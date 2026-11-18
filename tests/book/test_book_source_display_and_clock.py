"""Regression tests for #2762.

Two independent reports were filed as one issue:

1. A book created from notes showed no knowledge sources at all — the proposal
   page fell back to "no knowledge bases selected, the book will rely on
   general knowledge" even though the notes had been captured.
2. The elapsed-time readout above the book restarted at zero every time the
   reader navigated away and came back.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from deeptutor.book.engine import BookEngine, source_summaries
from deeptutor.book.models import (
    Book,
    BookInputs,
    BookSourceSummary,
    BookStatus,
    NotebookRef,
    Page,
    PageStatus,
    Spine,
)

# ── 1. Source labels reach the reader ────────────────────────────────────────


def test_source_summaries_lists_notes_and_documents() -> None:
    inputs = BookInputs(
        user_intent="Learn attention",
        source_refs=[
            {
                "kind": "notebook",
                "label": "Chapter 3 — attention notes",
                "source_id": "nb-1",
                "available": True,
            },
            {
                "kind": "file",
                "label": "attention.pdf",
                "source_id": "doc-9",
                "available": False,
            },
        ],
    )

    summaries = source_summaries(inputs)

    assert [s.label for s in summaries] == [
        "Chapter 3 — attention notes",
        "attention.pdf",
    ]
    assert [s.kind for s in summaries] == ["notebook", "file"]
    # An unreadable source stays visible but is marked as not usable.
    assert summaries[1].available is False


def test_source_summaries_falls_back_to_legacy_notebook_refs() -> None:
    """Books created before unified ``source_refs`` still list their notes."""
    inputs = BookInputs(notebook_refs=[NotebookRef(notebook_id="nb-legacy", record_ids=["r1"])])

    summaries = source_summaries(inputs)

    assert [(s.kind, s.label) for s in summaries] == [("notebook", "nb-legacy")]


def test_source_summaries_dedupes_and_drops_blank_labels() -> None:
    inputs = BookInputs(
        source_refs=[
            {"kind": "notebook", "label": "Same", "source_id": "a"},
            {"kind": "notebook", "label": "Same", "source_id": "b"},
            {"kind": "notebook", "label": "   ", "source_id": "c"},
            {"kind": "file", "label": "Other", "source_id": "d"},
        ]
    )

    assert [s.label for s in source_summaries(inputs)] == ["Same", "Other"]


def test_book_payload_reports_saved_sources() -> None:
    """The book carries its sources, so the form never claims it has none."""
    book = Book(
        title="Attention",
        knowledge_bases=[],
        sources=[BookSourceSummary(kind="notebook", label="Chapter 3 notes")],
    )

    payload = book.model_dump(mode="json")

    assert payload["sources"] == [
        {"kind": "notebook", "label": "Chapter 3 notes", "source_id": "", "available": True}
    ]


# ── 2. A run keeps its clock across page navigation ─────────────────────────


class _InMemoryStorage:
    """Storage stand-in: the clock logic only needs load/save of book + spine."""

    def __init__(self, book: Book, spine: Spine | None, pages: list[Page]) -> None:
        self.book = book
        self.spine = spine
        self.pages = pages

    def load_book(self, book_id: str) -> Book | None:
        return self.book if self.book.id == book_id else None

    def save_book(self, book: Book) -> None:
        self.book = book

    def load_spine(self, book_id: str) -> Spine | None:
        return self.spine

    def list_pages(self, book_id: str) -> list[Page]:
        return list(self.pages)

    def save_page(self, page: Page) -> None:
        self.pages = [page if p.id == page.id else p for p in self.pages]

    def append_log(self, *args, **kwargs) -> None:
        return None


def _engine(book: Book) -> BookEngine:
    """A BookEngine wired to in-memory storage; no compiler, no worker."""
    engine = BookEngine.__new__(BookEngine)
    engine._global_lock = asyncio.Lock()
    engine._runtimes = {}
    engine._run_owners = set()
    engine.storage = _InMemoryStorage(
        book,
        Spine(book_id=book.id, chapters=[]),
        [Page(id="pg-1", book_id=book.id, title="Chapter 1", status=PageStatus.PENDING)],
    )

    async def _no_enqueue(book_id: str, pages: list[Page]) -> None:
        return None

    engine._enqueue_pending_pages = _no_enqueue
    return engine


def _compiling_book(started_at: float) -> Book:
    book = Book(title="Clock", status=BookStatus.COMPILING)
    book.metadata = {"compile_started_at": started_at}
    return book


@pytest.mark.asyncio
async def test_reopening_a_running_book_keeps_its_original_start_time() -> None:
    """Navigating away and back must not restart the elapsed-time readout.

    ``maybe_resume_on_open`` runs on every book open, and the worker retires an
    idle runtime after two seconds, so a queued-but-not-yet-started book looked
    abandoned on every visit and ``resume_book`` re-stamped the clock.

    Compared with an explicit absolute tolerance: ``pytest.approx`` defaults to
    a *relative* tolerance of 1e-6, which on an epoch timestamp is about half an
    hour — enough to wave through exactly the reset this test exists to catch.
    """
    started_at = time.time() - 600  # ten minutes into the run
    book = _compiling_book(started_at)
    engine = _engine(book)
    # This process is already driving the run.
    engine._run_owners.add(book.id)

    await engine.resume_book(book_id=book.id)

    stamped = engine.storage.book.metadata["compile_started_at"]
    assert stamped == pytest.approx(started_at, abs=1.0)
    assert time.time() - stamped > 500, "the run's clock was restarted"


@pytest.mark.asyncio
async def test_resuming_after_a_restart_starts_a_fresh_clock() -> None:
    """A stamp left by a dead process belongs to a run that no longer exists."""
    stale = time.time() - 86_400  # a full day old: nobody is still running it
    book = _compiling_book(stale)
    engine = _engine(book)
    # Nothing in this process has claimed the run.
    assert engine._run_owners == set()

    await engine.resume_book(book_id=book.id)

    stamped = engine.storage.book.metadata["compile_started_at"]
    assert stamped > stale
    assert stamped == pytest.approx(time.time(), abs=30.0)
