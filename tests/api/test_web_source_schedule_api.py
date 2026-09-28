from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.knowledge.manager import KnowledgeBaseManager
import deeptutor.services.config as config_package
from deeptutor.services.config import loader as config_loader
from deeptutor.services.web_source import scheduler as scheduler_module
from deeptutor.services.web_source.repository import (
    SQLiteWebSourceSyncRepository,
)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI

    runtime_home = tmp_path / "runtime"
    settings_dir = runtime_home / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "main.yaml").write_text("system:\n  language: en\n", encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_HOME", str(runtime_home))
    monkeypatch.setattr(config_package, "PROJECT_ROOT", runtime_home)
    monkeypatch.setattr(config_loader, "PROJECT_ROOT", runtime_home)

    from deeptutor.api.routers import knowledge as knowledge_router

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir(parents=True)
    (manager.base_dir / "kb" / "metadata.json").write_text("{}", encoding="utf-8")
    manager.register_knowledge_base("kb")

    def writable(kb_name: str):
        assert kb_name == "kb"
        return manager, "kb", manager.base_dir

    monkeypatch.setattr(knowledge_router, "_writable_kb", writable)
    scheduler = scheduler_module.WebSourceSyncScheduler(
        repository=SQLiteWebSourceSyncRepository(tmp_path / "web-source-sync.sqlite")
    )
    monkeypatch.setattr(scheduler_module, "_scheduler", scheduler)
    app = FastAPI()
    app.include_router(knowledge_router.router, prefix="/api")
    return TestClient(app), manager


def test_schedule_defaults_update_and_delete_cleanup(client) -> None:
    test_client, manager = client
    source = manager.add_web_source("kb", "https://example.com/docs/")
    scheduler_module._scheduler.repo.ensure_source(("local-admin", "kb", source["id"]))

    created = test_client.post(
        "/api/knowledge-bases/kb/web-source",
        json={"url": "https://another.example.com/docs/"},
    )
    assert created.status_code == 200
    assert created.json()["auto_sync_enabled"] is True
    assert created.json()["sync_interval_hours"] == 24

    jobs = test_client.get("/api/knowledge-bases/kb/web-source-sync")
    assert jobs.status_code == 200
    assert {item["source_id"] for item in jobs.json()} == {
        source["id"],
        created.json()["id"],
    }

    updated = test_client.put(
        f"/api/knowledge-bases/kb/web-source/{source['id']}/schedule",
        json={"auto_sync_enabled": False, "sync_interval_hours": 6},
    )
    assert updated.status_code == 200
    assert updated.json()["auto_sync_enabled"] is False
    assert updated.json()["sync_interval_hours"] == 6
    scheduled_ids = {
        item["source_id"]
        for item in test_client.get("/api/knowledge-bases/kb/web-source-sync").json()
    }
    assert scheduled_ids == {created.json()["id"]}

    removed = test_client.delete(f"/api/knowledge-bases/kb/web-source/{source['id']}")
    assert removed.status_code == 200
    job_ids = {
        item["source_id"]
        for item in test_client.get("/api/knowledge-bases/kb/web-source-sync").json()
    }
    assert source["id"] not in job_ids


def test_schedule_rejects_out_of_range_interval(client) -> None:
    test_client, manager = client
    source = manager.add_web_source("kb", "https://example.com/docs/")
    response = test_client.put(
        f"/api/knowledge-bases/kb/web-source/{source['id']}/schedule",
        json={"auto_sync_enabled": True, "sync_interval_hours": 0},
    )
    assert response.status_code == 422
