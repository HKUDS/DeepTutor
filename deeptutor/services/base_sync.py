"""Abstract base class for background source-sync services.

Source-sync services share lifecycle management (start/stop/event-loop)
and staleness detection logic. This module provides the shared
implementation so subclasses only need to implement ``_sync_one_cycle``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 3600
_DEFAULT_STALE_HOURS = 24


def is_stale(source: dict, *, stale_hours: float = _DEFAULT_STALE_HOURS) -> bool:
    """Return True if *source* hasn't been synced within *stale_hours*."""
    last = source.get("last_synced_at") or ""
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age >= stale_hours * 3600


def default_base_dir() -> str:
    """Return the default knowledge-base directory for the current project."""
    try:
        from deeptutor.services.path_service import get_path_service

        return str(get_path_service().project_root / "data" / "knowledge_bases")
    except Exception:
        from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR

        return DEFAULT_BASE_DIR


class BaseSourceSyncService(ABC):
    """Abstract base for periodic source-sync background services.

    Subclasses implement :meth:`_sync_one_cycle` (the per-iteration work)
    and optionally override :attr:`task_name` for logging.
    """

    def __init__(
        self, *, base_dir: str | None = None, check_interval_s: int = _CHECK_INTERVAL_SECONDS
    ):
        self._base_dir = base_dir
        self._check_interval_s = check_interval_s
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def task_name(self) -> str:
        """Name used for the asyncio task (override in subclasses)."""
        return "source-sync"

    @property
    def effective_base_dir(self) -> str:
        return self._base_dir or default_base_dir()

    # -- lifecycle (shared, concrete) --------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name=self.task_name)
        logger.info("%s started", self.__class__.__name__)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("%s stopped", self.__class__.__name__)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._sync_one_cycle()
            except Exception:
                logger.exception("%s loop error", self.__class__.__name__)
            await asyncio.sleep(self._check_interval_s)

    # -- to be implemented by subclasses -----------------------------

    @abstractmethod
    async def _sync_one_cycle(self) -> None:
        """Run one pass of syncing. Called repeatedly by the loop."""
        ...
