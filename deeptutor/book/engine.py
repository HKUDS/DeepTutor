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
    resume_book(...)         → re-queue unfinished pages, keeping what exists
    rebuild_book(...)        → discard every page and regenerate from the spine
    list_books(), load_book(), delete_book()

Compilation queue
-----------------

Each book gets a ``_BookRuntime``: an ``asyncio.Queue`` of pending pages, one
background worker, and an **in-flight table** keyed by page id. Every path that
can compile a page — the reader opening one, the worker reaching one, a forced
regenerate — goes through :meth:`BookEngine.compile_page`, which consults that
table so concurrent requests for the same page join a single run instead of
racing into duplicate generations.

The worker trips a breaker (``CONSECUTIVE_PAGE_FAILURE_LIMIT``) when pages fail
for provider-level reasons, pausing the book rather than grinding the remaining
chapters into half-generated debris.

Progress is published to the book's long-lived stream in :mod:`.event_hub`,
never to a request-scoped bus — background compilation must keep streaming
after the call that queued it has returned.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
import logging
import time
from typing import Any

from deeptutor.core.stream_bus import StreamBus

from . import progress as progress_ops
from .agents.ideation_agent import IdeationAgent
from .agents.source_explorer import SourceExplorer
from .agents.spine_synthesizer import SpineSynthesizer
from .compiler import BookCompiler, CompilerOptions, systemic_failure_reason
from .event_hub import close_book_bus, get_book_bus
from .inputs import IdeationContext, build_book_inputs
from .models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookDepth,
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
    Spine,
)
from .overview_copy import overview_copy
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


# A page that fails *entirely* for provider-level reasons (quota exhausted,
# credentials revoked, provider down) will be followed by more of the same, so
# the queue trips a breaker instead of grinding the rest of the book into
# half-generated pages. Ungenerated pages are an asset; half-generated ones are
# debris the user has to clean up.
CONSECUTIVE_PAGE_FAILURE_LIMIT = 2


# Statuses that mean "this page still has work owed to it". PARTIAL is
# deliberately absent: the compiler already ran every block and some failed for
# good, so re-queueing it on each open would re-spend the same model calls
# forever without changing the outcome. Force-regenerate is the way back in.
_UNFINISHED_PAGE_STATUSES = frozenset(
    {
        PageStatus.PENDING,
        PageStatus.PLANNING,
        PageStatus.GENERATING,
        PageStatus.ERROR,
    }
)


# Blocks whose content is a single run of prose the reader can correct in
# place. Everything else carries structured payloads — a section's subsections,
# a quiz's questions, a figure's source — where a plain text box would either
# destroy the structure or edit a field nothing renders. Those stay on
# regenerate.
_EDITABLE_BLOCK_TYPES = frozenset({BlockType.TEXT, BlockType.USER_NOTE, BlockType.CALLOUT})


def _body_key(block: Block) -> str:
    """Which payload key holds a block's prose.

    ``TEXT`` blocks are inconsistent by history: the generator writes ``body``
    while the deterministic overview blocks write ``content``. Respect whatever
    the block already uses so an edit lands where the renderer reads.
    """
    if block.type == BlockType.TEXT and "content" in (block.payload or {}):
        return "content"
    return "body"


def _prune_concept_graph(spine: Spine) -> int:
    """Drop graph nodes whose chapter no longer exists, and dangling edges.

    The concept graph is built once, before the reader ever opens the spine
    editor, and is never rebuilt. Deleting a chapter therefore left its concept
    on the Overview page's map — the book's own front page contradicting its
    table of contents. Pruning is deterministic and costs no model call; the
    remaining graph is still the one that was synthesised, just without the
    parts the reader removed.

    Returns the number of nodes dropped.
    """
    graph = spine.concept_graph
    if not graph.nodes:
        return 0

    live_chapters = {c.id for c in spine.chapters}
    kept = [n for n in graph.nodes if not n.chapter_id or n.chapter_id in live_chapters]
    dropped = len(graph.nodes) - len(kept)
    if not dropped:
        return 0

    kept_ids = {n.id for n in kept}
    graph.nodes = kept
    graph.edges = [e for e in graph.edges if e.src in kept_ids and e.dst in kept_ids]
    return dropped


