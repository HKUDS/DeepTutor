"""Process-wide media runtime lifecycle wiring (MED-03).

Owns the worker/scheduler/executor pair for every media root so queued,
polling and ``cancel_requested`` jobs progress in the background and recover
after a process restart (§11.3/§11.5).  Roots are discovered from the
persistent data layout:

* the default (admin) media root   ``data/user/workspace/media``
* every per-user media root        ``data/users/<uid>/workspace/media``

Each root gets its own :class:`MediaStore` + :class:`ImageGenerationJobWorker`
+ :class:`MediaScheduler`.  The provider executor (the MED-02
:class:`MediaAdapterRouter`) is built lazily on the first actionable job so a
process with no image profiles never opens HTTP clients at startup;
:meth:`MediaRuntimeManager.aclose` releases every executor at shutdown.

The process singleton (:func:`get_media_runtime`) uses
:func:`_default_executor_factory` so queued production jobs reach the real
MED-02 adapters; a manager constructed with ``executor_factory=None`` is the
explicit offline path that fails jobs with ``no_executor`` instead (used by
tests and deployments with no provider configured).

In production-discovery mode (no explicit ``roots=[...]``) the root set is
refreshed at each :meth:`MediaRuntimeManager.run_once` boundary, so a per-user
media root created *after* startup is picked up exactly once and that user's
jobs start advancing without a process restart.  Managers built with explicit
roots never scan the global layout (offline determinism).

Recovery is deliberately isolated per root: one corrupt record or one failing
root never blocks the others (the worker's own ``recover`` is per-record
tolerant as well).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

from deeptutor.services.media.scheduler import MediaScheduler
from deeptutor.services.media.store import MediaStore, default_media_root
from deeptutor.services.media.worker import ImageGenerationJobWorker, JobExecutor

logger = logging.getLogger(__name__)

#: Injectable sleep so offline tests advance the loop deterministically.
SleepFn = Callable[[float], Awaitable[None]]
#: Builds the JobExecutor (provider adapters) for one worker.  ``None`` means
#: "no provider configured" — the scheduler then fails jobs with a stable
#: ``no_executor`` state instead of guessing a provider.  The process singleton
#: passes :func:`_default_executor_factory` so production jobs reach the real
#: MED-02 adapters.
ExecutorFactory = Callable[[ImageGenerationJobWorker], JobExecutor]


def discover_media_roots() -> list[Path]:
    """Every media root that exists under the persistent data layout.

    The default root is always included (created lazily by the store); per-user
    roots under ``data/users/*/workspace/media`` are included only when they
    already exist, so a fresh deployment does not fabricate empty user trees.
    """
    roots = [Path(default_media_root())]
    try:
        from deeptutor.multi_user.paths import USERS_ROOT

        if USERS_ROOT.is_dir():
            for user_dir in sorted(USERS_ROOT.iterdir()):
                candidate = user_dir / "workspace" / "media"
                if candidate.is_dir():
                    roots.append(candidate)
    except Exception:  # noqa: BLE001 - optional discovery must never fail startup
        logger.debug("could not discover per-user media roots", exc_info=True)
    return roots


def _default_executor_factory(worker: ImageGenerationJobWorker) -> JobExecutor:
    from deeptutor.services.mcp import get_mcp_manager
    from deeptutor.services.media.adapters import MediaAdapterRouter

    return MediaAdapterRouter(store=worker.store, mcp_manager=get_mcp_manager())


class MediaRuntimeManager:
    """Advances every media root's actionable jobs on the calling event loop.

    API routes keep using fresh per-request stores (the repository's normal
    request-scoped pattern); this manager is the *process* owner that makes
    those durable jobs actually progress.  A single process holds one execution
    pass per job (the store's module-level lock makes compare-and-swap
    transitions hold across instances); multi-process replication is out of
    scope (§11.3).
    """

    def __init__(
        self,
        *,
        roots: list[Path] | None = None,
        executor_factory: ExecutorFactory | None = None,
        sleep: SleepFn | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._explicit_roots = roots is not None
        self._roots = [Path(p) for p in (roots if roots is not None else discover_media_roots())]
        self._root_keys = {self._root_key(p) for p in self._roots}
        self._executor_factory = executor_factory
        self._sleep = sleep or self._asyncio_sleep
        self._now = now
        self._workers: dict[str, ImageGenerationJobWorker] = {}
        self._schedulers: dict[str, MediaScheduler] = {}
        self._executors: dict[str, JobExecutor] = {}
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None

    @staticmethod
    async def _asyncio_sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

    @property
    def roots(self) -> list[Path]:
        return list(self._roots)

    @staticmethod
    def _root_key(root: Path) -> str:
        return str(Path(root).resolve())

    def _worker_for(self, root: Path) -> ImageGenerationJobWorker:
        key = self._root_key(root)
        worker = self._workers.get(key)
        if worker is None:
            worker = ImageGenerationJobWorker(store=MediaStore(root=root), now=self._now)
            self._workers[key] = worker
        return worker

    def _scheduler_for(self, root: Path) -> MediaScheduler:
        key = self._root_key(root)
        scheduler = self._schedulers.get(key)
        if scheduler is None:
            worker = self._worker_for(root)
            scheduler = MediaScheduler(worker, sleep=self._sleep, now=self._now)
            self._schedulers[key] = scheduler
        return scheduler

    def _ensure_executor(self, root: Path) -> None:
        key = self._root_key(root)
        if key in self._executors:
            return
        if self._executor_factory is None:
            return
        worker = self._worker_for(root)
        executor = self._executor_factory(worker)
        self._executors[key] = executor
        worker.set_executor(executor)

    def _refresh_roots(self) -> None:
        """Re-discover per-user roots created since startup (production mode).

        Only managers built *without* explicit ``roots=[...]`` refresh: those
        were initialized from the persistent layout and must pick up a user's
        media root the first time it appears during the running process, so that
        user's queued/polling/cancel_requested jobs advance without a restart.
        Managers given explicit roots never scan unrelated global roots
        (offline determinism).

        Existing workers/schedulers/executors are keyed by resolved root and are
        preserved; a newly discovered root simply gains fresh entries on first
        use, so nothing is duplicated and nothing already running is disturbed.
        """
        if self._explicit_roots:
            return
        for root in discover_media_roots():
            key = self._root_key(root)
            if key in self._root_keys:
                continue
            self._roots.append(Path(root))
            self._root_keys.add(key)
            logger.info("media runtime: discovered new per-user root %s", root)

    # ── recovery ─────────────────────────────────────────────────────────────

    def recover(self) -> list[dict[str, str]]:
        """Apply the deterministic restart rules to every root (§11.3).

        Returns the flattened per-job transitions.  A failing root logs its
        exception type and never blocks the remaining roots.
        """
        outcomes: list[dict[str, str]] = []
        for root in self._roots:
            try:
                outcomes.extend(self._worker_for(root).recover())
            except Exception as exc:  # noqa: BLE001 - one root must never stop startup
                logger.warning(
                    "media recovery failed for %s (%s)",
                    root,
                    type(exc).__name__,
                )
        return outcomes

    # ── execution loop ───────────────────────────────────────────────────────

    async def run_once(self) -> int:
        """Advance at most one actionable job per root; returns the count."""
        # Production-discovery mode: pick up per-user media roots created since
        # the last pass so those users' jobs start advancing without a restart.
        self._refresh_roots()
        advanced = 0
        for root in self._roots:
            scheduler = self._scheduler_for(root)
            job = scheduler.next_actionable()
            if job is None:
                continue
            self._ensure_executor(root)
            await scheduler.run_once()
            advanced += 1
        return advanced

    async def run_forever(self, *, interval: float = 1.0) -> None:
        """Advance jobs until :meth:`stop` is called."""
        while self._stop_event is None or not self._stop_event.is_set():
            await self.run_once()
            await self._sleep(interval)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self, *, interval: float = 1.0) -> asyncio.Task[None]:
        """Start the background scheduler task (idempotent)."""
        if self._task is not None and not self._task.done():
            return self._task
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self.run_forever(interval=interval))
        return self._task

    async def stop(self) -> None:
        """Stop the background loop and release every executor.

        A provider call may be mid-flight when shutdown arrives (long read
        timeouts are part of the design, §11.4).  We give the loop a short
        grace period to finish the current job, then cancel it: the worker's
        restart recovery deterministically reconciles an interrupted
        ``running``/``polling`` job on the next start (§11.3/§11.5), so a hard
        stop is safe and never blocks the process.
        """
        if self._stop_event is not None:
            self._stop_event.set()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    logger.debug("media scheduler task cancelled during shutdown")
        await self.aclose()

    async def aclose(self) -> None:
        """Best-effort close of every lazily-built provider executor."""
        for key, executor in list(self._executors.items()):
            closer = getattr(executor, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:  # noqa: BLE001 - best-effort shutdown
                    logger.debug("media executor %s close failed", key, exc_info=True)
        self._executors.clear()


#: Process-wide singleton, wired into the FastAPI lifespan by
#: ``deeptutor.api.main``.  Routes use per-request stores; this owns the
#: background execution that makes their durable jobs progress.
_runtime: MediaRuntimeManager | None = None


def get_media_runtime() -> MediaRuntimeManager:
    """The process-wide media runtime (created on first access).

    Production binds the real MED-02 adapter router through
    :func:`_default_executor_factory`; ``executor_factory=None`` (the
    constructor default) is the explicit offline path that disables executors.
    """
    global _runtime
    if _runtime is None:
        _runtime = MediaRuntimeManager(executor_factory=_default_executor_factory)
    return _runtime


def reset_media_runtime() -> None:
    """Drop the singleton (used by offline lifecycle tests)."""
    global _runtime
    _runtime = None


__all__ = [
    "ExecutorFactory",
    "MediaRuntimeManager",
    "SleepFn",
    "default_media_root",
    "discover_media_roots",
    "get_media_runtime",
    "reset_media_runtime",
]
