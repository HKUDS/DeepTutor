"""Post-generation chapter CRUD (#2571, slice 1).

The promise: add / rename / reorder / delete a chapter *after* the book is
generated, without rebuilding it and without losing already-compiled content.
Every test seeds a READY book whose pages hold real prose, then asserts the
structural edit lands while the untouched pages keep their blocks byte-for-byte.
"""

from __future__ import annotations

import pytest

from deeptutor.book.engine import BookEngine
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookStatus,
    Chapter,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ContentType,
    Page,
    PageStatus,
    Progress,
    Spine,
)
from deeptutor.book.storage import BookStorage
from deeptutor.services.path_service import PathService


def _storage(tmp_path) -> BookStorage:
    return BookStorage(path_service=PathService(workspace_root=tmp_path / "data"))


def _compiled_page(book_id: str, chapter_id: str, page_id: str, order: int, body: str) -> Page:
    return Page(
        id=page_id,
        book_id=book_id,
        chapter_id=chapter_id,
        title=f"Page {order}",
        order=order,
        status=PageStatus.READY,
        blocks=[
            Block(
                id=f"blk_{page_id}",
                type=BlockType.TEXT,
                status=BlockStatus.READY,
                payload={"body": body},
            )
        ],
    )


def _seed(storage: BookStorage, *, book_id: str = "bk", chapters: int = 3) -> BookEngine:
    """A READY book with *chapters* compiled chapters and a concept graph."""
    engine = BookEngine(storage=storage)
    spine_chapters: list[Chapter] = []
    nodes: list[ConceptNode] = []
    for i in range(chapters):
        chapter = Chapter(id=f"ch_{i}", title=f"Chapter {i}", order=i)
        page = _compiled_page(book_id, chapter.id, f"pg_{i}", i, f"compiled prose {i}")
        storage.save_page(page)
        chapter.page_ids = [page.id]
        spine_chapters.append(chapter)
        nodes.append(ConceptNode(id=f"n_{i}", label=f"Concept {i}", chapter_id=chapter.id))
    spine = Spine(
        book_id=book_id,
        chapters=spine_chapters,
        concept_graph=ConceptGraph(nodes=nodes, edges=[ConceptEdge(src="n_0", dst="n_1")]),
    )
    storage.save_spine(spine)
    storage.save_book(
        Book(
            id=book_id,
            title="Book",
            status=BookStatus.READY,
            revision=1,
            chapter_count=chapters,
            page_count=chapters,
        )
    )
    return engine


def _bodies(storage: BookStorage, book_id: str) -> dict[str, str]:
    return {p.id: p.blocks[0].payload["body"] for p in storage.list_pages(book_id) if p.blocks}


# ── Add ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_chapter_appends_an_empty_shell_and_keeps_compiled_pages(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)
    before = _bodies(storage, "bk")

    chapter = await engine.add_chapter(book_id="bk", title="New chapter")

    assert chapter is not None
    spine = storage.load_spine("bk")
    assert [c.id for c in spine.chapters] == ["ch_0", "ch_1", "ch_2", chapter.id]
    assert chapter.order == 3
    # The new chapter starts as a pending shell with no generated content.
    new_page = storage.load_page("bk", chapter.page_ids[0])
    assert new_page.status == PageStatus.PENDING
    assert new_page.blocks == []
    assert new_page.chapter_id == chapter.id
    # Every previously compiled page is untouched.
    for page_id, body in before.items():
        assert storage.load_page("bk", page_id).blocks[0].payload["body"] == body
    assert storage.load_book("bk").chapter_count == 4


@pytest.mark.asyncio
async def test_add_chapter_at_position_renumbers_spine_and_pages(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)

    chapter = await engine.add_chapter(book_id="bk", title="Inserted", position=1)

    spine = storage.load_spine("bk")
    assert [c.id for c in spine.chapters] == ["ch_0", chapter.id, "ch_1", "ch_2"]
    assert [c.order for c in spine.chapters] == [0, 1, 2, 3]
    # Pages are sorted by order, so the reader-visible sequence must follow.
    assert [p.chapter_id for p in storage.list_pages("bk")] == [
        "ch_0",
        chapter.id,
        "ch_1",
        "ch_2",
    ]


# ── Rename ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_chapter_carries_title_onto_its_page(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)

    chapter = await engine.rename_chapter(
        book_id="bk", chapter_id="ch_1", title="Renamed", learning_objectives=["obj"]
    )

    assert chapter.title == "Renamed"
    page = storage.load_page("bk", "pg_1")
    assert page.title == "Renamed"
    assert page.learning_objectives == ["obj"]
    # Renaming is not a regeneration: the compiled prose survives.
    assert page.blocks[0].payload["body"] == "compiled prose 1"
    assert page.status == PageStatus.READY


