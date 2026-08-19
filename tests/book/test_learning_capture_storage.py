from __future__ import annotations

from pathlib import Path

from deeptutor.book.models import LearningCapture, LearningCaptureStatus
import deeptutor.book.storage as storage_module
from deeptutor.services.path_service import PathService


def _build_storage(tmp_path: Path, monkeypatch) -> storage_module.BookStorage:
    service = PathService(workspace_root=tmp_path / "data")
    storage_module._storages.clear()
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    return storage_module.get_book_storage()


def test_learning_captures_load_save_sorting(tmp_path: Path, monkeypatch) -> None:
    storage = _build_storage(tmp_path, monkeypatch)
    book_id = "bk_capture_sort"

    first = LearningCapture(
        book_id=book_id,
        page_id="pg_1",
        source_text="first",
        content_hash="h1",
        updated_at=1,
    )
    second = LearningCapture(
        book_id=book_id,
        page_id="pg_1",
        source_text="second",
        content_hash="h2",
        updated_at=5,
    )
    third = LearningCapture(
        book_id=book_id,
        page_id="pg_2",
        source_text="third",
        content_hash="h3",
        updated_at=3,
    )

    storage.upsert_learning_capture(first)
    storage.upsert_learning_capture(second)
    storage.upsert_learning_capture(third)

    captures = storage.load_learning_captures(book_id)
    assert [capture.id for capture in captures] == [second.id, third.id, first.id]

    updated = first.model_copy()
    updated.updated_at = 10
    updated.user_note = "updated note"
    storage.upsert_learning_capture(updated)

    captures = storage.load_learning_captures(book_id)
    assert captures[0].id == first.id
    assert captures[0].user_note == "updated note"


def test_learning_captures_filter_by_status(tmp_path: Path, monkeypatch) -> None:
    storage = _build_storage(tmp_path, monkeypatch)
    book_id = "bk_capture_filter"
    storage.upsert_learning_capture(
        LearningCapture(
            book_id=book_id,
            page_id="pg_1",
            source_text="one",
            content_hash="h1",
            status=LearningCaptureStatus.CAPTURED,
        )
    )
    storage.upsert_learning_capture(
        LearningCapture(
            book_id=book_id,
            page_id="pg_1",
            source_text="two",
            content_hash="h2",
            status=LearningCaptureStatus.APPROVED,
        )
    )
    storage.upsert_learning_capture(
        LearningCapture(
            book_id=book_id,
            page_id="pg_1",
            source_text="three",
            content_hash="h3",
            status=LearningCaptureStatus.REJECTED,
        )
    )

    assert [
        capture.status
        for capture in storage.load_learning_captures(
            book_id,
            status=LearningCaptureStatus.APPROVED,
        )
    ] == [LearningCaptureStatus.APPROVED]

    assert {
        capture.status
        for capture in storage.load_learning_captures(
            book_id,
            status=LearningCaptureStatus.REJECTED,
        )
    } == {LearningCaptureStatus.REJECTED}


def test_learning_capture_load_by_id(tmp_path: Path, monkeypatch) -> None:
    storage = _build_storage(tmp_path, monkeypatch)
    book_id = "bk_capture_lookup"
    capture = LearningCapture(
        book_id=book_id,
        page_id="pg_1",
        source_text="lookup me",
        content_hash="h1",
    )
    storage.upsert_learning_capture(capture)

    loaded = storage.load_learning_capture(book_id, capture.id)
    assert loaded is not None
    assert loaded.id == capture.id
    assert loaded.source_text == "lookup me"
