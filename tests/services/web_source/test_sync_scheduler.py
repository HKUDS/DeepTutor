from __future__ import annotations

import asyncio
from pathlib import Path
import time
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.web_source.repository import (
    SQLiteWebSourceSyncRepository,
    WebSourceSyncJob,
)
from deeptutor.services.web_source.scheduler import WebSourceSyncScheduler
from deeptutor.services.web_source.sync import WebSyncResult


def test_repository_creates_reconciles_and_recovers(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = "local-admin", "kb", "abc"
    repository.reconcile_sources({key})
    assert repository.list_jobs("local-admin", "kb")[0].state == "pending"

    job = repository.get(key)
    assert job is not None
    claimed = repository.claim(job, runner_id="runner-a", lease_until_ms=10_000)
    assert claimed is not None and claimed.state == "running"

    repository.recover_interrupted("runner-b")
    recovered = repository.get(key)
    assert recovered is not None
    assert recovered.state == "interrupted"
    assert recovered.runner_id == ""

    repository.reconcile_sources(set())
    assert repository.get(key) is None


def test_repository_recover_preserves_active_lease(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = "local-admin", "kb", "abc"
    repository.reconcile_sources({key})
    job = repository.get(key)
    assert job is not None

    claimed = repository.claim(
        job,
        runner_id="runner-a",
        lease_until_ms=int(time.time() * 1000) + 3_600_000,
    )
    assert claimed is not None
    repository.recover_interrupted("runner-b")

    active = repository.get(key)
    assert active is not None
    assert active.state == "running"


def test_repository_cancel_and_retry(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = "local-admin", "kb", "abc"
    repository.reconcile_sources({key})

    assert repository.request_cancel(key) is True
    assert repository.get(key).state == "cancelled"  # type: ignore[union-attr]

    retried = repository.retry(key)
    assert retried is not None and retried.state == "pending"


@pytest.mark.asyncio
async def test_scheduler_marks_success_and_schedules_next_run(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir()
    (manager.base_dir / "kb" / "metadata.json").write_text("{}", encoding="utf-8")
    manager.register_knowledge_base("kb")
    source = manager.add_web_source("kb", "https://example.com/docs/")
    source["sync_interval_hours"] = 2

    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = WebSourceSyncScheduler(
        repository=repository,
        manager_factory=lambda: manager,
    )
    await scheduler._synchronize_sources()
    job = repository.list_jobs("local-admin", "kb")[0]

    sync = AsyncMock(return_value=WebSyncResult(ok=True))
    with patch("deeptutor.services.web_source.sync.sync_source", sync):
        await scheduler._run_job(job)

    persisted = repository.get((job.owner_id, job.kb_name, job.source_id))
    assert persisted is not None
    assert persisted.state == "pending"
    assert persisted.attempt == 0
    assert persisted.next_run_at_ms > persisted.last_run_at_ms  # type: ignore[operator]
    sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_cancelled_run_is_not_marked_successful(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir()
    (manager.base_dir / "kb" / "metadata.json").write_text("{}", encoding="utf-8")
    manager.register_knowledge_base("kb")
    manager.add_web_source("kb", "https://example.com/docs/")

    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = WebSourceSyncScheduler(
        repository=repository,
        manager_factory=lambda: manager,
    )
    await scheduler._synchronize_sources()
    job = repository.list_jobs("local-admin", "kb")[0]

    sync = AsyncMock(side_effect=asyncio.CancelledError)
    with patch("deeptutor.services.web_source.sync.sync_source", sync):
        with pytest.raises(asyncio.CancelledError):
            await scheduler._run_job(job)

    persisted = repository.get((job.owner_id, job.kb_name, job.source_id))
    assert persisted is not None
    assert persisted.state == "cancelled"


@pytest.mark.asyncio
async def test_scheduler_ignores_manual_and_disabled_sources(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir()
    (manager.base_dir / "kb" / "metadata.json").write_text("{}", encoding="utf-8")
    manager.register_knowledge_base("kb")
    automatic = manager.add_web_source("kb", "https://auto.example.com/docs/")
    manager.add_web_source("kb", "https://disabled.example.com/docs/")
    manager.update_web_source_state(
        "kb",
        manager.get_web_sources("kb")[1]["id"],
        auto_sync_enabled=False,
    )

    scheduler = WebSourceSyncScheduler(
        repository=SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite"),
        manager_factory=lambda: manager,
    )
    await scheduler._synchronize_sources()

    assert [job.source_id for job in scheduler.repo.list_jobs("local-admin", "kb")] == [
        automatic["id"]
    ]
