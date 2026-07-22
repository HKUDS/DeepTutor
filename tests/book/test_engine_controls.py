from __future__ import annotations

from deeptutor.book.engine import BookEngine
from deeptutor.book.models import Block, BlockStatus, BlockType, Page, PageStatus


def test_force_compile_reset_preserves_user_notes() -> None:
    generated = Block(
        type=BlockType.CODE,
        status=BlockStatus.READY,
        payload={"code": "print(1)"},
        source_anchors=[],
        metadata={"generation_ms": 10, "transition_in": "bridge"},
    )
    note = Block(
        type=BlockType.USER_NOTE,
        status=BlockStatus.READY,
        payload={"body": "keep me"},
    )
    page = Page(status=PageStatus.READY, error="", blocks=[generated, note])

    BookEngine._reset_page_for_force_compile(page)

    assert page.status == PageStatus.PENDING
    assert generated.status == BlockStatus.PENDING
    assert generated.payload == {}
    assert generated.error == ""
    assert generated.metadata == {"transition_in": "bridge"}
    assert note.status == BlockStatus.READY
    assert note.payload == {"body": "keep me"}


class _RecordingStorage:
    """Minimal stand-in for BookStorage: records or refuses save_page calls."""

    def __init__(self, fail: bool = False):
        self.saved: list[Page] = []
        self.fail = fail

    def save_page(self, page: Page) -> None:
        if self.fail:
            raise OSError("disk full")
        self.saved.append(page)


def _engine_with_storage(storage: _RecordingStorage) -> BookEngine:
    engine = BookEngine.__new__(BookEngine)
    engine.storage = storage
    return engine


def test_mark_page_error_resets_generating_page() -> None:
    storage = _RecordingStorage()
    engine = _engine_with_storage(storage)
    page = Page(status=PageStatus.GENERATING)

    engine._mark_page_error(page, RuntimeError("llm timeout"), prefix="Compilation failed")

    assert page.status == PageStatus.ERROR
    assert "llm timeout" in page.error
    assert storage.saved == [page]


def test_mark_page_error_resets_planning_page() -> None:
    storage = _RecordingStorage()
    engine = _engine_with_storage(storage)
    page = Page(status=PageStatus.PLANNING)

    engine._mark_page_error(page, RuntimeError("planner crashed"), prefix="Compilation failed")

    assert page.status == PageStatus.ERROR
    assert "planner crashed" in page.error
    assert storage.saved == [page]


def test_mark_page_error_ignores_missing_or_settled_pages() -> None:
    storage = _RecordingStorage()
    engine = _engine_with_storage(storage)

    engine._mark_page_error(None, RuntimeError("boom"), prefix="x")
    ready = Page(status=PageStatus.READY)
    engine._mark_page_error(ready, RuntimeError("boom"), prefix="x")

    assert storage.saved == []
    assert ready.status == PageStatus.READY


def test_mark_page_error_survives_save_failure() -> None:
    engine = _engine_with_storage(_RecordingStorage(fail=True))
    page = Page(status=PageStatus.GENERATING)

    # Runs inside exception handlers (worker loop) — must never raise.
    engine._mark_page_error(page, RuntimeError("boom"), prefix="x")

    assert page.status == PageStatus.ERROR
