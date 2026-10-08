from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth
from deeptutor.api.routers import knowledge as knowledge_router


def _client(monkeypatch, base_dir: Path) -> TestClient:
    async def allow(_websocket):
        return None

    monkeypatch.setattr(auth, "ws_require_auth", allow)
    monkeypatch.setattr(knowledge_router, "_current_kb_base_dir", lambda: base_dir)
    app = FastAPI()
    app.include_router(knowledge_router.ws_router, prefix="/ws")
    return TestClient(app)


def _write_progress(base_dir: Path, payload: dict) -> None:
    kb_dir = base_dir / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / ".progress.json").write_text(json.dumps(payload), encoding="utf-8")


def test_completed_progress_is_replayed_for_expected_task(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "completed-task",
            "stage": "completed",
            "message": "done",
            "progress_percent": 100,
            "timestamp": "2026-09-02T00:00:00",
        },
    )

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress?task_id=completed-task"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "completed"
    assert frame["data"]["task_id"] == "completed-task"


def test_orphaned_live_progress_becomes_retryable_error(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "orphaned-after-restart",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": "2026-09-02T00:00:00",
        },
    )

    with _client(monkeypatch, base_dir).websocket_connect(
        "/ws/knowledge-bases/kb/progress?task_id=orphaned-after-restart"
    ) as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "error"
    assert frame["data"]["error_code"] == "knowledge_task_interrupted"
    assert frame["data"]["retryable"] is True

    persisted = json.loads((base_dir / "kb" / ".progress.json").read_text(encoding="utf-8"))
    assert persisted["stage"] == "error"
    assert persisted["task_id"] == "orphaned-after-restart"


def test_malformed_progress_timestamp_is_logged_and_degrades(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """An unparseable freshness timestamp falls back safely AND stays visible."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "stuck-task",
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": "not-an-iso-timestamp",
        },
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.api.routers.knowledge"):
        with _client(monkeypatch, base_dir).websocket_connect(
            "/ws/knowledge-bases/kb/progress"
        ) as websocket:
            frame = websocket.receive_json()

    # Degradation: the snapshot is still replayed on the no-task fast path
    # instead of blocking the endpoint.
    assert frame["type"] == "progress"
    assert frame["data"]["stage"] == "processing_documents"
    # Visibility: the parse failure must reach the logs.
    assert any("not-an-iso-timestamp" in record.getMessage() for record in caplog.records), (
        f"expected a log mentioning the malformed timestamp, got: {caplog.records}"
    )


def test_malformed_timestamp_with_task_id_warns_once(monkeypatch, tmp_path: Path, caplog) -> None:
    """A corrupt snapshot timestamp is reported once even when both freshness
    checks (active-task detection and replay decision) consult it."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            # Snapshot predates task ids: the freshness checks still apply,
            # but the expected task id cannot short-circuit them.
            "stage": "processing_documents",
            "message": "working",
            "progress_percent": 40,
            "timestamp": "not-an-iso-timestamp",
        },
    )

    class _ReadyKBManager:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_info(self, _name: str) -> dict:
            return {"statistics": {"rag_initialized": True}}

    class _LiveTaskManager:
        @staticmethod
        def get_instance() -> "_LiveTaskManager":
            return _LiveTaskManager()

        def get_task_metadata(self, _task_id: str) -> dict:
            return {"status": "processing"}

    class _TasklessSocket:
        query_params: dict[str, str] = {"task_id": "live-task"}

        async def accept(self) -> None:
            return None

        async def send_json(self, payload: dict) -> None:
            return None

        async def receive_text(self) -> str:
            raise RuntimeError("client went away")

        async def close(self) -> None:
            return None

    async def allow(_websocket):
        return None

    async def _noop(_key, _websocket):
        return None

    from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster

    broadcaster = ProgressBroadcaster.get_instance()
    monkeypatch.setattr(auth, "ws_require_auth", allow)
    monkeypatch.setattr(knowledge_router, "_current_kb_base_dir", lambda: base_dir)
    monkeypatch.setattr(knowledge_router, "KnowledgeBaseManager", _ReadyKBManager)
    monkeypatch.setattr(knowledge_router, "TaskIDManager", _LiveTaskManager)
    monkeypatch.setattr(broadcaster, "connect", _noop)
    monkeypatch.setattr(broadcaster, "disconnect", _noop)

    with caplog.at_level(logging.WARNING, logger="deeptutor.api.routers.knowledge"):
        asyncio.run(knowledge_router.websocket_progress(_TasklessSocket(), "kb"))

    warnings = [
        record.getMessage()
        for record in caplog.records
        if "not-an-iso-timestamp" in record.getMessage()
    ]
    assert len(warnings) == 1, (
        f"expected exactly one warning for the corrupt timestamp, got: {warnings}"
    )