# ── Move ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_move_chapter_reorders_spine_and_pages_stably(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)
    before = _bodies(storage, "bk")

    ok = await engine.move_chapter(book_id="bk", chapter_id="ch_2", new_position=0)

    assert ok is True
    spine = storage.load_spine("bk")
    assert [c.id for c in spine.chapters] == ["ch_2", "ch_0", "ch_1"]
    assert [c.order for c in spine.chapters] == [0, 1, 2]
    pages = storage.list_pages("bk")
    assert [p.id for p in pages] == ["pg_2", "pg_0", "pg_1"]
    # Reordering moves pages, it never rewrites them.
    assert _bodies(storage, "bk") == before


@pytest.mark.asyncio
async def test_move_chapter_clamps_out_of_range_position(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)

    assert await engine.move_chapter(book_id="bk", chapter_id="ch_0", new_position=99) is True
    assert [c.id for c in storage.load_spine("bk").chapters] == ["ch_1", "ch_2", "ch_0"]


# ── Delete ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_chapter_removes_only_its_pages_and_preserves_the_rest(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)

    ok = await engine.delete_chapter(book_id="bk", chapter_id="ch_1")

    assert ok is True
    assert storage.load_page("bk", "pg_1") is None
    spine = storage.load_spine("bk")
    assert [c.id for c in spine.chapters] == ["ch_0", "ch_2"]
    assert [c.order for c in spine.chapters] == [0, 1]
    # The other compiled pages keep their content and follow the new order.
    assert storage.load_page("bk", "pg_0").blocks[0].payload["body"] == "compiled prose 0"
    assert storage.load_page("bk", "pg_2").blocks[0].payload["body"] == "compiled prose 2"
    assert [p.id for p in storage.list_pages("bk")] == ["pg_0", "pg_2"]
    # The deleted chapter's concept node and its dangling edge are pruned.
    assert [n.id for n in spine.concept_graph.nodes] == ["n_0", "n_2"]
    assert spine.concept_graph.edges == []
    book = storage.load_book("bk")
    assert book.chapter_count == 2
    assert book.page_count == 2


@pytest.mark.asyncio
async def test_delete_chapter_cleans_prerequisites_and_progress(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)
    spine = storage.load_spine("bk")
    spine.chapter_by_id("ch_2").prerequisites = ["ch_1"]
    storage.save_spine(spine)
    storage.save_progress(
        Progress(
            book_id="bk",
            current_page_id="pg_1",
            visited_page_ids=["pg_0", "pg_1"],
            bookmarked_page_ids=["pg_1"],
            weak_chapters=["ch_1"],
        )
    )

    assert await engine.delete_chapter(book_id="bk", chapter_id="ch_1") is True

    assert storage.load_spine("bk").chapter_by_id("ch_2").prerequisites == []
    progress = storage.load_progress("bk")
    assert progress.current_page_id == ""
    assert progress.visited_page_ids == ["pg_0"]
    assert progress.bookmarked_page_ids == []
    assert progress.weak_chapters == []


@pytest.mark.asyncio
async def test_delete_chapter_refuses_the_auto_overview(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)
    spine = storage.load_spine("bk")
    overview = Chapter(
        id="ch_overview", title="Overview", order=0, content_type=ContentType.OVERVIEW
    )
    spine.chapters = [overview, *spine.chapters]
    storage.save_spine(spine)

    assert await engine.delete_chapter(book_id="bk", chapter_id="ch_overview") is False
    assert storage.load_spine("bk").chapter_by_id("ch_overview") is not None


# ── Guards ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chapter_crud_without_a_spine_returns_none(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = BookEngine(storage=storage)
    storage.save_book(Book(id="bk", title="Draft", status=BookStatus.DRAFT))

    assert await engine.add_chapter(book_id="bk", title="x") is None
    assert await engine.rename_chapter(book_id="bk", chapter_id="ch_0", title="x") is None
    assert await engine.move_chapter(book_id="bk", chapter_id="ch_0", new_position=0) is False
    assert await engine.delete_chapter(book_id="bk", chapter_id="ch_0") is False


@pytest.mark.asyncio
async def test_chapter_crud_on_unknown_chapter_returns_none(tmp_path) -> None:
    storage = _storage(tmp_path)
    engine = _seed(storage)

    assert await engine.rename_chapter(book_id="bk", chapter_id="nope", title="x") is None
    assert await engine.move_chapter(book_id="bk", chapter_id="nope", new_position=0) is False
    assert await engine.delete_chapter(book_id="bk", chapter_id="nope") is False
