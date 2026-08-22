from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source.sync_service import WebSourceSyncService


@pytest.mark.asyncio
async def test_scheduler_submits_durable_job(monkeypatch, tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir(parents=True, exist_ok=True)
    manager.register_knowledge_base("kb")
    manager.add_web_source("kb", "https://example.com/docs/", language="en")
    submitted: list[dict] = []

    def fake_submit(**kwargs):
        submitted.append(kwargs)
        return {
            "job_id": "scheduled-job",
            "kb_name": kwargs["kb_name"],
            "trigger": kwargs["trigger"],
            "status": "queued",
        }

    monkeypatch.setattr(
        "deeptutor.knowledge.manager.KnowledgeBaseManager",
        lambda base_dir: manager,
    )
    monkeypatch.setattr(
        "deeptutor.services.web_source.sync_service.submit_web_sync",
        fake_submit,
    )

    service = WebSourceSyncService(base_dir=str(manager.base_dir))
    await service._sync_one_cycle()

    assert len(submitted) == 1
    assert submitted[0]["kb_name"] == "kb"
    assert submitted[0]["trigger"] == "scheduled"
    assert submitted[0]["kb_base_dir"] == str(manager.base_dir)


@pytest.mark.asyncio
async def test_scheduler_honors_per_source_interval(monkeypatch, tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir(parents=True, exist_ok=True)
    manager.register_knowledge_base("kb")
    source = manager.add_web_source(
        "kb",
        "https://example.com/docs/",
        language="en",
        sync_interval_hours=12,
    )
    manager.update_web_source_state(
        "kb",
        source["id"],
        last_synced_at="2999-01-01T00:00:00+00:00",
    )
    submitted: list[dict] = []

    monkeypatch.setattr(
        "deeptutor.knowledge.manager.KnowledgeBaseManager",
        lambda base_dir: manager,
    )
    monkeypatch.setattr(
        "deeptutor.services.web_source.sync_service.submit_web_sync",
        lambda **kwargs: submitted.append(kwargs),
    )

    service = WebSourceSyncService(base_dir=str(manager.base_dir))
    await service._sync_one_cycle()

    assert submitted == []
