"""The engine-injected Overview chapter must stay singular and non-destructive.

Two defects motivated these: the idempotency guard keyed on ``chapters[0]``, so
any caller handing the spine back with the overview elsewhere (the spine editor
re-appends hidden chapters) grew a second overview on every re-confirm; and the
overview page is rebuilt wholesale, which is the one path the ``edited_by_user``
protection cannot reach.
"""

from __future__ import annotations

import pytest

from deeptutor.book.engine import BookEngine, _is_auto_overview
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Chapter,
    ConceptGraph,
    ContentType,
    Page,
    PageStatus,
    Spine,
)


def _engine() -> BookEngine:
    return BookEngine.__new__(BookEngine)


def _spine(*chapters: Chapter) -> Spine:
    return Spine(book_id="bk", chapters=list(chapters), concept_graph=ConceptGraph())


def _authored(title: str, order: int) -> Chapter:
    return Chapter(title=title, content_type=ContentType.THEORY, order=order)


@pytest.mark.asyncio
async def test_overview_is_injected_once() -> None:
    engine, book = _engine(), Book(id="bk", language="en")
    spine = await engine._ensure_overview_chapter(
        _spine(_authored("One", 0), _authored("Two", 1)), book, stream=None
    )

    assert sum(1 for c in spine.chapters if _is_auto_overview(c)) == 1
    assert _is_auto_overview(spine.chapters[0])
    assert [c.order for c in spine.chapters] == [0, 1, 2]


@pytest.mark.asyncio
async def test_re_confirming_does_not_add_a_second_overview() -> None:
    engine, book = _engine(), Book(id="bk", language="en")
    spine = await engine._ensure_overview_chapter(_spine(_authored("One", 0)), book, stream=None)
    again = await engine._ensure_overview_chapter(spine, book, stream=None)

    assert sum(1 for c in again.chapters if _is_auto_overview(c)) == 1


@pytest.mark.asyncio
async def test_an_overview_that_came_back_out_of_position_is_reseated() -> None:
    """The spine editor hides the overview and re-attaches it around the edits."""
    engine, book = _engine(), Book(id="bk", language="en")
    overview = Chapter(title="How to read this book", content_type=ContentType.OVERVIEW)
    # Overview last — the shape that used to defeat the guard entirely.
    spine = _spine(_authored("One", 0), _authored("Two", 1), overview)

    result = await engine._ensure_overview_chapter(spine, book, stream=None)

    assert sum(1 for c in result.chapters if _is_auto_overview(c)) == 1
    assert result.chapters[0] is overview, "the overview must lead the book"
    assert [c.order for c in result.chapters] == [0, 1, 2], "orders must be contiguous"


@pytest.mark.asyncio
async def test_duplicate_overviews_from_older_data_are_collapsed() -> None:
    engine, book = _engine(), Book(id="bk", language="en")
    first = Chapter(title="How to read this book", content_type=ContentType.OVERVIEW)
    stale = Chapter(title="How to read this book", content_type=ContentType.OVERVIEW)
    spine = _spine(first, _authored("One", 1), stale)

    result = await engine._ensure_overview_chapter(spine, book, stream=None)

    assert sum(1 for c in result.chapters if _is_auto_overview(c)) == 1
    assert len(result.chapters) == 2


# ── Rebuild preserves reader-authored content ───────────────────────────


class _Storage:
    def __init__(self) -> None:
        self.saved: list[Page] = []

    def save_page(self, page: Page) -> None:
        self.saved.append(page)


@pytest.mark.asyncio
async def test_rebuilding_the_overview_keeps_notes_and_hand_edits() -> None:
    engine = _engine()
    engine.storage = _Storage()
    book = Book(id="bk", language="en", title="B")

    note = Block(type=BlockType.USER_NOTE, status=BlockStatus.READY, payload={"body": "my note"})
    edited_intro = Block(
        type=BlockType.TEXT,
        status=BlockStatus.READY,
        params={"role": "overview_intro"},
        payload={"content": "my own introduction"},
        metadata={"edited_by_user": True},
    )
    overview_chapter = Chapter(title="How to read this book", content_type=ContentType.OVERVIEW)
    page = Page(
        id="pg_0",
        book_id="bk",
        chapter_id=overview_chapter.id,
        content_type=ContentType.OVERVIEW,
        status=PageStatus.PENDING,
        blocks=[edited_intro, note],
    )
    spine = _spine(overview_chapter, _authored("One", 1))

    await engine._materialize_overview_page(spine, [page], book, stream=None)

    bodies = [b.payload.get("content", "") for b in page.blocks]
    assert "my own introduction" in bodies, "a hand-edited intro must survive"
    assert note in page.blocks, "the reader's note must survive"
    # The un-edited deterministic blocks are still refreshed from the spine.
    assert any(b.type == BlockType.CONCEPT_GRAPH for b in page.blocks)
    assert page.status == PageStatus.READY
