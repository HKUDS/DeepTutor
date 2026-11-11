"""Chapter CRUD over the REST surface (#2571, slice 1).

Exercises the reporter's proposed paths through the real router + engine on a
personal (single-user) book: the optimistic-concurrency contract, the pending
shell on add, and surgical delete that leaves the other compiled pages alone.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book.engine import BookEngine
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookStatus,
    Chapter,
    Page,
    PageStatus,
    Spine,
)
import deeptutor.book.storage as storage_module
from deeptutor.services.path_service import PathService


def _client(tmp_path, monkeypatch) -> tuple[TestClient, storage_module.BookStorage]:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    storage_module._storages.clear()
    storage = storage_module.get_book_storage()
    engine = BookEngine(storage=storage)
    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
    # The single-user fallback claims a revision as the local admin; keep the
    # audit subsystem out of the test entirely.
    monkeypatch.setattr(book_router, "log_admin_action", lambda *a, **k: None)
    monkeypatch.setattr(book_router, "log_usage", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    return TestClient(app), storage


def _seed(storage: storage_module.BookStorage, book_id: str = "bk") -> None:
    chapters = []
    for i in range(2):
        chapter = Chapter(id=f"ch_{i}", title=f"Chapter {i}", order=i)
        storage.save_page(
            Page(
                id=f"pg_{i}",
                book_id=book_id,
                chapter_id=chapter.id,
                title=f"Page {i}",
                order=i,
                status=PageStatus.READY,
                blocks=[
                    Block(
                        id=f"blk_{i}",
                        type=BlockType.TEXT,
                        status=BlockStatus.READY,
                        payload={"body": f"prose {i}"},
                    )
                ],
            )
        )
        chapter.page_ids = [f"pg_{i}"]
        chapters.append(chapter)
    storage.save_spine(Spine(book_id=book_id, chapters=chapters))
    storage.save_book(
        Book(
            id=book_id,
            title="Book",
            status=BookStatus.READY,
            revision=1,
            chapter_count=2,
            page_count=2,
        )
    )


def test_add_chapter_returns_a_pending_shell_and_advances_revision(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)

    response = client.post("/api/books/bk/chapters", json={"title": "Added"})

    assert response.status_code == 200
    body = response.json()
    assert body["book_revision"] == 2
    chapter = body["chapter"]
    assert chapter["title"] == "Added"
    page = storage.load_page("bk", chapter["page_ids"][0])
    assert page.status == PageStatus.PENDING
    assert storage.load_book("bk").revision == 2


def test_rename_chapter_requires_a_matching_revision(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)

    ok = client.patch(
        "/api/books/bk/chapters/ch_0",
        json={"title": "Renamed", "expected_revision": 1},
    )
    assert ok.status_code == 200
    assert ok.json()["book_revision"] == 2
    assert storage.load_page("bk", "pg_0").title == "Renamed"

    stale = client.patch(
        "/api/books/bk/chapters/ch_0",
        json={"title": "Stale", "expected_revision": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "book_revision_conflict"
    assert stale.json()["detail"]["current_revision"] == 2
    # The stale edit must not land.
    assert storage.load_page("bk", "pg_0").title == "Renamed"


def test_move_chapter_reorders_pages(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)

    response = client.post(
        "/api/books/bk/chapters/ch_1/move",
        json={"new_position": 0, "expected_revision": 1},
    )

    assert response.status_code == 200
    assert [p.id for p in storage.list_pages("bk")] == ["pg_1", "pg_0"]


def test_delete_chapter_preserves_the_other_compiled_pages(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)

    response = client.delete("/api/books/bk/chapters/ch_0?expected_revision=1")

    assert response.status_code == 200
    assert response.json()["book_revision"] == 2
    assert storage.load_page("bk", "pg_0") is None
    survivor = storage.load_page("bk", "pg_1")
    assert survivor.status == PageStatus.READY
    assert survivor.blocks[0].payload["body"] == "prose 1"


def test_chapter_routes_404_for_unknown_book_and_chapter(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)

    assert client.post("/api/books/missing/chapters", json={"title": "x"}).status_code == 404
    assert client.patch("/api/books/bk/chapters/nope", json={"title": "x"}).status_code == 404
    assert client.delete("/api/books/bk/chapters/nope").status_code == 404


def test_add_chapter_rejects_an_empty_title(tmp_path, monkeypatch) -> None:
    client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)

    assert client.post("/api/books/bk/chapters", json={"title": "  "}).status_code == 400
