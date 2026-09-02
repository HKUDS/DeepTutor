from __future__ import annotations

import json
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
