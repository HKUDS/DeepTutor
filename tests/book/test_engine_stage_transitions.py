"""Stage-transition guarantees for the BookEngine lifecycle.

DT-21 Top 15 gap #6 — ``deeptutor/book/engine.py`` drives the longest
multi-stage flow in the product (ideation → spine → shells → background
compilation). These tests pin the three properties whose failure costs a
whole long-running generation:

1. stages advance in order and each stage's artefact is persisted,
2. a single-stage failure retries without duplicating output,
3. cancelling mid-run leaves state that ``resume_book`` can recover from.

All external work — ideation, source exploration, spine synthesis, block
compilation — is faked. No LLM, no network, no real long tasks.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.book.agents.ideation_agent import IdeationAgent
from deeptutor.book.agents.source_explorer import SourceExplorer
from deeptutor.book.agents.spine_synthesizer import SpineSynthesizer
from deeptutor.book.engine import BookEngine
from deeptutor.book.event_hub import close_book_bus
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookInputs,
    BookProposal,
    BookStatus,
    Chapter,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ContentType,
    ExplorationReport,
    Page,
    PageStatus,
    Progress,
    Spine,
)
from deeptutor.runtime.stream_bus import StreamBus

# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


class FakeStorage:
    """In-memory BookStorage: deep-copies on save and load like real disk."""

    def __init__(self) -> None:
        self.books: dict[str, Book] = {}
        self.inputs: dict[str, BookInputs] = {}
        self.progress: dict[str, Progress] = {}
        self.pages: dict[str, dict[str, Page]] = {}
        self.spines: dict[str, Spine] = {}
        self.explorations: dict[str, ExplorationReport] = {}
        self.logs: list[tuple[str, str, str]] = []
        self.save_book_calls: list[str] = []

    # -- books -----------------------------------------------------------

    def save_book(self, book: Book) -> None:
        self.books[book.id] = book.model_copy(deep=True)
        self.save_book_calls.append(book.id)

    def load_book(self, book_id: str) -> Book | None:
        book = self.books.get(book_id)
        return book.model_copy(deep=True) if book else None

    def list_book_ids(self) -> list[str]:
        return list(self.books)

    def delete_book(self, book_id: str) -> bool:
        self.books.pop(book_id, None)
        self.pages.pop(book_id, None)
        self.spines.pop(book_id, None)
        return True

    # -- inputs / progress / logs -----------------------------------------

    def save_inputs(self, book_id: str, inputs: BookInputs) -> None:
        self.inputs[book_id] = inputs.model_copy(deep=True)

    def load_inputs(self, book_id: str) -> BookInputs | None:
        inputs = self.inputs.get(book_id)
        return inputs.model_copy(deep=True) if inputs else None

    def save_progress(self, progress: Progress) -> None:
        self.progress[progress.book_id] = progress.model_copy(deep=True)

    def load_progress(self, book_id: str) -> Progress | None:
        progress = self.progress.get(book_id)
        return progress.model_copy(deep=True) if progress else None

    def append_log(self, book_id: str, message: str, op: str = "info") -> None:
        self.logs.append((book_id, message, op))

    # -- spine / exploration ----------------------------------------------

    def save_spine(self, spine: Spine) -> None:
        self.spines[spine.book_id] = spine.model_copy(deep=True)

    def load_spine(self, book_id: str) -> Spine | None:
        spine = self.spines.get(book_id)
        return spine.model_copy(deep=True) if spine else None

    def save_exploration(self, book_id: str, report: ExplorationReport) -> None:
        self.explorations[book_id] = report.model_copy(deep=True)

    def load_exploration(self, book_id: str) -> ExplorationReport | None:
        report = self.explorations.get(book_id)
        return report.model_copy(deep=True) if report else None

    # -- pages --------------------------------------------------------------

    def save_page(self, page: Page) -> None:
        self.pages.setdefault(page.book_id, {})[page.id] = page.model_copy(deep=True)

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        page = self.pages.get(book_id, {}).get(page_id)
        return page.model_copy(deep=True) if page else None

    def list_pages(self, book_id: str) -> list[Page]:
        pages = self.pages.get(book_id, {}).values()
        return [p.model_copy(deep=True) for p in sorted(pages, key=lambda p: p.created_at)]

    def delete_page(self, book_id: str, page_id: str) -> None:
        self.pages.get(book_id, {}).pop(page_id, None)


class FakeCompiler:
    """Stands in for BookCompiler: records runs, scripts failures/blocks."""

    def __init__(self, storage: FakeStorage) -> None:
        self.storage = storage
        self.calls: list[str] = []  # page_id per compile attempt
        self.fail_on: set[str] = set()
        self.block_gate: asyncio.Event | None = None  # hold pages mid-flight
        self.started: asyncio.Event | None = None  # signals first gated page

    async def compile_page(
        self,
        *,
        book_id: str,
        chapter: Chapter,
        page: Page,
        stream: Any = None,
        knowledge_bases: list[str] | None = None,
        language: str = "en",
        depth: str = "standard",
    ) -> Page:
        self.calls.append(page.id)
        if page.id in self.fail_on:
            # Mimic the real compiler: persist an in-flight status, then die.
            page.status = PageStatus.GENERATING
            self.storage.save_page(page)
            raise RuntimeError("provider 500")
        if self.block_gate is not None:
            page.status = PageStatus.GENERATING
            self.storage.save_page(page)
            if self.started is not None:
                self.started.set()
            await self.block_gate.wait()
        page.status = PageStatus.READY
        page.blocks = [
            Block(
                type=BlockType.TEXT,
                status=BlockStatus.READY,
                payload={"body": f"content for {page.title}"},
            )
        ]
        self.storage.save_page(page)
        return page


def _proposal() -> BookProposal:
    return BookProposal(
        title="Fourier Mini",
        description="A tiny signals book",
        estimated_chapters=2,
    )


def _spine(book_id: str) -> Spine:
    chapters = [
        Chapter(id="ch_signals", title="Signals", order=0),
        Chapter(id="ch_basis", title="Basis", order=1),
    ]
    graph = ConceptGraph(
        nodes=[
            ConceptNode(id="signal", label="Signal", chapter_id="ch_signals"),
            ConceptNode(id="basis", label="Basis", chapter_id="ch_basis"),
        ],
        edges=[ConceptEdge(src="signal", dst="basis")],
    )
    return Spine(book_id=book_id, chapters=chapters, concept_graph=graph)


def _exploration(book_id: str) -> ExplorationReport:
    return ExplorationReport(
        book_id=book_id,
        queries=["signal", "basis"],
        coverage={"kb": 4},
        candidate_concepts=["signal", "basis"],
        summary="sources cover both chapters",
    )


def _book_event_kinds(bus: StreamBus) -> list[str]:
    return [event.content for event in bus._history if event.content]


@pytest.fixture
def wired_engine(monkeypatch: pytest.MonkeyPatch) -> tuple[BookEngine, FakeStorage, FakeCompiler]:
    """A BookEngine whose every external stage is faked and recorded."""
    storage = FakeStorage()
    compiler = FakeCompiler(storage)

    async def fake_ideation(self, ideation_context):  # noqa: ANN001
        return _proposal()

    async def fake_explore(self, *, book_id, proposal, inputs, stream=None):  # noqa: ANN001
        return _exploration(book_id)

    async def fake_synthesize(self, *, book_id, proposal, exploration, on_round=None):  # noqa: ANN001
        if on_round is not None:
            await on_round(
                "critique#1",
                {"chapters": [{"id": "ch_signals"}], "issues": [{"id": "i1"}], "verdict": "revise"},
            )
        return _spine(book_id)

    monkeypatch.setattr(IdeationAgent, "process", fake_ideation)
    monkeypatch.setattr(SourceExplorer, "explore", fake_explore)
    monkeypatch.setattr(SpineSynthesizer, "synthesize", fake_synthesize)

    engine = BookEngine(storage=storage)  # type: ignore[arg-type]
    engine.compiler = compiler  # type: ignore[assignment]
    return engine, storage, compiler


# ─────────────────────────────────────────────────────────────────────────────
# 1. Stages advance in order, persisting each artefact
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stages_advance_in_order_and_persist_each_artefact(
    wired_engine, stream_bus: StreamBus
) -> None:
    engine, storage, compiler = wired_engine

    # Stage 1 — ideation: DRAFT book + proposal + inputs + progress on disk.
    book, proposal = await engine.create_book(user_intent="fourier", stream=stream_bus)
    assert book.status == BookStatus.DRAFT
    assert book.proposal is not None and book.proposal.title == proposal.title
    assert storage.load_book(book.id) is not None
    assert storage.load_inputs(book.id) is not None
    assert storage.load_progress(book.id) is not None
    assert ("create" in op for _, _, op in storage.logs)

    # Stage 2 — spine: exploration saved, spine saved, status SPINE_READY.
    book, spine = await engine.confirm_proposal(book_id=book.id, stream=stream_bus)
    assert book.status == BookStatus.SPINE_READY
    assert spine.book_id == book.id
    assert [c.id for c in spine.chapters] == ["ch_signals", "ch_basis"]
    assert storage.load_spine(book.id) is not None
    assert storage.load_exploration(book.id) is not None
    assert book.chapter_count == 2

    # Stage 3 — shells: overview injected first and READY, content pages
    # PENDING, book COMPILING; lazy mode keeps the worker out of the picture.
    pages = await engine.confirm_spine(book_id=book.id, stream=stream_bus, auto_compile=False)
    assert _status_of(storage, book.id, "ch_signals") == PageStatus.PENDING
    assert _status_of(storage, book.id, "ch_basis") == PageStatus.PENDING
    overview = storage.pages[book.id][pages[0].id]
    assert overview.content_type == ContentType.OVERVIEW
    assert overview.status == PageStatus.READY
    assert overview.blocks, "the overview page must be built deterministically"
    persisted_book = storage.load_book(book.id)
    assert persisted_book.status == BookStatus.COMPILING
    assert persisted_book.metadata["lazy_compile"] is True
    assert persisted_book.page_count == 3
    assert compiler.calls == [], "confirm_spine must not run the LLM compiler"

    # Stage 4 — compilation: each remaining page READY, then the book
    # finalises only after the last one.
    for page in pages:
        if page.content_type == ContentType.OVERVIEW:
            continue
        compiled = await engine.compile_page(book_id=book.id, page_id=page.id)
        assert compiled.status == PageStatus.READY
    assert storage.load_book(book.id).status == BookStatus.READY

    # A READY page is never re-compiled: re-opening it costs nothing.
    before = list(compiler.calls)
    again = await engine.compile_page(
        book_id=book.id, page_id=storage.pages[book.id][pages[1].id].id
    )
    assert again.status == PageStatus.READY
    assert compiler.calls == before

    # The streamed timeline shows the stages in lifecycle order.
    kinds = _book_event_kinds(stream_bus)
    ordering = [
        k
        for k in ("proposal_ready", "exploration_ready", "spine_ready", "overview_ready")
        if k in kinds
    ]
    assert ordering == ["proposal_ready", "exploration_ready", "spine_ready", "overview_ready"]

    close_book_bus(book.id)


def _status_of(storage: FakeStorage, book_id: str, chapter_id: str) -> PageStatus:
    for page in storage.pages.get(book_id, {}).values():
        if page.chapter_id == chapter_id:
            return page.status
    raise AssertionError(f"no page for chapter {chapter_id}")


# ─────────────────────────────────────────────────────────────────────────────
# 2a. Stage-2 failure: exploration dies, spine still ships, retry is clean
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exploration_failure_degrades_and_retry_does_not_duplicate(
    wired_engine, monkeypatch: pytest.MonkeyPatch, stream_bus: StreamBus
) -> None:
    engine, storage, _compiler = wired_engine
    book, _proposal = await engine.create_book(user_intent="fourier", stream=stream_bus)

    calls = {"explore": 0, "synthesize": 0}

    async def failing_explore(self, *, book_id, proposal, inputs, stream=None):  # noqa: ANN001
        calls["explore"] += 1
        raise RuntimeError("knowledge base unreachable")

    async def counting_synthesize(self, *, book_id, proposal, exploration, on_round=None):  # noqa: ANN001
        calls["synthesize"] += 1
        return _spine(book_id)

    monkeypatch.setattr(SourceExplorer, "explore", failing_explore)

    # Attempt 1 — exploration fails, the spine is still built from the
    # proposal alone, and the failure is recorded on the manifest.
    book, spine = await engine.confirm_proposal(book_id=book.id, stream=stream_bus)
    assert book.status == BookStatus.SPINE_READY
    assert [c.id for c in spine.chapters] == ["ch_signals", "ch_basis"]
    assert storage.load_spine(book.id) is not None
    assert storage.load_exploration(book.id) is None
    assert storage.load_book(book.id).metadata["exploration_failed"] is True
    assert any(op == "exploration_failed" for _, _, op in storage.logs)

    # Attempt 2 — sources are back: the failure marker is cleared, exactly
    # one exploration is saved, and the spine is replaced (not accumulated).
    monkeypatch.setattr(SpineSynthesizer, "synthesize", counting_synthesize)
    monkeypatch.setattr(
        SourceExplorer,
        "explore",
        lambda self, **kw: _async_value(_exploration(kw["book_id"])),
    )
    book, spine = await engine.confirm_proposal(book_id=book.id, stream=stream_bus)
    assert book.status == BookStatus.SPINE_READY
    assert calls == {"explore": 1, "synthesize": 1}
    assert storage.load_exploration(book.id) is not None
    metadata = storage.load_book(book.id).metadata
    assert "exploration_failed" not in metadata
    assert "source_quality" in metadata
    stored = storage.load_spine(book.id)
    assert [c.id for c in stored.chapters] == ["ch_signals", "ch_basis"], (
        "a retry must leave one spine, not layers of spines"
    )

    close_book_bus(book.id)


def _async_value(value: Any):
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        return value

    return _wrapper()


# ─────────────────────────────────────────────────────────────────────────────
# 2b. Stage-4 failure: page flips ERROR, retry re-pays only that page
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compile_failure_marks_the_page_and_retry_pays_only_for_it(
    wired_engine, stream_bus: StreamBus
) -> None:
    engine, storage, compiler = wired_engine
    book, _proposal = await engine.create_book(user_intent="fourier", stream=stream_bus)
    await engine.confirm_proposal(book_id=book.id, stream=stream_bus)
    pages = await engine.confirm_spine(book_id=book.id, stream=stream_bus, auto_compile=False)
    content_pages = [p for p in pages if p.content_type != ContentType.OVERVIEW]
    first, second = content_pages

    compiler.fail_on = {first.id}
    with pytest.raises(RuntimeError):
        await engine.compile_page(book_id=book.id, page_id=first.id)

    failed = storage.load_page(book.id, first.id)
    assert failed.status == PageStatus.ERROR
    assert "provider 500" in failed.error
    assert storage.load_book(book.id).status == BookStatus.COMPILING, (
        "one failed page must not finalize or kill the book"
    )
    assert storage.load_page(book.id, second.id).status == PageStatus.PENDING

    # Retry: the failed page is re-compiled, the untouched one pays once.
    compiler.fail_on.clear()
    assert (await engine.compile_page(book_id=book.id, page_id=first.id)).status == PageStatus.READY
    assert compiler.calls.count(first.id) == 2
    assert compiler.calls.count(second.id) == 0
    assert (
        await engine.compile_page(book_id=book.id, page_id=second.id)
    ).status == PageStatus.READY
    assert compiler.calls == [first.id, first.id, second.id]
    assert storage.load_book(book.id).status == BookStatus.READY

    close_book_bus(book.id)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cancel mid-run, then recover: pause → resume keeps finished work
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_mid_compile_then_resume_finishes_without_repaying_ready_work(
    wired_engine, stream_bus: StreamBus
) -> None:
    engine, storage, compiler = wired_engine
    book, _proposal = await engine.create_book(user_intent="fourier", stream=stream_bus)
    await engine.confirm_proposal(book_id=book.id, stream=stream_bus)
    pages = await engine.confirm_spine(book_id=book.id, stream=stream_bus, auto_compile=False)
    content_pages = [p for p in pages if p.content_type != ContentType.OVERVIEW]
    done, owed = content_pages

    # The reader finished chapter 1 in the foreground.
    assert (await engine.compile_page(book_id=book.id, page_id=done.id)).status == PageStatus.READY

    # Chapter 2 is mid-flight in the background worker when the user cancels.
    compiler.block_gate = asyncio.Event()
    compiler.started = asyncio.Event()
    book.metadata = {**(book.metadata or {}), "lazy_compile": False}
    storage.save_book(book)
    await engine.resume_book(book_id=book.id)
    await asyncio.wait_for(compiler.started.wait(), timeout=5)

    result = await engine.pause_book(book_id=book.id, reason="switching provider")

    paused_book = storage.load_book(book.id)
    assert paused_book.status == BookStatus.PAUSED
    assert paused_book.metadata["pause_kind"] == "user"
    assert paused_book.metadata["pause_reason"] == "switching provider"
    owed_status = storage.load_page(book.id, owed.id).status
    assert owed_status == PageStatus.PENDING, "a cancelled in-flight page must return to PENDING"
    assert storage.load_page(book.id, done.id).status == PageStatus.READY
    assert [p.id for p in result] == [p.id for p in storage.list_pages(book.id)]

    # While paused, generation is refused and auto-resume stays out of it.
    from deeptutor.book.engine import BookPausedError

    with pytest.raises(BookPausedError):
        await engine.compile_page(book_id=book.id, page_id=owed.id)
    assert await engine.maybe_resume_on_open(book.id) is False

    # Resume: the queue picks up exactly the owed page; the READY page and
    # the deterministic overview are never re-compiled.
    calls_before = list(compiler.calls)
    compiler.block_gate.set()
    resumed = await engine.resume_book(book_id=book.id)
    assert storage.load_book(book.id).status == BookStatus.COMPILING

    async def _wait_book_ready() -> None:
        while storage.load_book(book.id).status != BookStatus.READY:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait_book_ready(), timeout=10)
    assert compiler.calls == [*calls_before, owed.id], "resume re-pays only the owed page"
    assert [p.id for p in resumed] == [p.id for p in storage.list_pages(book.id)]

    close_book_bus(book.id)
