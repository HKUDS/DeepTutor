from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency
    FastAPI = None
    TestClient = None

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source.jobs import reset_web_sync_job_state_for_tests
from deeptutor.services.web_source.orchestrator import KBSyncResult

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


def _manager(tmp_path: Path) -> KnowledgeBaseManager:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir(parents=True, exist_ok=True)
    manager.register_knowledge_base("kb")
    manager.add_web_source("kb", "https://example.com/", language="en")
    return manager


def _client(router_module) -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/knowledge")
    return TestClient(app)


def _wait_for_terminal(client: TestClient, job_id: str) -> dict:
    for _ in range(30):
        response = client.get(f"/api/v1/knowledge/kb/web-sync-jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] not in {"queued", "running", "cancelling"}:
            return job
    raise AssertionError("web sync job did not finish")


def test_web_sync_returns_202_and_persists_job(monkeypatch, tmp_path: Path) -> None:
    import deeptutor.api.routers.knowledge as router_module

    manager = _manager(tmp_path)
    monkeypatch.setattr(router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(router_module, "kb_manager", manager)
    reset_web_sync_job_state_for_tests()

    async def fake_sync(**_kwargs):
        return KBSyncResult(ok=True)

    monkeypatch.setattr(
        "deeptutor.services.web_source.orchestrator.sync_kb_sources_safe", fake_sync
    )

    client = _client(router_module)
    response = client.post("/api/v1/knowledge/kb/sync-web")

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] in {"queued", "running"}
    job = _wait_for_terminal(client, accepted["job_id"])
    assert job["status"] == "succeeded"
    assert job["trigger"] == "manual"
    assert job["progress"] == 100
    persisted = (manager.base_dir / "kb" / ".web_sync_jobs.json").read_text(encoding="utf-8")
    assert accepted["job_id"] in persisted
    assert manager.get_web_sources("kb")[0]["latest_sync_job"] == accepted["job_id"]


def test_web_sync_job_can_be_cancelled(monkeypatch, tmp_path: Path) -> None:
    import deeptutor.api.routers.knowledge as router_module

    manager = _manager(tmp_path)
    monkeypatch.setattr(router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(router_module, "kb_manager", manager)
    reset_web_sync_job_state_for_tests()

    started = asyncio.Event()

    async def slow_sync(**_kwargs):
        started.set()
        await asyncio.sleep(2)
        return KBSyncResult(ok=True)

    monkeypatch.setattr(
        "deeptutor.services.web_source.orchestrator.sync_kb_sources_safe", slow_sync
    )
    client = _client(router_module)
    accepted = client.post("/api/v1/knowledge/kb/sync-web").json()

    cancel = client.post(f"/api/v1/knowledge/kb/web-sync-jobs/{accepted['job_id']}/cancel")

    assert cancel.status_code == 200
    assert cancel.json()["status"] in {"cancelling", "cancelled"}
    job = _wait_for_terminal(client, accepted["job_id"])
    assert job["status"] == "cancelled"
