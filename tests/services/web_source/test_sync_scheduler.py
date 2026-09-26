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
    assert persisted.state == "interrupted"


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


def test_reconcile_preserves_jobs_for_an_owner_that_failed_to_scan(tmp_path: Path) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    old = ("local-admin", "kb", "old")
    repository.reconcile_sources({old})
    repository.reconcile_sources(set(), scanned_owner_ids=set())
    assert repository.get(old) is not None
    repository.reconcile_sources(set(), scanned_owner_ids={"local-admin"})
    assert repository.get(old) is None


def test_expired_owner_cannot_overwrite_a_new_claim(tmp_path: Path, monkeypatch) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    now = [1_000]
    monkeypatch.setattr(repository, "_now_ms", lambda: now[0])
    key = ("local-admin", "kb", "source")
    repository.reconcile_sources({key})
    old = repository.claim(repository.get(key), runner_id="runner-old", lease_until_ms=2_000)
    assert old is not None
    assert repository.renew_lease(old, 3_000) is True
    now[0] = 3_001
    assert repository.renew_lease(old, 4_000) is False
    repository.recover_interrupted("runner-new")
    new = repository.claim(repository.get(key), runner_id="runner-new", lease_until_ms=4_000)
    assert new is not None
    repository.mark_success(old, 9_000)
    assert repository.get(key).runner_id == "runner-new"
    repository.mark_success(new, 9_000)
    assert repository.get(key).state == "pending"


@pytest.mark.asyncio
async def test_failed_owner_enumeration_does_not_delete_persisted_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    key = ("local-admin", "kb", "source")
    repository.reconcile_sources({key})
    scheduler = WebSourceSyncScheduler(repository=repository)

    class BrokenManager:
        def get_all_web_sources(self):
            raise RuntimeError("temporary read failure")

    monkeypatch.setattr(scheduler, "_manager_for_owner", lambda _owner: BrokenManager())
    await scheduler._synchronize_sources()
    assert repository.get(key) is not None
    assert scheduler._sources == {}


@pytest.mark.asyncio
async def test_scheduler_renews_lease_during_a_long_sync(tmp_path: Path, monkeypatch) -> None:
    from deeptutor.services.web_source import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "WEB_SYNC_LEASE_SECONDS", 0.2)
    monkeypatch.setattr(scheduler_module, "WEB_SYNC_LEASE_RENEW_SECONDS", 0.04)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    (manager.base_dir / "kb").mkdir()
    (manager.base_dir / "kb" / "metadata.json").write_text("{}", encoding="utf-8")
    manager.register_knowledge_base("kb")
    manager.add_web_source("kb", "https://example.com/docs/")
    repository = SQLiteWebSourceSyncRepository(tmp_path / "jobs.sqlite")
    scheduler = WebSourceSyncScheduler(repository=repository, manager_factory=lambda: manager)
    await scheduler._synchronize_sources()
    job = repository.list_jobs("local-admin", "kb")[0]

    async def slow_sync(**_kwargs):
        await asyncio.sleep(0.35)
        return WebSyncResult(ok=True)

    with patch("deeptutor.services.web_source.sync.sync_source", slow_sync):
        running = asyncio.create_task(scheduler._run_job(job))
        await asyncio.sleep(0.25)
        current = repository.get(repository.key(job))
        assert current is not None and current.state == "running"
        assert current.lease_until_ms is not None and current.lease_until_ms > int(
            time.time() * 1000
        )
        await running
    assert repository.get(repository.key(job)).state == "pending"
