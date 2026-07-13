"""
BookEngine
==========

Top-level orchestrator for the Book Engine. Sits **parallel** to
``ChatOrchestrator`` (i.e. it is **not** a ``BaseCapability``) and is the
single public entry point used by the API router, CLI, and SDK.

Lifecycle
---------

::

    create_book(...)         → BookProposal       (Stage 1, requires user confirm)
    confirm_proposal(...)    → Spine              (Stage 2, requires user confirm)
    confirm_spine(...)       → page shells + queued compilation
    compile_page(book, page) → Page               (Stage 3-4, drives BookCompiler)
    list_books(), load_book(), delete_book(), resume_book()

Compilation queue
-----------------

For each book a per-book ``asyncio.Queue`` schedules pages with priority:
- Highest priority: page the user just opened (handled inline).
- Background: remaining unfinished pages, processed by a single worker.

The engine emits all progress over a ``StreamBus`` (wrapped by ``BookStream``)
which the WebSocket router fans out to clients.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import time
from typing import Any

from deeptutor.core.stream_bus import StreamBus

from .agents.ideation_agent import IdeationAgent
from .agents.source_explorer import SourceExplorer
from .agents.spine_synthesizer import SpineSynthesizer
from .compiler import BookCompiler, CompilerOptions
from .inputs import IdeationContext, build_book_inputs
from .models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookInputs,
    BookProposal,
    BookStatus,
    Chapter,
    ContentType,
    ExplorationReport,
    Page,
    PageLink,
    PageStatus,
    Progress,
    QuizAttempt,
    Spine,
)
from .storage import BookStorage, get_book_storage
from .streaming import (
    STAGE_COMPILATION,
    STAGE_CRITIQUE,
    STAGE_EXPLORATION,
    STAGE_IDEATION,
    STAGE_OVERVIEW,
    STAGE_SPINE,
    STAGE_SYNTHESIS,
    BookStream,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Per-book runtime state (queues, workers)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _BookRuntime:
    """In-process per-book scheduling state."""

    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    queued: set[str] = field(default_factory=set)
    worker: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stream: BookStream | None = None  # default stream for background work


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


class BookEngine:
    """Process-wide orchestrator for the Book Engine."""

    def __init__(
        self,
        *,
        storage: BookStorage | None = None,
        compiler_options: CompilerOptions | None = None,
    ) -> None:
        self.storage = storage or get_book_storage()
        self.compiler = BookCompiler(
            storage=self.storage,
            options=compiler_options or CompilerOptions(phase=2),
        )
        self._runtimes: dict[str, _BookRuntime] = {}
        self._global_lock = asyncio.Lock()

    # ── Discovery / lifecycle ────────────────────────────────────────────

    def list_books(self) -> list[Book]:
        books: list[Book] = []
        for book_id in self.storage.list_book_ids():
            book = self.storage.load_book(book_id)
            if book is not None:
                books.append(book)
        books.sort(key=lambda b: b.updated_at, reverse=True)
        return books

    def load_book(self, book_id: str) -> Book | None:
        return self.storage.load_book(book_id)

    def load_spine(self, book_id: str) -> Spine | None:
        return self.storage.load_spine(book_id)

    def list_pages(self, book_id: str) -> list[Page]:
        return self.storage.list_pages(book_id)

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        return self.storage.load_page(book_id, page_id)

    def load_progress(self, book_id: str) -> Progress:
        progress = self.storage.load_progress(book_id)
        if progress is None:
            progress = Progress(book_id=book_id)
            self.storage.save_progress(progress)
        return progress

    def delete_book(self, book_id: str) -> bool:
        runtime = self._runtimes.pop(book_id, None)
        if runtime and runtime.worker and not runtime.worker.done():
            runtime.worker.cancel()
        return self.storage.delete_book(book_id)

    def set_page_chat_session(self, *, book_id: str, page_id: str, session_id: str) -> Book | None:
        """Persist the chat session associated with a specific book page."""
        book = self.storage.load_book(book_id)
        page = self.storage.load_page(book_id, page_id)
        clean_session_id = (session_id or "").strip()
        if book is None or page is None or not clean_session_id:
            return None

        metadata = dict(book.metadata or {})
        mapping = metadata.get("page_chat_sessions")
        if not isinstance(mapping, dict):
            mapping = {}
        mapping[str(page_id)] = clean_session_id
        metadata["page_chat_sessions"] = mapping
        book.metadata = metadata
        book.updated_at = time.time()
        self.storage.save_book(book)
        self.storage.append_log(
            book_id,
            f"page chat session mapped ({page_id} → {clean_session_id})",
            op="page_chat",
        )
        return book

    @staticmethod
    def _reset_page_for_force_compile(page: Page) -> None:
        """Reset generated block outputs while preserving user-authored notes."""
        for block in page.blocks:
            if block.type == BlockType.USER_NOTE:
                continue
            preserved_metadata = {
                key: value
                for key, value in (block.metadata or {}).items()
                if key in {"transition_in", "deep_dive_page_id"}
            }
            block.status = BlockStatus.PENDING
            block.payload = {}
            block.error = ""
            block.source_anchors = []
            block.metadata = preserved_metadata
            block.updated_at = time.time()
        page.status = PageStatus.PENDING
        page.error = ""
        page.updated_at = time.time()

    # ── Stage 1: Ideation ────────────────────────────────────────────────

    async def create_book(
        self,
        *,
        user_intent: str,
        chat_session_id: str = "",
        chat_selections: list[dict[str, Any]] | None = None,
        notebook_refs: list[dict[str, Any]] | None = None,
        knowledge_bases: list[str] | None = None,
        question_categories: list[int] | None = None,
        question_entries: list[int] | None = None,
        language: str = "en",
        stream: StreamBus | None = None,
    ) -> tuple[Book, BookProposal]:
        """Capture inputs, run IdeationAgent, persist DRAFT book + proposal."""
        bus = stream or StreamBus()
        bstream = BookStream(bus)

        async with bstream.stage(STAGE_IDEATION):
            await bstream.progress("Capturing inputs…", stage=STAGE_IDEATION)
            book_inputs, ideation_ctx = await build_book_inputs(
                user_intent=user_intent,
                chat_session_id=chat_session_id,
                chat_selections=chat_selections,
                notebook_refs=notebook_refs,
                knowledge_bases=knowledge_bases,
                question_categories=question_categories,
                question_entries=question_entries,
                language=language,
            )

            await bstream.progress(
                "Generating book proposal…",
                stage=STAGE_IDEATION,
            )
            proposal = await self._run_ideation(ideation_ctx, language)

            book = Book(
                title=proposal.title,
                description=proposal.description,
                status=BookStatus.DRAFT,
                proposal=proposal,
                knowledge_bases=book_inputs.knowledge_bases,
                language=language,
                chapter_count=proposal.estimated_chapters,
            )
            # Capture baseline KB fingerprints immediately so subsequent drift
            # checks have something to compare against. Without this the very
            # first health-check run treats every selected KB as "newly added"
            # and surfaces a spurious drift warning.
            try:
                from .kb_health import fingerprint_kbs

                if book.knowledge_bases:
                    book.kb_fingerprints = fingerprint_kbs(book.knowledge_bases)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"baseline fingerprint capture skipped: {exc}")
            self.storage.save_book(book)
            self.storage.save_inputs(book.id, book_inputs)
            self.storage.save_progress(Progress(book_id=book.id))
            self.storage.append_log(
                book.id, f"created (status=draft, title='{book.title}')", op="create"
            )

            await bstream.book_event(
                "proposal_ready",
                {
                    "book_id": book.id,
                    "title": book.title,
                    "proposal": proposal.model_dump(),
                },
                stage=STAGE_IDEATION,
            )

        return book, proposal

    async def _run_ideation(self, ctx: IdeationContext, language: str) -> BookProposal:
        agent = IdeationAgent(language=language)
        return await agent.process(ideation_context=ctx)

    # ── Stage 2: Spine ───────────────────────────────────────────────────

    async def confirm_proposal(
        self,
        *,
        book_id: str,
        edited_proposal: BookProposal | None = None,
        stream: StreamBus | None = None,
    ) -> tuple[Book, Spine]:
        """User confirms (and optionally edits) the proposal → run SpineAgent."""
        book = self.storage.load_book(book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")

        if edited_proposal is not None:
            book.proposal = edited_proposal
            book.title = edited_proposal.title or book.title
            book.description = edited_proposal.description or book.description

        bus = stream or StreamBus()
        bstream = BookStream(bus)

        proposal = book.proposal or BookProposal(title=book.title)
        inputs = self.storage.load_inputs(book.id) or BookInputs(
            user_intent=book.title or "",
            knowledge_bases=list(book.knowledge_bases),
            language=book.language,
        )

        async with bstream.stage(STAGE_SPINE):
            # ── Sub-stage 1: Source exploration ──────────────────────
            exploration: ExplorationReport | None = None
            try:
                async with bstream.stage(STAGE_EXPLORATION):
                    await bstream.progress(
                        "Exploring your sources in parallel…",
                        stage=STAGE_EXPLORATION,
                    )
                    explorer = SourceExplorer(language=book.language)
                    exploration = await explorer.explore(
                        book_id=book.id,
                        proposal=proposal,
                        inputs=inputs,
                    )
                    self.storage.save_exploration(book.id, exploration)
                    await bstream.book_event(
                        "exploration_ready",
                        {
                            "book_id": book.id,
                            "queries": exploration.queries,
                            "coverage": exploration.coverage,
                            "candidate_concepts": exploration.candidate_concepts,
                            "summary": exploration.summary,
                        },
                        stage=STAGE_EXPLORATION,
                    )
            except Exception as exc:
                logger.warning(f"SourceExplorer failed for {book.id}: {exc}")
                exploration = None
                await bstream.progress(
                    "Source exploration unavailable — falling back to proposal-only spine.",
                    stage=STAGE_EXPLORATION,
                )

            # ── Sub-stage 2: Synthesise spine + concept graph ────────
            synthesizer = SpineSynthesizer(language=book.language)

            async def _on_round(label: str, payload: dict[str, Any]) -> None:
                stage = STAGE_CRITIQUE if label.startswith("critique") else STAGE_SYNTHESIS
                # Don't push the full payload; just enough to drive the timeline.
                summary = {
                    "round": label,
                    "chapter_count": len(payload.get("chapters") or [])
                    if isinstance(payload.get("chapters"), list)
                    else 0,
                    "issue_count": len(payload.get("issues") or [])
                    if isinstance(payload.get("issues"), list)
                    else 0,
                    "verdict": payload.get("verdict") or "",
                }
                await bstream.book_event(
                    "spine_round", {"book_id": book.id, **summary}, stage=stage
                )

            async with bstream.stage(STAGE_SYNTHESIS):
                await bstream.progress("Synthesising spine + concept graph…", stage=STAGE_SYNTHESIS)
                spine = await synthesizer.synthesize(
                    book_id=book.id,
                    proposal=proposal,
                    exploration=exploration,
                    on_round=_on_round,
                )

            book.chapter_count = len(spine.chapters)
            book.status = BookStatus.SPINE_READY
            self.storage.save_book(book)
            self.storage.save_spine(spine)
            self.storage.append_log(
                book.id,
                f"spine generated ({len(spine.chapters)} chapters, "
                f"{len(spine.concept_graph.nodes)} concepts)",
                op="spine",
            )

            await bstream.book_event(
                "spine_ready",
                {
                    "book_id": book.id,
                    "chapter_count": len(spine.chapters),
                    "concept_node_count": len(spine.concept_graph.nodes),
                    "concept_edge_count": len(spine.concept_graph.edges),
                    "spine": spine.model_dump(),
                },
                stage=STAGE_SPINE,
            )
        return book, spine

    # ── Stage 2.5: Overview chapter injection ───────────────────────────

    async def _ensure_overview_chapter(
        self,
        spine: Spine,
        book: Book,
        *,
        stream: StreamBus | None,
    ) -> Spine:
        """Insert an Overview chapter at position 0 (idempotent)."""
        # Idempotent guard — already injected?
        first = spine.chapters[0] if spine.chapters else None
        already = bool(
            first
            and (
                first.content_type == ContentType.OVERVIEW
                or (first.__pydantic_extra__ or {}).get("auto_overview") is True
            )
        )
        if already:
            return spine

        overview_title = "本书导览" if book.language == "zh" else "How to read this book"
        objectives = (
            [
                "了解整本书的章节脉络",
                "掌握各章之间的概念依赖关系",
                "选择最合适的阅读顺序",
            ]
            if book.language == "zh"
            else [
                "See the full chapter map at a glance",
                "Understand how concepts depend on each other",
                "Pick the reading path that fits your goals",
            ]
        )
        overview = Chapter(
            title=overview_title,
            learning_objectives=objectives,
            content_type=ContentType.OVERVIEW,
            summary=(
                "Auto-generated overview of the book's concept graph and chapter index."
                if book.language != "zh"
                else "自动生成的概念图与章节索引，作为本书的入口。"
            ),
            order=0,
        )
        # Mark for idempotency on subsequent runs.
        overview.__pydantic_extra__ = overview.__pydantic_extra__ or {}
        overview.__pydantic_extra__["auto_overview"] = True

        # Re-number existing chapters down by one.
        for ch in spine.chapters:
            ch.order = ch.order + 1
        spine.chapters = [overview, *spine.chapters]
        return spine

    async def _materialize_overview_page(
        self,
        spine: Spine,
        pages: list[Page],
        book: Book,
        *,
        stream: StreamBus | None,
    ) -> None:
        """Build the Overview page's blocks deterministically."""
        if not spine.chapters:
            return
        overview_chapter = spine.chapters[0]
        if overview_chapter.content_type != ContentType.OVERVIEW:
            return

        overview_page = next((p for p in pages if p.chapter_id == overview_chapter.id), None)
        if overview_page is None or overview_page.status == PageStatus.READY:
            return

        zh = book.language == "zh"
        chapter_index = [
            {
                "id": ch.id,
                "title": ch.title,
                "summary": ch.summary,
                "objectives": list(ch.learning_objectives),
                "order": ch.order,
                "content_type": ch.content_type.value,
                "page_id": (ch.page_ids[0] if ch.page_ids else ""),
            }
            for ch in spine.chapters
            if ch.content_type != ContentType.OVERVIEW
        ]

        # 1) Intro text block (pre-rendered, status=READY)
        intro_md = (
            (
                f"# {book.title or '本书'}\n\n"
                f"{(book.proposal.description if book.proposal else '') or ''}\n\n"
                f"下方的概念图展示了本书 {len(spine.concept_graph.nodes)} 个核心概念以及"
                f"它们之间的依赖关系；再下方是 {len(chapter_index)} 个章节的入口。"
                f"你可以按从上到下的顺序阅读，也可以根据自己的兴趣或先验知识选择切入点。"
            )
            if zh
            else (
                f"# {book.title or 'This book'}\n\n"
                f"{(book.proposal.description if book.proposal else '') or ''}\n\n"
                f"The diagram below maps the {len(spine.concept_graph.nodes)} core "
                f"concepts in this book and how they depend on each other. The "
                f"chapter index that follows lists all {len(chapter_index)} "
                f"chapters — read top-to-bottom for the recommended path, or jump "
                f"straight to whatever you're most curious about."
            )
        )
        intro_block = Block(
            type=BlockType.TEXT,
            status=BlockStatus.READY,
            title=("如何阅读这本书" if zh else "How to read this book"),
            params={"role": "overview_intro"},
            payload={"content": intro_md, "format": "markdown"},
        )

        # 2) Concept graph block — render deterministically
        from .blocks.concept_graph import render_mermaid

        graph_block = Block(
            type=BlockType.CONCEPT_GRAPH,
            status=BlockStatus.READY,
            title=("概念图" if zh else "Concept map"),
            params={
                "concept_graph": spine.concept_graph.model_dump(),
                "chapter_index": chapter_index,
            },
            payload={
                "render_type": "concept_graph",
                "code": {
                    "language": "mermaid",
                    "content": render_mermaid(spine.concept_graph),
                },
                "graph": spine.concept_graph.model_dump(),
                "index": {
                    "chapters": chapter_index,
                    "node_to_chapter": {
                        n.id: n.chapter_id for n in spine.concept_graph.nodes if n.chapter_id
                    },
                },
            },
            metadata={
                "node_count": len(spine.concept_graph.nodes),
                "edge_count": len(spine.concept_graph.edges),
            },
        )

        # 3) Chapter index callout — also rendered deterministically
        index_lines = []
        for entry in chapter_index:
            line = f"- **{entry['title']}**"
            if entry.get("summary"):
                line += f" — {entry['summary']}"
            index_lines.append(line)
        index_md = ("## 章节索引\n\n" if zh else "## Chapter index\n\n") + "\n".join(index_lines)
        index_block = Block(
            type=BlockType.TEXT,
            status=BlockStatus.READY,
            title=("章节索引" if zh else "Chapter index"),
            params={"role": "chapter_index"},
            payload={"content": index_md, "format": "markdown"},
        )

        overview_page.blocks = [intro_block, graph_block, index_block]
        overview_page.status = PageStatus.READY
        overview_page.content_type = ContentType.OVERVIEW
        self.storage.save_page(overview_page)

        if stream is not None:
            bstream = BookStream(stream)
            await bstream.book_event(
                "overview_ready",
                {
                    "book_id": book.id,
                    "page_id": overview_page.id,
                    "node_count": len(spine.concept_graph.nodes),
                    "chapter_count": len(chapter_index),
                },
                stage=STAGE_OVERVIEW,
            )

    # ── Stage 3: confirm spine + create page shells ─────────────────────

    async def confirm_spine(
        self,
        *,
        book_id: str,
        edited_spine: Spine | None = None,
        stream: StreamBus | None = None,
        auto_compile: bool = True,
    ) -> list[Page]:
        """User confirms (or edits) the spine → create pending page shells.

        BookEngine v2: automatically injects an **Overview** chapter at order 0
        whose page is fully pre-built (deterministic concept-graph render +
        intro text + chapter index). The rest of the chapters are queued for
        normal compilation.
        """
        book = self.storage.load_book(book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")

        spine = edited_spine or self.storage.load_spine(book_id)
        if spine is None:
            raise ValueError(f"No spine for book {book_id}")
        if edited_spine is not None:
            spine.book_id = book_id
            self.storage.save_spine(spine)

        # ── Inject Overview chapter (idempotent) ─────────────────────
        spine = await self._ensure_overview_chapter(spine, book, stream=stream)
        self.storage.save_spine(spine)

        existing = {p.chapter_id: p for p in self.storage.list_pages(book_id)}
        pages: list[Page] = []
        for chapter in spine.chapters:
            page = existing.get(chapter.id)
            if page is None:
                page = Page(
                    book_id=book_id,
                    chapter_id=chapter.id,
                    title=chapter.title,
                    learning_objectives=list(chapter.learning_objectives),
                    content_type=chapter.content_type,
                    order=chapter.order,
                    status=PageStatus.PENDING,
                )
                self.storage.save_page(page)
                chapter.page_ids = [page.id]
                self.storage.save_spine(spine)
            pages.append(page)

        # Build the Overview page eagerly (no LLM, no queue).
        await self._materialize_overview_page(spine, pages, book, stream=stream)

        book.page_count = len(pages)
        book.status = BookStatus.COMPILING if auto_compile else BookStatus.SPINE_READY
        self.storage.save_book(book)
        self.storage.append_log(
            book_id,
            f"spine confirmed ({len(pages)} page shells, auto_compile={auto_compile})",
            op="confirm_spine",
        )

        if auto_compile:
            await self._enqueue_pending_pages(book_id, pages, stream=stream)
        return pages

    async def rebuild_book(
        self,
        *,
        book_id: str,
        stream: StreamBus | None = None,
        auto_compile: bool = True,
    ) -> list[Page]:
        """Regenerate all pages while preserving the confirmed proposal/spine."""
        book = self.storage.load_book(book_id)
        spine = self.storage.load_spine(book_id)
        if book is None or spine is None:
            raise ValueError(f"Cannot rebuild book – missing book/spine ({book_id})")

        runtime = self._runtimes.get(book_id)
        if runtime is not None:
            async with runtime.lock:
                if runtime.worker is not None and not runtime.worker.done():
                    runtime.worker.cancel()
                    runtime.worker = None
                runtime.queued.clear()
                while not runtime.queue.empty():
                    try:
                        runtime.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        for page in self.storage.list_pages(book_id):
            self.storage.delete_page(book_id, page.id)
        for chapter in spine.chapters:
            chapter.page_ids = []
        self.storage.save_spine(spine)
        self.storage.save_progress(Progress(book_id=book_id))

        book.status = BookStatus.SPINE_READY
        book.page_count = 0
        book.updated_at = time.time()
        self.storage.save_book(book)
        self.storage.append_log(
            book_id,
            f"rebuild requested (preserve_spine=true, auto_compile={auto_compile})",
            op="rebuild",
        )

        return await self.confirm_spine(
            book_id=book_id,
            edited_spine=spine,
            stream=stream,
            auto_compile=auto_compile,
        )

    # ── Stage 3-4: compile a single page (current page) ──────────────────

    async def compile_page(
        self,
        *,
        book_id: str,
        page_id: str,
        stream: StreamBus | None = None,
        force: bool = False,
    ) -> Page:
        """Drive the compiler for one page (used when a user opens it)."""
        book = self.storage.load_book(book_id)
        spine = self.storage.load_spine(book_id)
        page = self.storage.load_page(book_id, page_id)
        if book is None or spine is None or page is None:
            raise ValueError(f"Cannot compile page – missing book/spine/page ({book_id}/{page_id})")
        if page.status == PageStatus.READY and not force:
            return page

        # Overview pages are built deterministically from the spine (intro,
        # concept graph, chapter index). Never run the generic LLM compiler over
        # their hand-built blocks — that would overwrite the deterministic
        # "How to read this book" intro and chapter index with hallucinated
        # prose. Reaching here means force=True or the page is not yet READY, so
        # rebuild deterministically (this also refreshes a changed spine).
        if page.content_type == ContentType.OVERVIEW:
            page.status = PageStatus.PENDING
            self.storage.save_page(page)
            await self._materialize_overview_page(spine, [page], book, stream=stream)
            page = self.storage.load_page(book_id, page_id) or page
            await self._maybe_finalize_book(book_id)
            return page

        if force:
            self._reset_page_for_force_compile(page)
            self.storage.save_page(page)

        chapter = spine.chapter_by_id(page.chapter_id)
        if chapter is None:
            raise ValueError(f"Page {page_id} references unknown chapter {page.chapter_id}")

        bus = stream or StreamBus()
        bstream = BookStream(bus)

        async with bstream.stage(STAGE_COMPILATION):
            page = await self.compiler.compile_page(
                book_id=book_id,
                chapter=chapter,
                page=page,
                stream=bstream,
                knowledge_bases=book.knowledge_bases,
                language=book.language,
            )

        # Refresh KB fingerprints once we successfully ship a READY page.
        # We capture them lazily so a brand-new book gets its baseline as
        # soon as the very first page is compiled.
        if page.status == PageStatus.READY:
            try:
                from .kb_health import refresh_book_fingerprints

                refreshed = self.storage.load_book(book_id)
                if refreshed is not None and not refreshed.kb_fingerprints:
                    refresh_book_fingerprints(book_id, storage=self.storage)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"fingerprint refresh skipped: {exc}")

        await self._maybe_finalize_book(book_id)
        return page

    # ── Background compilation queue ─────────────────────────────────────

    async def _enqueue_pending_pages(
        self,
        book_id: str,
        pages: list[Page],
        *,
        stream: StreamBus | None = None,
    ) -> None:
        runtime = await self._get_or_create_runtime(book_id, stream)
        async with runtime.lock:
            for page in pages:
                if page.status == PageStatus.READY:
                    continue
                if page.id in runtime.queued:
                    continue
                runtime.queued.add(page.id)
                await runtime.queue.put(page.id)
            self._ensure_worker(book_id)

    async def _get_or_create_runtime(self, book_id: str, stream: StreamBus | None) -> _BookRuntime:
        async with self._global_lock:
            runtime = self._runtimes.get(book_id)
            if runtime is None:
                runtime = _BookRuntime()
                self._runtimes[book_id] = runtime
            if stream is not None and runtime.stream is None:
                runtime.stream = BookStream(stream)
            elif runtime.stream is None:
                runtime.stream = BookStream(StreamBus())
            return runtime

    def _ensure_worker(self, book_id: str) -> None:
        runtime = self._runtimes.get(book_id)
        if runtime is None:
            return
        if runtime.worker is not None and not runtime.worker.done():
            return
        runtime.worker = asyncio.create_task(self._worker_loop(book_id))

    async def _worker_loop(self, book_id: str) -> None:
        runtime = self._runtimes.get(book_id)
        if runtime is None:
            return
        bstream = runtime.stream or BookStream(StreamBus())
        while True:
            try:
                page_id = await asyncio.wait_for(runtime.queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                async with runtime.lock:
                    if runtime.queue.empty():
                        runtime.worker = None
                        return
                continue

            try:
                book = self.storage.load_book(book_id)
                spine = self.storage.load_spine(book_id)
                page = self.storage.load_page(book_id, page_id)
                if book is None or spine is None or page is None:
                    continue
                if page.status == PageStatus.READY:
                    continue
                chapter = spine.chapter_by_id(page.chapter_id)
                if chapter is None:
                    continue
                await self.compiler.compile_page(
                    book_id=book_id,
                    chapter=chapter,
                    page=page,
                    stream=bstream,
                    knowledge_bases=book.knowledge_bases,
                    language=book.language,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    f"Background compilation failed for {book_id}/{page_id}: {exc}",
                    exc_info=True,
                )
                self.storage.append_log(
                    book_id,
                    f"background compile failed for page {page_id}: {exc}",
                    op="compile_error",
                )
            finally:
                runtime.queued.discard(page_id)

            await self._maybe_finalize_book(book_id)

    async def _maybe_finalize_book(self, book_id: str) -> None:
        book = self.storage.load_book(book_id)
        if book is None:
            return
        pages = self.storage.list_pages(book_id)
        if not pages:
            return
        if all(p.status == PageStatus.READY for p in pages):
            if book.status != BookStatus.READY:
                book.status = BookStatus.READY
                self.storage.save_book(book)
                self.storage.append_log(book_id, "all pages ready → status=READY", op="finalize")

    # ── Block-level controls (Phase 1: regenerate single block) ─────────

    async def regenerate_block(
        self,
        *,
        book_id: str,
        page_id: str,
        block_id: str,
        params_override: dict[str, Any] | None = None,
        stream: StreamBus | None = None,
    ) -> Block | None:
        """Re-run a single block generator (e.g. user clicked 'regenerate')."""
        book = self.storage.load_book(book_id)
        spine = self.storage.load_spine(book_id)
        page = self.storage.load_page(book_id, page_id)
        if book is None or spine is None or page is None:
            return None
        chapter = spine.chapter_by_id(page.chapter_id)
        if chapter is None:
            return None
        block = page.block_by_id(block_id)
        if block is None:
            return None
        if params_override:
            block.params = {**block.params, **params_override}

        bus = stream or StreamBus()
        bstream = BookStream(bus)

        from .blocks.base import BlockContext, get_block_registry

        registry = get_block_registry()
        generator = registry.get(block.type)
        if generator is None:
            block.error = f"No generator for {block.type.value}"
            self.storage.save_page(page)
            return block

        ctx = BlockContext(
            book_id=book_id,
            chapter=chapter,
            page=page,
            block=block,
            language=book.language,
            knowledge_bases=book.knowledge_bases,
        )
        # Resolve previous block by planning order so the bridge text can be
        # refreshed alongside the block itself.
        prev_block: Block | None = None
        for candidate in page.blocks:
            if candidate.id == block.id:
                break
            prev_block = candidate

        async with bstream.stage(STAGE_COMPILATION):
            await generator.generate(ctx)
            if block.status.value == "ready":
                await self.compiler.attach_bridge_text(
                    block,
                    chapter=chapter,
                    previous_block=prev_block,
                    language=book.language,
                )
            self.storage.save_page(page)
            self.compiler._finalize_page_status(page)
            self.storage.save_page(page)
            await self._maybe_finalize_book(book_id)
        return block

    # ── Maintenance / health (Phase 4) ─────────────────────────────────

    def kb_drift_report(self, book_id: str) -> dict[str, Any]:
        """Compute and persist the current KB drift report for *book_id*."""
        from .kb_health import mark_drift_on_book

        report = mark_drift_on_book(book_id, storage=self.storage)
        if report is None:
            return {"book_id": book_id, "has_drift": False, "missing": True}
        return report.to_dict()

    def refresh_kb_fingerprints(self, book_id: str) -> dict[str, Any] | None:
        from .kb_health import refresh_book_fingerprints

        book = refresh_book_fingerprints(book_id, storage=self.storage)
        if book is None:
            return None
        return {
            "book_id": book.id,
            "kb_fingerprints": book.kb_fingerprints,
            "stale_page_ids": book.stale_page_ids,
        }

    def log_health(self, book_id: str) -> dict[str, Any]:
        from .kb_health import scan_log_health

        return scan_log_health(book_id, storage=self.storage).to_dict()

    # ── Block CRUD operations (Phase 3) ────────────────────────────────

    async def insert_block(
        self,
        *,
        book_id: str,
        page_id: str,
        block_type: BlockType,
        params: dict[str, Any] | None = None,
        position: int | None = None,
        stream: StreamBus | None = None,
        compile_now: bool = True,
    ) -> Block | None:
        """Insert a fresh PENDING block at *position* (default: end)."""
        spine = self.storage.load_spine(book_id)
        page = self.storage.load_page(book_id, page_id)
        if spine is None or page is None:
            return None
        chapter = spine.chapter_by_id(page.chapter_id)
        if chapter is None:
            return None

        merged_params: dict[str, Any] = {
            "chapter_title": chapter.title,
            "chapter_summary": chapter.summary,
            "objectives": chapter.learning_objectives,
            **(params or {}),
        }
        block = Block(type=block_type, status=BlockStatus.PENDING, params=merged_params)
        if position is None or position >= len(page.blocks) or position < 0:
            page.blocks.append(block)
        else:
            page.blocks.insert(position, block)
        self.storage.save_page(page)

        if compile_now and block_type != BlockType.USER_NOTE:
            from .blocks.base import BlockContext, get_block_registry

            generator = get_block_registry().get(block_type)
            if generator is not None:
                ctx = BlockContext(
                    book_id=book_id,
                    chapter=chapter,
                    page=page,
                    block=block,
                    language=self.storage.load_book(book_id).language
                    if self.storage.load_book(book_id)
                    else "en",
                    knowledge_bases=self.storage.load_book(book_id).knowledge_bases
                    if self.storage.load_book(book_id)
                    else [],
                )
                bus = stream or StreamBus()
                bstream = BookStream(bus)
                async with bstream.stage(STAGE_COMPILATION):
                    await generator.generate(ctx)
                self.compiler._finalize_page_status(page)
                self.storage.save_page(page)
        elif block_type == BlockType.USER_NOTE:
            block.status = BlockStatus.READY
            block.payload = {
                "format": "markdown",
                "body": str(merged_params.get("body") or ""),
                "author": "user",
            }
            self.storage.save_page(page)
        self.storage.append_log(
            book_id,
            f"inserted {block_type.value} block on page {page_id} (pos={position})",
            op="insert_block",
        )
        return block

    async def delete_block(self, *, book_id: str, page_id: str, block_id: str) -> bool:
        page = self.storage.load_page(book_id, page_id)
        if page is None:
            return False
        before = len(page.blocks)
        page.blocks = [b for b in page.blocks if b.id != block_id]
        if len(page.blocks) == before:
            return False
        self.compiler._finalize_page_status(page)
        self.storage.save_page(page)
        self.storage.append_log(
            book_id, f"deleted block {block_id} from page {page_id}", op="delete_block"
        )
        return True

    async def move_block(
        self, *, book_id: str, page_id: str, block_id: str, new_position: int
    ) -> bool:
        page = self.storage.load_page(book_id, page_id)
        if page is None:
            return False
        idx = next((i for i, b in enumerate(page.blocks) if b.id == block_id), -1)
        if idx < 0:
            return False
        new_position = max(0, min(len(page.blocks) - 1, new_position))
        block = page.blocks.pop(idx)
        page.blocks.insert(new_position, block)
        self.storage.save_page(page)
        self.storage.append_log(
            book_id,
            f"moved block {block_id} on page {page_id} → pos {new_position}",
            op="move_block",
        )
        return True

    async def change_block_type(
        self,
        *,
        book_id: str,
        page_id: str,
        block_id: str,
        new_type: BlockType,
        params_override: dict[str, Any] | None = None,
        stream: StreamBus | None = None,
    ) -> Block | None:
        spine = self.storage.load_spine(book_id)
        page = self.storage.load_page(book_id, page_id)
        if spine is None or page is None:
            return None
        chapter = spine.chapter_by_id(page.chapter_id)
        if chapter is None:
            return None
        block = page.block_by_id(block_id)
        if block is None:
            return None
        block.type = new_type
        block.status = BlockStatus.PENDING
        block.payload = {}
        block.error = ""
        if params_override:
            block.params = {**block.params, **params_override}
        self.storage.save_page(page)
        # Re-run generator immediately
        return await self.regenerate_block(
            book_id=book_id, page_id=page_id, block_id=block_id, stream=stream
        )

    # ── Deep-dive sub-page (Phase 3) ──────────────────────────────────

    async def create_deep_dive_subpage(
        self,
        *,
        book_id: str,
        parent_page_id: str,
        topic: str,
        block_id: str | None = None,
        content_type: ContentType = ContentType.CONCEPT,
        stream: StreamBus | None = None,
    ) -> Page | None:
        """Spawn a child Page that deepens *topic* and link it from the parent."""
        book = self.storage.load_book(book_id)
        spine = self.storage.load_spine(book_id)
        parent = self.storage.load_page(book_id, parent_page_id)
        if book is None or spine is None or parent is None:
            return None

        # Add a synthetic chapter so the planner has a target
        chapter = Chapter(
            title=f"{topic} (deep dive)",
            learning_objectives=[f"Go deeper into {topic}"],
            content_type=content_type,
            summary=f"Sub-chapter spawned from {parent.title}.",
            order=len(spine.chapters),
        )
        spine.chapters.append(chapter)
        self.storage.save_spine(spine)

        sub = Page(
            book_id=book_id,
            chapter_id=chapter.id,
            title=topic,
            learning_objectives=list(chapter.learning_objectives),
            content_type=content_type,
            status=PageStatus.PENDING,
            order=len(self.storage.list_pages(book_id)),
            parent_page_id=parent.id,
        )
        self.storage.save_page(sub)
        chapter.page_ids = [sub.id]
        self.storage.save_spine(spine)

        # Add link from parent → sub
        parent.links.append(PageLink(target_page_id=sub.id, relation="deepens", label=topic))
        if block_id:
            block = parent.block_by_id(block_id)
            if block is not None:
                block.metadata = {**block.metadata, "deep_dive_page_id": sub.id}
        self.storage.save_page(parent)

        # Compile the new page now (blocking, so caller gets ready content)
        await self.compile_page(book_id=book_id, page_id=sub.id, stream=stream)
        self.storage.append_log(
            book_id,
            f"deep-dive page {sub.id} spawned from {parent_page_id}: {topic}",
            op="deep_dive",
        )
        return self.storage.load_page(book_id, sub.id)

    # ── Quiz attempts (Phase 3) ────────────────────────────────────────

    async def record_quiz_attempt(
        self,
        *,
        book_id: str,
        page_id: str,
        block_id: str,
        question_id: str,
        user_answer: str,
        is_correct: bool,
    ) -> Progress:
        progress = self.load_progress(book_id)
        progress.quiz_attempts.append(
            QuizAttempt(
                block_id=block_id,
                page_id=page_id,
                question_id=question_id,
                user_answer=user_answer,
                is_correct=is_correct,
            )
        )
        if not is_correct:
            page = self.storage.load_page(book_id, page_id)
            if page and page.chapter_id and page.chapter_id not in progress.weak_chapters:
                progress.weak_chapters.append(page.chapter_id)
        else:
            progress.score += 1
        self.storage.save_progress(progress)
        return progress

    async def supplement_for_weakness(
        self,
        *,
        book_id: str,
        page_id: str,
        topic: str,
        stream: StreamBus | None = None,
    ) -> Block | None:
        """Append an extra TEXT + QUIZ block when the user struggles."""
        await self.insert_block(
            book_id=book_id,
            page_id=page_id,
            block_type=BlockType.CALLOUT,
            params={"variant": "common_pitfall", "topic": topic},
            stream=stream,
        )
        await self.insert_block(
            book_id=book_id,
            page_id=page_id,
            block_type=BlockType.TEXT,
            params={"role": "remediation", "topic": topic},
            stream=stream,
        )
        return await self.insert_block(
            book_id=book_id,
            page_id=page_id,
            block_type=BlockType.QUIZ,
            params={"num_questions": 2, "difficulty": "easy", "topic": topic},
            stream=stream,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────


_engines: dict[str, BookEngine] = {}


def get_book_engine() -> BookEngine:
    from deeptutor.services.path_service import get_path_service

    key = str(get_path_service().workspace_root.resolve())
    if key not in _engines:
        _engines[key] = BookEngine()
    return _engines[key]


__all__ = ["BookEngine", "get_book_engine"]
