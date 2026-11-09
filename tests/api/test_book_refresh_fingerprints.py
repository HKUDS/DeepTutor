from __future__ import annotations

import time

from fastapi import FastAPI
from starlette.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Book, Page, PageStatus
import deeptutor.book.storage as storage_module
from deeptutor.multi_user import paths
from deeptutor.services.path_service import PathService


class _StubBookEngine:
    """The refresh-fingerprints surface of BookEngine, on the real kb_health."""

    def __init__(self, storage: storage_module.BookStorage) -> None:
        self.storage = storage

    def load_book(self, book_id: str) -> Book | None:
        return self.storage.load_book(book_id)

    def check_refresh_kb_fingerprints(self, book_id: str, *, force: bool = False) -> bool:
        from deeptutor.book.kb_health import ensure_can_refresh_fingerprints

        book = ensure_can_refresh_fingerprints(book_id, storage=self.storage, force=force)
        return book is not None

    def refresh_kb_fingerprints(self, book_id: str, *, force: bool = False) -> dict | None:
        from deeptutor.book.kb_health import refresh_book_fingerprints

        book = refresh_book_fingerprints(book_id, storage=self.storage, force=force)
        if book is None:
            return None
        return {
            "book_id": book.id,
            "kb_fingerprints": book.kb_fingerprints,
            "stale_page_ids": book.stale_page_ids,
        }


def _new_client(tmp_path, monkeypatch) -> tuple[TestClient, storage_module.BookStorage]:
    service = PathService(workspace_root=tmp_path / "book-data")
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    storage_module._storages.clear()
    storage = storage_module.get_book_storage()
    monkeypatch.setattr(book_router, "get_book_engine", lambda: _StubBookEngine(storage))
    # _claim_content_mutation audit-logs admin edits; keep them off the repo.
    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "system")

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    return TestClient(app), storage


def _book_with_page_flagged_stale(storage: storage_module.BookStorage) -> None:
    storage.save_page(
        Page(
            id="pg_stale",
            book_id="bk_refresh",
            title="Stale",
            status=PageStatus.READY,
            updated_at=1000.0,
        )
    )
    book = Book(id="bk_refresh", title="Book")
    book.stale_page_ids = ["pg_stale"]
    book.stale_detected_at = time.time()
    storage.save_book(book)


def test_rejected_refresh_fingerprints_keeps_revision_for_force_retry(
    tmp_path, monkeypatch
) -> None:
    client, storage = _new_client(tmp_path, monkeypatch)
    _book_with_page_flagged_stale(storage)

    refused = client.post(
        "/api/books/bk_refresh/refresh-fingerprints?force=false&expected_revision=1"
    )
    assert refused.status_code == 409
    assert "recompiled" in refused.json()["detail"]

    # The rejection must be side-effect free: book.revision stays where the
    # client left it, so the force retry's expected_revision is still valid.
    after_refusal = storage.load_book("bk_refresh")
    assert after_refusal is not None
    assert after_refusal.revision == 1

    forced = client.post(
        "/api/books/bk_refresh/refresh-fingerprints?force=true&expected_revision=1"
    )
    assert forced.status_code == 200
    assert forced.json()["book_revision"] == 2
    assert forced.json()["stale_page_ids"] == []
    refreshed = storage.load_book("bk_refresh")
    assert refreshed is not None
    assert refreshed.revision == 2
    assert refreshed.stale_page_ids == []