def _is_auto_overview(chapter: Chapter) -> bool:
    """Whether *chapter* is the engine-injected overview.

    Checks both markers: ``content_type`` survives a round trip through the
    typed model, while the ``auto_overview`` extra survives a chapter whose
    content type was changed by hand in the spine editor.
    """
    return (
        chapter.content_type == ContentType.OVERVIEW
        or (chapter.__pydantic_extra__ or {}).get("auto_overview") is True
    )


def _coerce_depth(value: str | BookDepth | None) -> BookDepth:
    """Accept anything the API layer might pass; fall back to STANDARD."""
    if isinstance(value, BookDepth):
        return value
    try:
        return BookDepth(str(value or "").strip().lower())
    except ValueError:
        return BookDepth.STANDARD


@dataclass
class _BookRuntime:
    """In-process per-book **scheduling** state.

    Deliberately owns no event stream: streams live in :mod:`.event_hub` and
    outlive any single request, so background compilation keeps broadcasting
    after the call that queued it has returned.
    """

    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    queued: set[str] = field(default_factory=set)
    # page_id → the task currently compiling it. The single source of truth for
    # "is this page already being built", shared by the foreground
    # ``compile_page`` path and the background worker so they can never race
    # into compiling the same page twice.
    in_flight: dict[str, asyncio.Task[Page]] = field(default_factory=dict)
    worker: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    consecutive_page_failures: int = 0


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

    def reading_summary(self, book: Book) -> dict[str, Any]:
        """How far the reader has got, cheap enough to compute for a whole shelf.

        Reads only ``progress.json`` and the page count already on the manifest
        — deliberately no ``list_pages``, which would turn drawing the library
        into one directory scan per book.
        """
        progress = self.storage.load_progress(book.id)
        total = max(0, book.page_count)
        if progress is None:
            return {
                "current_page_id": "",
                "visited_pages": 0,
                "total_pages": total,
                "percent": 0,
            }
        return {
            "current_page_id": progress.current_page_id,
            "visited_pages": len(set(progress.visited_page_ids)),
            "total_pages": total,
            "percent": round(progress_ops.completion_ratio(progress, total) * 100),
        }

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
        if runtime is not None:
            if runtime.worker and not runtime.worker.done():
                runtime.worker.cancel()
            for task in runtime.in_flight.values():
                if not task.done():
                    task.cancel()
        # The book's event stream is the one thing that outlives its requests,
        # so deletion is the only place allowed to close it.
        close_book_bus(book_id)
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
        """Reset generated block outputs while preserving anything user-authored.

        Notes and hand-edited prose survive a forced regenerate. A reader who
        corrected a sentence and then hit "regenerate page" should not silently
        lose their correction — the two actions have nothing to do with each
        other from their point of view.
        """
        for block in page.blocks:
            if block.type == BlockType.USER_NOTE:
                continue
            if (block.metadata or {}).get("edited_by_user"):
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
        depth: str = BookDepth.STANDARD.value,
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
                depth=_coerce_depth(depth),
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

        bus = stream or get_book_bus(book_id)
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
                    if (book.metadata or {}).get("exploration_failed"):
                        book.metadata = {
                            k: v
                            for k, v in book.metadata.items()
                            if k not in ("exploration_failed", "exploration_error")
                        }
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
                book.metadata = {
                    **(book.metadata or {}),
                    "exploration_failed": True,
                    "exploration_error": str(exc)[:400],
                }
                self.storage.save_book(book)
                self.storage.append_log(
                    book_id,
                    f"source exploration failed, spine built from the proposal alone: {exc}",
                    op="exploration_failed",
                )
                await bstream.book_event(
                    "exploration_failed",
                    {"book_id": book.id, "reason": str(exc)[:400]},
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
        """Ensure exactly one Overview chapter, first in the spine (idempotent).

        Identity, not position, decides whether one already exists. Keying the
        guard on ``chapters[0]`` meant any caller that handed the spine back
        with the overview elsewhere in the list — the spine editor re-appends
        hidden chapters after the user's own — silently got a second one on
        every re-confirm, each with its own page.
        """
        existing = [c for c in spine.chapters if _is_auto_overview(c)]
        if existing:
            keep, *duplicates = existing
            if duplicates:
                logger.warning(
                    f"book {book.id}: dropping {len(duplicates)} duplicate overview chapter(s)"
                )
                dropped = {id(c) for c in duplicates}
                spine.chapters = [c for c in spine.chapters if id(c) not in dropped]
            # Re-seat it at the front and renumber, so a spine that came back
            # out of order still reads correctly.
            spine.chapters = [keep, *[c for c in spine.chapters if c is not keep]]
            for index, chapter in enumerate(spine.chapters):
                chapter.order = index
            return spine

        copy = overview_copy(book.language)
        overview = Chapter(
            title=copy["chapter_title"],
            learning_objectives=list(copy["objectives"]),
            content_type=ContentType.OVERVIEW,
            summary=copy["chapter_summary"],
            order=0,
        )
        # Mark for idempotency on subsequent runs.
        overview.__pydantic_extra__ = overview.__pydantic_extra__ or {}
        overview.__pydantic_extra__["auto_overview"] = True

        spine.chapters = [overview, *spine.chapters]
        for index, chapter in enumerate(spine.chapters):
            chapter.order = index
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

        copy = overview_copy(book.language)
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
        description = (book.proposal.description if book.proposal else "") or ""
        intro_md = f"# {book.title or copy['untitled_book']}\n\n{description}\n\n" + copy[
            "intro_body"
        ].format(
            concepts=len(spine.concept_graph.nodes),
            chapters=len(chapter_index),
        )
        intro_block = Block(
            type=BlockType.TEXT,
            status=BlockStatus.READY,
            title=copy["intro_title"],
            params={"role": "overview_intro"},
            payload={"content": intro_md, "format": "markdown"},
        )

        # 2) Concept graph block — render deterministically
        from .blocks.concept_graph import render_mermaid

        graph_block = Block(
            type=BlockType.CONCEPT_GRAPH,
            status=BlockStatus.READY,
            title=copy["concept_map_title"],
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
        index_md = copy["chapter_index_heading"] + "\n\n" + "\n".join(index_lines)
        index_block = Block(
            type=BlockType.TEXT,
            status=BlockStatus.READY,
            title=copy["chapter_index_title"],
            params={"role": "chapter_index"},
            payload={"content": index_md, "format": "markdown"},
        )

        # This page is rebuilt from scratch every time the spine changes, which
        # is the one place ``edited_by_user`` protection cannot reach — the
        # blocks are replaced wholesale rather than reset. Carry the reader's
        # own content across: a hand-edited deterministic block wins over its
        # freshly rendered replacement, and notes are appended.
        edited_by_role: dict[str, Block] = {}
        notes: list[Block] = []
        for existing in overview_page.blocks:
            if existing.type == BlockType.USER_NOTE:
                notes.append(existing)
            elif (existing.metadata or {}).get("edited_by_user"):
                role = str((existing.params or {}).get("role") or existing.type.value)
                edited_by_role[role] = existing

        def _keep(block: Block, role: str) -> Block:
            return edited_by_role.get(role, block)

        overview_page.blocks = [
            _keep(intro_block, "overview_intro"),
            _keep(graph_block, BlockType.CONCEPT_GRAPH.value),
            _keep(index_block, "chapter_index"),
            *notes,
        ]
        overview_page.status = PageStatus.READY
        overview_page.content_type = ContentType.OVERVIEW
        self.storage.save_page(overview_page)

        # Publish to the book's own stream. Guarding on ``stream is not None``
        # silently dropped this event once callers stopped passing a bus.
        await BookStream(stream or get_book_bus(book.id)).book_event(
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

        # Chapters the reader deleted must not survive on the concept map.
        dropped = _prune_concept_graph(spine)
        if dropped:
            self.storage.append_log(
                book_id,
                f"pruned {dropped} concept-graph node(s) for deleted chapters",
                op="confirm_spine",
            )

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
            elif (
                page.order != chapter.order
                or page.title != chapter.title
                or page.content_type != chapter.content_type
            ):
                # A re-confirm after editing the spine has to carry the edits
                # onto pages that already exist, or reordering and renaming
                # chapters changes nothing the reader can see: pages are sorted
                # by ``order`` (storage.list_pages) and titled from the page.
                page.order = chapter.order
                page.title = chapter.title
                page.content_type = chapter.content_type
                page.learning_objectives = list(chapter.learning_objectives)
                page.updated_at = time.time()
                self.storage.save_page(page)
            pages.append(page)
        pages.sort(key=lambda p: (p.order, p.created_at))

        # Build the Overview page eagerly (no LLM, no queue).
        await self._materialize_overview_page(spine, pages, book, stream=stream)

        book.page_count = len(pages)
        book.status = BookStatus.COMPILING
        metadata = {k: v for k, v in (book.metadata or {}).items() if k != "pause_reason"}
        metadata["lazy_compile"] = not auto_compile
        book.metadata = metadata
        self.storage.save_book(book)
        self.storage.append_log(
            book_id,
            f"spine confirmed ({len(pages)} page shells, auto_compile={auto_compile})",
            op="confirm_spine",
        )

        if auto_compile:
            await self._enqueue_pending_pages(book_id, pages)
        return pages

    async def _halt_compilation(self, book_id: str) -> None:
        """Stop this book's worker and drain its queue, leaving disk untouched."""
        runtime = self._runtimes.get(book_id)
        if runtime is None:
            return
        async with runtime.lock:
            if runtime.worker is not None and not runtime.worker.done():
                runtime.worker.cancel()
                runtime.worker = None
            for task in runtime.in_flight.values():
                if not task.done():
                    task.cancel()
            runtime.in_flight.clear()
            runtime.queued.clear()
            runtime.consecutive_page_failures = 0
            while not runtime.queue.empty():
                try:
                    runtime.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    async def resume_book(
        self,
        *,
        book_id: str,
        stream: StreamBus | None = None,
    ) -> list[Page]:
        """Re-queue every page that never finished, keeping what already exists.

        The non-destructive counterpart to :meth:`rebuild_book`. Three things
        need it and previously had only "delete everything and start over":

        - a process restart (per-book runtimes live in memory only),
        - a paused book once the user has topped up their quota,
        - a page stranded in ``PLANNING``/``GENERATING`` by a crash.

        Pages that are already ``READY`` are left exactly as they are, so
        resuming costs only the work that is genuinely missing.
        """
        book = self.storage.load_book(book_id)
        if book is None:
            raise ValueError(f"Book {book_id} not found")
        if self.storage.load_spine(book_id) is None:
            raise ValueError(f"No spine for book {book_id}")

        # A page left mid-flight by a crash would otherwise be skipped by the
        # queue's "already generating" checks forever.
        pages = self.storage.list_pages(book_id)
        for page in pages:
            if page.status in (PageStatus.PLANNING, PageStatus.GENERATING):
                page.status = PageStatus.PENDING
                page.updated_at = time.time()
                self.storage.save_page(page)

        pending = [p for p in pages if p.status in _UNFINISHED_PAGE_STATUSES]
        if not pending:
            await self._maybe_finalize_book(book_id)
            return pages

        book.status = BookStatus.COMPILING
        book.metadata = {k: v for k, v in (book.metadata or {}).items() if k != "pause_reason"}
        book.updated_at = time.time()
        self.storage.save_book(book)
        self.storage.append_log(
            book_id, f"resume requested ({len(pending)} unfinished pages)", op="resume"
        )

        await self._enqueue_pending_pages(book_id, pending)
        return self.storage.list_pages(book_id)

    async def maybe_resume_on_open(self, book_id: str) -> bool:
        """Restart stalled compilation when the reader opens a book.

        ``PathService`` resolves per current user, so a process-wide sweep at
        startup cannot even enumerate other users' books. Opening a book is the
        natural, correctly-scoped trigger instead: it runs as that user and
        only touches the book they actually care about.

        Deliberately does *not* resume a ``PAUSED`` book — that one stopped for
        a reason the user has to clear first, and silently retrying would burn
        the quota they just ran out of. Returns whether work was queued.
        """
        book = self.storage.load_book(book_id)
        if book is None or book.status != BookStatus.COMPILING:
            return False

        if (book.metadata or {}).get("lazy_compile"):
            # The reader asked for chapters to be built as they open them.
            # Resuming would queue the whole book and defeat that choice.
            return False

        runtime = self._runtimes.get(book_id)
        if runtime is not None:
            # Liveness, not queue depth. A queue with items in it and no worker
            # draining them is exactly the state that needs rescuing — reading
            # ``queued`` as proof of progress left such a book wedged at
            # COMPILING for the life of the process.
            if runtime.in_flight:
                return False
            if runtime.worker is not None and not runtime.worker.done():
                return False
        try:
            await self.resume_book(book_id=book_id)
        except ValueError:
            return False
        except Exception:  # noqa: BLE001
            logger.warning(f"auto-resume failed for {book_id}", exc_info=True)
            return False
        return True

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

        await self._halt_compilation(book_id)

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
        """Compile one page, coalescing concurrent requests for the same page.

        Three call sites can ask for the same page at once — the user opening
        it, the background worker reaching it, and a forced regenerate. Without
        coalescing they each run a full plan-and-generate pass, pay for it, and
        then race to persist, so the loser's output is silently discarded.

        A plain request *joins* the run already in flight. A forced one waits
        for that run to finish and then starts a clean pass, so a regenerate
        never interleaves with the generation it is meant to replace.
        """
        runtime = await self._get_or_create_runtime(book_id)

        while True:
            async with runtime.lock:
                running = runtime.in_flight.get(page_id)
                if running is None or running.done():
                    task = asyncio.create_task(
                        self._compile_page_now(
                            book_id=book_id,
                            page_id=page_id,
                            stream=stream,
                            force=force,
                        )
                    )
                    runtime.in_flight[page_id] = task
                    task.add_done_callback(partial(self._release_in_flight, runtime, page_id))
                    break
                if not force:
                    task = running
                    break
                joined = running
            # Outside the lock: let the in-flight pass finish, then loop round
            # and claim the slot for the forced rebuild. ``asyncio.wait`` never
            # re-raises, which is what we want — we only care that it ended.
            await asyncio.wait({joined})

        # Shielded: awaiting a task propagates the awaiter's cancellation *into*
        # that task, so one caller going away — a closed WebSocket, a client
        # that navigated on — would otherwise kill a run that other awaiters and
        # the background worker are relying on. Compilation persists its own
        # output, so it is always right to let it finish; the ways to genuinely
        # stop it (``_halt_compilation``, ``delete_book``) cancel the task
        # directly.
        return await asyncio.shield(task)

    @staticmethod
    def _release_in_flight(runtime: _BookRuntime, page_id: str, task: asyncio.Task[Page]) -> None:
        """Drop *page_id* from the in-flight table once *task* settles.

        Keyed on identity so a task that has already been replaced by a forced
        rebuild cannot evict its successor.
        """
        if runtime.in_flight.get(page_id) is task:
            runtime.in_flight.pop(page_id, None)

    async def _compile_page_now(
        self,
        *,
        book_id: str,
        page_id: str,
        stream: StreamBus | None = None,
        force: bool = False,
    ) -> Page:
        """Drive the compiler for one page. Always run via :meth:`compile_page`."""
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

        bus = stream or get_book_bus(book_id)
        bstream = BookStream(bus)

        try:
            async with bstream.stage(STAGE_COMPILATION):
                page = await self.compiler.compile_page(
                    book_id=book_id,
                    chapter=chapter,
                    page=page,
                    stream=bstream,
                    knowledge_bases=book.knowledge_bases,
                    language=book.language,
                    depth=book.depth.value,
                )
        except Exception as exc:
            self._mark_page_error(page, exc, prefix="Compilation failed")
            raise

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

    async def _enqueue_pending_pages(self, book_id: str, pages: list[Page]) -> None:
        while True:
            runtime = await self._get_or_create_runtime(book_id)
            async with runtime.lock:
                # An idle worker retires its runtime under the same two locks in
                # the same order. If it did so between our lookup and this
                # acquisition, we would be queueing into an orphan that nothing
                # drains — take the live runtime and try again.
                async with self._global_lock:
                    if self._runtimes.get(book_id) is not runtime:
                        continue

                runtime.consecutive_page_failures = 0
                for page in pages:
                    if page.status == PageStatus.READY:
                        continue
                    if page.id in runtime.queued:
                        continue
                    runtime.queued.add(page.id)
                    await runtime.queue.put(page.id)
                self._ensure_worker(book_id)
                return

    async def _get_or_create_runtime(self, book_id: str) -> _BookRuntime:
        async with self._global_lock:
            runtime = self._runtimes.get(book_id)
            if runtime is None:
                runtime = _BookRuntime()
                self._runtimes[book_id] = runtime
            return runtime

    def _mark_page_error(self, page: Page | None, exc: Exception, *, prefix: str) -> None:
        """Flip a page stranded in an in-flight state to ``ERROR``.

        The compiler persists ``page.status = PLANNING`` before the LLM
        planning call and ``GENERATING`` before running block generators;
        when either throws, nothing resets the status, so without this the
        page spins forever and is neither retried on resume nor
        force-regenerable in the UI. Saving is best-effort — this runs
        inside exception handlers (including the background worker loop,
        which must survive), so a failing save must not mask the original
        error or kill the worker.
        """
        if page is None or page.status not in (PageStatus.GENERATING, PageStatus.PLANNING):
            return
        page.status = PageStatus.ERROR
        page.error = f"{prefix}: {exc}"
        page.updated_at = time.time()
        try:
            self.storage.save_page(page)
        except Exception:
            logger.warning(f"Failed to persist ERROR status for page {page.id}", exc_info=True)

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

        # A task inherits the context it was created in, and this one is created
        # inside whichever request happened to enqueue first. That request may
        # have installed a scoped LLM config (a per-run model pick); without
        # clearing it, every chapter this worker compiles for the rest of its
        # life would silently use that one request's model. Background
        # compilation belongs to the book, not to the call that started it, so
        # it runs against the user's current configuration.
        from deeptutor.services.llm.config import set_scoped_llm_config

        set_scoped_llm_config(None)
        while True:
            try:
                page_id = await asyncio.wait_for(runtime.queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                async with runtime.lock:
                    if runtime.queue.empty() and not runtime.in_flight:
                        runtime.worker = None
                        async with self._global_lock:
                            if self._runtimes.get(book_id) is runtime:
                                self._runtimes.pop(book_id, None)
                        from deeptutor.runtime.memory_reclaim import schedule_memory_reclaim

                        schedule_memory_reclaim()
                        return
                continue

            # Re-bound every iteration: the except handler below reads `page`,
            # which must be neither unbound (loader raised on the first item —
            # the UnboundLocalError would kill this worker task) nor stale from
            # a previous iteration (the wrong page would be flipped to ERROR).
            page = None
            tripped = False
            try:
                page = self.storage.load_page(book_id, page_id)
                if page is None or page.status == PageStatus.READY:
                    continue
                # Go through the coalescing entry point rather than straight to
                # the compiler: if the reader just opened this very page, both
                # requests must land on one run instead of two.
                compiled = await self.compile_page(book_id=book_id, page_id=page_id)
                tripped = await self._record_page_outcome(runtime, book_id, compiled)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    f"Background compilation failed for {book_id}/{page_id}: {exc}",
                    exc_info=True,
                )
                # Reset page status so it can be retried on next resume.
                self._mark_page_error(page, exc, prefix="Background compile failed")
                try:
                    self.storage.append_log(
                        book_id,
                        f"background compile failed for page {page_id}: {exc}",
                        op="compile_error",
                    )
                except Exception:
                    logger.warning(
                        f"Failed to append compile-error log for {book_id}", exc_info=True
                    )
                tripped = await self._record_page_failure(runtime, book_id, str(exc))
            finally:
                runtime.queued.discard(page_id)

            if tripped:
                runtime.worker = None
                return

    # ── Compilation breaker ─────────────────────────────────────────────

    async def _record_page_outcome(self, runtime: _BookRuntime, book_id: str, page: Page) -> bool:
        """Feed a finished background page into the breaker.

        Returns ``True`` when the breaker tripped and the queue was drained.
        """
        reason = systemic_failure_reason(page) if page.status == PageStatus.ERROR else ""
        if not reason:
            # Any page that produced *something* proves the provider is alive.
            runtime.consecutive_page_failures = 0
            return False
        return await self._record_page_failure(runtime, book_id, reason)

    async def _record_page_failure(self, runtime: _BookRuntime, book_id: str, reason: str) -> bool:
        runtime.consecutive_page_failures += 1
        if runtime.consecutive_page_failures < CONSECUTIVE_PAGE_FAILURE_LIMIT:
            return False
        await self._pause_compilation(runtime, book_id, reason)
        return True

    async def _pause_compilation(self, runtime: _BookRuntime, book_id: str, reason: str) -> None:
        """Stop compiling this book and tell the reader why.

        Whatever is already on disk is kept: pausing leaves untouched pages
        ``PENDING`` so ``resume_book`` can pick them up verbatim once the user
        has fixed their quota or credentials.
        """
        async with runtime.lock:
            runtime.queued.clear()
            while not runtime.queue.empty():
                try:
                    runtime.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        book = self.storage.load_book(book_id)
        if book is not None:
            book.status = BookStatus.PAUSED
            book.metadata = {**(book.metadata or {}), "pause_reason": reason}
            book.updated_at = time.time()
            self.storage.save_book(book)
        self.storage.append_log(
            book_id,
            f"compilation paused after {runtime.consecutive_page_failures} "
            f"consecutive provider failures: {reason}",
            op="paused",
        )
        await BookStream(get_book_bus(book_id)).book_event(
            "compilation_paused",
            {"book_id": book_id, "reason": reason},
            stage=STAGE_COMPILATION,
        )

    async def _maybe_finalize_book(self, book_id: str) -> None:
        book = self.storage.load_book(book_id)
        if book is None:
            return
        pages = self.storage.list_pages(book_id)
        if not pages:
            return
        if not any(p.status in _UNFINISHED_PAGE_STATUSES for p in pages):
            # Every page has settled — READY, or PARTIAL with blocks that will
            # not come back. The book is as done as it is going to get.
            if book.status != BookStatus.READY:
                book.status = BookStatus.READY
                book.metadata = {
                    k: v for k, v in (book.metadata or {}).items() if k != "pause_reason"
                }
                self.storage.save_book(book)
                self.storage.append_log(book_id, "all pages ready → status=READY", op="finalize")
                # Without this the reader never learns the book finished:
                # the last page event fires while the book is still COMPILING.
                await BookStream(get_book_bus(book_id)).book_event(
                    "book_ready",
                    {"book_id": book_id, "page_count": len(pages)},
                    stage=STAGE_COMPILATION,
                )

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

        bus = stream or get_book_bus(book_id)
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
            # The content is machine-written again, so the reader's edit is
            # gone; leaving the flag set would make force-regenerate skip this
            # block for the rest of the book's life.
            if block.metadata:
                block.metadata.pop("edited_by_user", None)
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
                bus = stream or get_book_bus(book_id)
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

    async def update_block(
        self,
        *,
        book_id: str,
        page_id: str,
        block_id: str,
        title: str | None = None,
        body: str | None = None,
    ) -> Block | None:
        """Edit a block's prose in place, marking it as the reader's own.

        Deliberately limited to title and body. The point is to let someone fix
        a wrong sentence or write a margin note without gambling on a whole
        regeneration — not to turn the reader into a block-payload editor.

        The ``edited_by_user`` mark matters: :meth:`_reset_page_for_force_compile`
        honours it, so a later "regenerate this page" cannot quietly delete
        something the reader wrote.
        """
        page = self.storage.load_page(book_id, page_id)
        if page is None:
            return None
        block = page.block_by_id(block_id)
        if block is None or block.type not in _EDITABLE_BLOCK_TYPES:
            return None

        if title is not None:
            block.title = title
        if body is not None:
            block.payload = {
                **block.payload,
                _body_key(block): body,
                "format": "markdown",
            }
        block.status = BlockStatus.READY
        block.error = ""
        block.metadata = {**(block.metadata or {}), "edited_by_user": True}
        block.updated_at = time.time()

        self.compiler._finalize_page_status(page)
        self.storage.save_page(page)
        self.storage.append_log(
            book_id, f"edited {block.type.value} block {block_id}", op="edit_block"
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
        # The compiler needs a chapter to plan against, but this one is not part
        # of the book's structure: the spine editor hides it and a rebuild must
        # not resurrect it as a top-level chapter. Same marker pattern as
        # ``auto_overview``.
        chapter.__pydantic_extra__ = chapter.__pydantic_extra__ or {}
        chapter.__pydantic_extra__["deep_dive"] = True
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
        book.page_count = len(self.storage.list_pages(book_id))
        book.updated_at = time.time()
        self.storage.save_book(book)

        parent.links.append(PageLink(target_page_id=sub.id, relation="deepens", label=topic))
        if block_id:
            block = parent.block_by_id(block_id)
            if block is not None:
                # Keyed by topic: one card offers several, and each can be
                # expanded independently. The old scalar recorded only the
                # first and disabled the others.
                pages_by_topic = dict(block.metadata.get("deep_dive_pages") or {})
                pages_by_topic[topic] = sub.id
                block.metadata = {
                    **block.metadata,
                    "deep_dive_pages": pages_by_topic,
                    # Kept for books written before this change.
                    "deep_dive_page_id": block.metadata.get("deep_dive_page_id") or sub.id,
                }
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

    def _page_to_chapter(self, book_id: str) -> dict[str, str]:
        return {p.id: p.chapter_id for p in self.storage.list_pages(book_id) if p.chapter_id}

    async def record_quiz_attempt(
        self,
        *,
        book_id: str,
        page_id: str,
        block_id: str,
        question_id: str,
        user_answer: str,
        is_correct: bool | None,
    ) -> Progress:
        progress = progress_ops.record_attempt(
            self.load_progress(book_id),
            page_id=page_id,
            block_id=block_id,
            question_id=question_id,
            user_answer=user_answer,
            is_correct=is_correct,
            page_to_chapter=self._page_to_chapter(book_id),
        )
        self.storage.save_progress(progress)
        return progress

    # ── Reading position / bookmarks ────────────────────────────────────

    def mark_page_visited(self, *, book_id: str, page_id: str) -> Progress:
        """Remember where the reader is, so they can pick the book back up."""
        progress = self.load_progress(book_id)
        if progress_ops.mark_visited(progress, page_id):
            self.storage.save_progress(progress)
        return progress

    def toggle_page_bookmark(self, *, book_id: str, page_id: str) -> Progress:
        progress = self.load_progress(book_id)
        progress_ops.toggle_bookmark(progress, page_id)
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
        """Append a pitfall callout + worked explanation + an easier quiz.

        Idempotent per topic: asking twice returns the existing remediation
        rather than stacking a second copy onto the page. Three generated
        blocks per request is expensive enough that a double-click, a retry, or
        a second reader hitting the same wall must not pay for it twice.
        """
        page = self.storage.load_page(book_id, page_id)
        if page is None:
            return None

        clean_topic = (topic or "").strip()
        existing = next(
            (
                block
                for block in page.blocks
                if block.params.get("role") == "remediation"
                and str(block.params.get("topic") or "").strip() == clean_topic
            ),
            None,
        )
        if existing is not None:
            return existing

        await self.insert_block(
            book_id=book_id,
            page_id=page_id,
            block_type=BlockType.CALLOUT,
            params={"variant": "common_pitfall", "topic": clean_topic},
            stream=stream,
        )
        # The marker block the idempotency check above looks for.
        await self.insert_block(
            book_id=book_id,
            page_id=page_id,
            block_type=BlockType.TEXT,
            params={"role": "remediation", "topic": clean_topic},
            stream=stream,
        )
        return await self.insert_block(
            book_id=book_id,
            page_id=page_id,
            block_type=BlockType.QUIZ,
            params={"num_questions": 2, "difficulty": "easy", "topic": clean_topic},
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