def test_cleanup_and_error_delivery_failures_are_logged_not_silent(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """Error-frame send, close, and user-context reset failures become log lines."""
    from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster
    from deeptutor.multi_user import context as multi_user_context

    class _BrokenPipeWebSocket:
        query_params: dict[str, str] = {}

        async def accept(self) -> None:
            return None

        async def send_json(self, payload: dict) -> None:
            raise RuntimeError("send pipe broken")

        async def close(self) -> None:
            raise RuntimeError("socket already closed")

    class _ExplodingTracker:
        def __init__(self, kb_name: str, base_dir: Path):
            pass

        def get_progress(self) -> dict:
            raise ValueError("progress snapshot read failed")

    async def allow(_websocket):
        return "opaque-token"

    async def _noop(_key, _websocket):
        return None

    broadcaster = ProgressBroadcaster.get_instance()
    monkeypatch.setattr(auth, "ws_require_auth", allow)
    monkeypatch.setattr(knowledge_router, "_current_kb_base_dir", lambda: tmp_path)
    monkeypatch.setattr(knowledge_router, "ProgressTracker", _ExplodingTracker)
    monkeypatch.setattr(broadcaster, "connect", _noop)
    monkeypatch.setattr(broadcaster, "disconnect", _noop)

    def _reset_boom(_token):
        raise RuntimeError("context reset failed")

    monkeypatch.setattr(multi_user_context, "reset_current_user", _reset_boom)

    with caplog.at_level(logging.DEBUG, logger="deeptutor.api.routers.knowledge"):
        asyncio.run(knowledge_router.websocket_progress(_BrokenPipeWebSocket(), "kb"))

    messages = [record.getMessage() for record in caplog.records]
    # The original failure keeps its existing debug trace.
    assert any("progress snapshot read failed" in message for message in messages)
    # A failed error-frame delivery (usually a gone client) is now traced too.
    assert any("send pipe broken" in message for message in messages), messages
    # A failed close no longer disappears.
    assert any("socket already closed" in message for message in messages), messages
    # A failed user-context reset is a real fault: it must warn, not vanish.
    warnings = [
        record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING
    ]
    assert any("context reset failed" in message for message in warnings), messages


def test_client_disconnect_is_not_reported_as_error(monkeypatch, tmp_path: Path, caplog) -> None:
    """Teardown after a normal exchange stays quiet at warning level and above."""
    base_dir = tmp_path / "knowledge_bases"
    _write_progress(
        base_dir,
        {
            "task_id": "completed-task",
            "stage": "completed",
            "message": "done",
            "progress_percent": 100,
            "timestamp": "2026-09-02T00:00:00",
        },
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.api.routers.knowledge"):
        with _client(monkeypatch, base_dir).websocket_connect(
            "/ws/knowledge-bases/kb/progress?task_id=completed-task"
        ) as websocket:
            frame = websocket.receive_json()

    assert frame["data"]["stage"] == "completed"
    noisy = [record.getMessage() for record in caplog.records]
    assert not noisy, f"disconnect path produced warning-level logs: {noisy}"
