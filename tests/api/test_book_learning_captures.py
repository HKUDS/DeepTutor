from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book.models import (
    Book,
    ContentType,
    LearningCapture,
    Page,
    PageStatus,
)
import deeptutor.book.storage as storage_module
from deeptutor.services.path_service import PathService


class _StubBookEngine:
    def __init__(self, storage: storage_module.BookStorage) -> None:
        self.storage = storage

    def load_book(self, book_id: str) -> Book | None:
        return self.storage.load_book(book_id)

    def load_page(self, book_id: str, page_id: str) -> Page | None:
        return self.storage.load_page(book_id, page_id)

    def load_spine(self, book_id: str):
        return self.storage.load_spine(book_id)


def _new_client(tmp_path, monkeypatch) -> tuple[TestClient, storage_module.BookStorage]:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    storage_module._storages.clear()
    storage = storage_module.get_book_storage()

    monkeypatch.setattr(
        book_router,
        "get_book_engine",
        lambda: _StubBookEngine(storage),
    )

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api/v1/book")
    return TestClient(app), storage


def test_learning_capture_list_returns_empty_for_new_book(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_capture_api_list"

    storage.save_book(Book(id=book_id, title="Book"))
    response = client.get(f"/api/v1/book/books/{book_id}/learning-captures")

    assert response.status_code == 200
    assert response.json() == {"captures": []}


def test_learning_capture_create_deduplicates_by_content_hash(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_capture_api_create"

    storage.save_book(Book(id=book_id, title="Book"))
    storage.save_page(
        Page(
            id="pg_1",
            book_id=book_id,
            title="Page",
            learning_objectives=[],
            content_type=ContentType.THEORY,
            status=PageStatus.READY,
        )
    )

    payload = {
        "page_id": "pg_1",
        "block_id": "",
        "source_text": "  A   repeated   selection ",
    }

    first = client.post(f"/api/v1/book/books/{book_id}/learning-captures", json=payload)
    assert first.status_code == 200
    first_id = first.json()["capture"]["id"]

    second = client.post(
        f"/api/v1/book/books/{book_id}/learning-captures",
        json=payload,
    )
    assert second.status_code == 200
    assert second.json()["capture"]["id"] == first_id
    assert second.json()["capture"]["source_text"] == "A repeated selection"


def test_learning_capture_create_requires_source_text(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_capture_api_bad"

    storage.save_book(Book(id=book_id, title="Book"))
    storage.save_page(
        Page(
            id="pg_1",
            book_id=book_id,
            title="Page",
            learning_objectives=[],
            content_type=ContentType.THEORY,
            status=PageStatus.READY,
        )
    )

    response = client.post(
        f"/api/v1/book/books/{book_id}/learning-captures",
        json={
            "page_id": "pg_1",
            "source_text": "   ",
            "block_id": "",
        },
    )
    assert response.status_code == 400
    assert "source_text is required" in response.json()["detail"]


def test_learning_capture_patch_allows_legal_transition(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_capture_api_update"

    storage.save_book(Book(id=book_id, title="Book"))
    storage.save_page(
        Page(
            id="pg_1",
            book_id=book_id,
            title="Page",
            learning_objectives=[],
            content_type=ContentType.THEORY,
            status=PageStatus.READY,
        )
    )

    capture = LearningCapture(
        book_id=book_id,
        page_id="pg_1",
        source_text="source",
        content_hash="hash1",
    )
    storage.upsert_learning_capture(capture)

    response = client.patch(
        f"/api/v1/book/books/{book_id}/learning-captures/{capture.id}",
        json={"status": "approved"},
    )
    assert response.status_code == 200
    assert response.json()["capture"]["status"] == "approved"


def test_learning_capture_patch_blocks_invalid_transition(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_capture_api_bad_transition"

    storage.save_book(Book(id=book_id, title="Book"))
    storage.save_page(
        Page(
            id="pg_1",
            book_id=book_id,
            title="Page",
            learning_objectives=[],
            content_type=ContentType.THEORY,
            status=PageStatus.READY,
        )
    )
    capture = LearningCapture(
        book_id=book_id,
        page_id="pg_1",
        source_text="source",
        content_hash="hash1",
        status="captured",
    )
    storage.upsert_learning_capture(capture)

    response = client.patch(
        f"/api/v1/book/books/{book_id}/learning-captures/{capture.id}",
        json={"status": "imported"},
    )
    assert response.status_code == 400


def test_learning_capture_list_supports_status_filter(tmp_path, monkeypatch) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    book_id = "bk_capture_api_filter"

    storage.save_book(Book(id=book_id, title="Book"))
    storage.save_page(
        Page(
            id="pg_1",
            book_id=book_id,
            title="Page",
            learning_objectives=[],
            content_type=ContentType.THEORY,
            status=PageStatus.READY,
        )
    )
    storage.upsert_learning_capture(
        LearningCapture(
            book_id=book_id,
            page_id="pg_1",
            source_text="one",
            content_hash="h1",
            status="captured",
        )
    )
    storage.upsert_learning_capture(
        LearningCapture(
            book_id=book_id,
            page_id="pg_1",
            source_text="two",
            content_hash="h2",
            status="approved",
        )
    )

    response = client.get(f"/api/v1/book/books/{book_id}/learning-captures?status=approved")
    assert response.status_code == 200
    payload = response.json()["captures"]
    assert len(payload) == 1
    assert payload[0]["status"] == "approved"
