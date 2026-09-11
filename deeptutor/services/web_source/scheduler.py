"""Durable background scheduler for account-scoped web sources."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time
from typing import Any
import uuid

from deeptutor.services.web_source.repository import (
    SQLiteWebSourceSyncRepository,
    WebSourceSyncJob,
)

logger = logging.getLogger(__name__)

WEB_SYNC_MIN_INTERVAL_HOURS = 1
WEB_SYNC_MAX_INTERVAL_HOURS = 168
WEB_SYNC_INTERVAL_HOURS = 24
WEB_SYNC_CHECK_SECONDS = 15
WEB_SYNC_LEASE_HOURS = 6
WEB_SYNC_MAX_CONCURRENCY = 2


def _now_ms() -> int:
    return int(time.time() * 1000)


def _hours_ms(hours: int) -> int:
    return hours * 60 * 60 * 1000


def default_repository() -> SQLiteWebSourceSyncRepository:
    from deeptutor.multi_user.paths import SYSTEM_ROOT

    return SQLiteWebSourceSyncRepository(SYSTEM_ROOT / "web-source-sync.sqlite")


def normalize_sync_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        return WEB_SYNC_INTERVAL_HOURS
    return max(WEB_SYNC_MIN_INTERVAL_HOURS, min(WEB_SYNC_MAX_INTERVAL_HOURS, interval))


class WebSourceSyncScheduler:
    """Run due web-source jobs while preserving state across restarts."""

    def __init__(
        self,
        *,
        repository: SQLiteWebSourceSyncRepository | None = None,
        manager_factory: Callable[[], Any] | None = None,
        check_interval_s: float = WEB_SYNC_CHECK_SECONDS,
        max_concurrency: int = WEB_SYNC_MAX_CONCURRENCY,
    ) -> None:
        self._repository = repository
        self._manager_factory = manager_factory
        self._check_interval_s = check_interval_s
        self._max_concurrency = max_concurrency
        self._runner_id = f"web-sync-{uuid.uuid4().hex}"
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._run_tasks: dict[tuple[str, str, str], asyncio.Task[None]] = {}
        self._sources: dict[tuple[str, str, str], dict[str, Any]] = {}

    @property
    def repo(self) -> SQLiteWebSourceSyncRepository:
        if self._repository is None:
            self._repository = default_repository()
        return self._repository

    def _make_manager(self) -> Any:
        if self._manager_factory is not None:
            return self._manager_factory()
        from deeptutor.knowledge.manager import KnowledgeBaseManager
        from deeptutor.multi_user.knowledge_access import current_kb_base_dir

        return KnowledgeBaseManager(base_dir=str(current_kb_base_dir()))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.repo.recover_interrupted(self._runner_id)
        self._task = asyncio.create_task(self._loop(), name="web-source-sync:scheduler")
        logger.info("Web source sync scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._run_tasks:
            for task in self._run_tasks.values():
                task.cancel()
            await asyncio.gather(*self._run_tasks.values(), return_exceptions=True)
            self._run_tasks.clear()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._synchronize_sources()
                self._start_due_jobs()
            except Exception:
                logger.exception("Web source scheduler cycle failed")
            await asyncio.sleep(self._check_interval_s)

    def _manager_for_owner(self, owner_id: str) -> Any:
        from deeptutor.multi_user.context import reset_current_user, set_current_user
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import (
            LOCAL_ADMIN_ID,
            ensure_scope_workspace,
            local_admin_user,
            scope_for_user,
        )

        user = (
            local_admin_user()
            if owner_id == LOCAL_ADMIN_ID
            else CurrentUser(
                id=owner_id,
                username=owner_id,
                role="user",
                scope=scope_for_user(owner_id, is_admin=False),
            )
        )
        if user.scope.kind == "user":
            ensure_scope_workspace(user.scope)
        token = set_current_user(user)
        try:
            return self._make_manager()
        finally:
            reset_current_user(token)

    async def _synchronize_sources(self) -> None:
        from deeptutor.multi_user.paths import LOCAL_ADMIN_ID, USERS_ROOT

        manager = self._manager_for_owner(LOCAL_ADMIN_ID)
        owner_ids = [LOCAL_ADMIN_ID, *(path.name for path in USERS_ROOT.glob("*") if path.is_dir())]
        # The first manager call above also validates the configured admin path.
        del manager
        source_keys: set[tuple[str, str, str]] = set()
        sources: dict[tuple[str, str, str], dict[str, Any]] = {}
        for owner_id in owner_ids:
            try:
                owner_manager = await asyncio.to_thread(self._manager_for_owner, owner_id)
                for kb_name, source in owner_manager.get_all_web_sources():
                    if not source.get("enabled", True):
                        continue
                    if not source.get("auto_sync_enabled", True):
                        continue
                    source_id = str(source.get("id") or "")
                    kb_key = str(kb_name)
                    if not source_id or not kb_key:
                        continue
                    key = owner_id, kb_key, source_id
                    source_keys.add(key)
                    sources[key] = dict(source)
            except Exception:
                logger.exception("Failed to enumerate web sources for owner %s", owner_id)
        self._sources = sources
        await asyncio.to_thread(self.repo.reconcile_sources, source_keys)

    def _start_due_jobs(self) -> None:
        for job in self.repo.due_jobs():
            key = self.repo.key(job)
            if key in self._run_tasks:
                continue
            if len(self._run_tasks) >= self._max_concurrency:
                return
            task = asyncio.create_task(self._run_job(job), name=f"web-source-sync:{key[2]}")
            self._run_tasks[key] = task
            task.add_done_callback(lambda _task, item=key: self._run_tasks.pop(item, None))

    async def _run_job(self, scheduled: WebSourceSyncJob) -> None:
        from deeptutor.multi_user.context import reset_current_user, set_current_user
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import (
            LOCAL_ADMIN_ID,
            ensure_scope_workspace,
            local_admin_user,
            scope_for_user,
        )
        from deeptutor.services.web_source.sync import sync_source

        key = self.repo.key(scheduled)
        lease_until = _now_ms() + _hours_ms(WEB_SYNC_LEASE_HOURS)
        claimed = await asyncio.to_thread(
            self.repo.claim,
            scheduled,
            runner_id=self._runner_id,
            lease_until_ms=lease_until,
        )
        if claimed is None:
            return
        source = self._sources.get(key)
        if source is None:
            self.repo.mark_cancelled(claimed)
            return

        user = (
            local_admin_user()
            if claimed.owner_id == LOCAL_ADMIN_ID
            else CurrentUser(
                id=claimed.owner_id,
                username=claimed.owner_id,
                role="user",
                scope=scope_for_user(claimed.owner_id, is_admin=False),
            )
        )
        if user.scope.kind == "user":
            ensure_scope_workspace(user.scope)
        token = set_current_user(user)
        try:
            current = await asyncio.to_thread(self.repo.get, key)
            if current is not None and current.cancel_requested:
                self.repo.mark_cancelled(current)
                return
            result = await sync_source(
                kb_name=claimed.kb_name,
                source=source,
                base_dir=str(self._make_manager().base_dir),
                max_depth=source.get("max_depth"),
                max_pages=source.get("max_pages"),
            )
            current = await asyncio.to_thread(self.repo.get, key)
            if current is not None and current.cancel_requested:
                self.repo.mark_cancelled(current)
                return
            if result.ok:
                interval = normalize_sync_interval(source.get("sync_interval_hours"))
                self.repo.mark_success(claimed, _now_ms() + _hours_ms(interval))
            else:
                self._mark_failure(claimed, source, result.error or "Web synchronization failed")
        except asyncio.CancelledError:
            self.repo.mark_cancelled(claimed, _now_ms())
            raise
        except Exception as exc:
            logger.exception("Scheduled web source sync failed for %s", source.get("url"))
            self._mark_failure(claimed, source, str(exc))
        finally:
            reset_current_user(token)

    def _mark_failure(
        self,
        job: WebSourceSyncJob,
        source: dict[str, Any],
        error: str,
    ) -> None:
        interval = normalize_sync_interval(source.get("sync_interval_hours"))
        backoff = min(interval, WEB_SYNC_MIN_INTERVAL_HOURS * max(1, job.attempt + 1))
        self.repo.mark_failure(
            job,
            error=error,
            next_run_at_ms=_now_ms() + _hours_ms(backoff),
        )

    async def request_cancel(self, owner_id: str, kb_name: str, source_id: str) -> bool:
        key = owner_id, kb_name, source_id
        if not await asyncio.to_thread(self.repo.request_cancel, key):
            return False
        task = self._run_tasks.get(key)
        if task is not None and not task.done():
            task.cancel()
        return True

    async def retry(self, owner_id: str, kb_name: str, source_id: str) -> bool:
        job = await asyncio.to_thread(self.repo.retry, (owner_id, kb_name, source_id))
        return job is not None


_scheduler: WebSourceSyncScheduler | None = None


def get_web_source_sync_scheduler() -> WebSourceSyncScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = WebSourceSyncScheduler()
    return _scheduler


async def start_web_source_sync_scheduler() -> None:
    await get_web_source_sync_scheduler().start()


async def stop_web_source_sync_scheduler() -> None:
    await get_web_source_sync_scheduler().stop()


__all__ = [
    "WEB_SYNC_INTERVAL_HOURS",
    "WEB_SYNC_MAX_INTERVAL_HOURS",
    "WEB_SYNC_MIN_INTERVAL_HOURS",
    "WebSourceSyncScheduler",
    "get_web_source_sync_scheduler",
    "normalize_sync_interval",
    "start_web_source_sync_scheduler",
    "stop_web_source_sync_scheduler",
]
