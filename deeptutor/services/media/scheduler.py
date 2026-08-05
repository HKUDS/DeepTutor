"""Async media job scheduler (MED-02).

The worker owns the state machine and persistence; the scheduler owns the
*event loop* that advances jobs.  Per §11.3/§11.5 it only ever touches
actionable states — ``queued`` (execute), ``polling`` (retrieve), and
``cancel_requested`` (cancel confirmation) — and never re-runs automatic
terminal states.  A ``polling`` job is not retrieved again before its
``poll_after`` has passed, so background polling respects the backoff window
(§11.4).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from deeptutor.services.media.models import (
    ImageGenerationJob,
    ImageJobStatus,
    JobStateError,
)
from deeptutor.services.media.worker import ImageGenerationJobWorker

logger = logging.getLogger(__name__)

SleepFn = Callable[[float], Awaitable[None]]
NowFn = Callable[[], float]

#: Priority for selecting the next actionable job (lower wins).
_PRIORITY = {
    ImageJobStatus.CANCEL_REQUESTED: 0,
    ImageJobStatus.QUEUED: 1,
    ImageJobStatus.POLLING: 2,
}

_ACTIONABLE = (ImageJobStatus.QUEUED, ImageJobStatus.POLLING, ImageJobStatus.CANCEL_REQUESTED)


class MediaScheduler:
    """Advances actionable image jobs on the calling event loop."""

    def __init__(
        self,
        worker: ImageGenerationJobWorker,
        *,
        sleep: SleepFn | None = None,
        now: NowFn | None = None,
    ) -> None:
        self._worker = worker
        self._sleep = sleep or self._asyncio_sleep
        self._now = now or time.time

    @staticmethod
    async def _asyncio_sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)

    @property
    def worker(self) -> ImageGenerationJobWorker:
        return self._worker

    def next_actionable(self, *, now: float | None = None) -> ImageGenerationJob | None:
        """The next job the loop should advance, or ``None``.

        Ordering is deterministic: cancel first (a user is waiting), then new
        work, then the polling job whose ``poll_after`` passed earliest.  A
        polling job whose delay has not elapsed is never returned.
        """
        now = self._now() if now is None else now
        candidates: list[ImageGenerationJob] = []
        for job in self._worker.store.list_jobs():
            if job.status not in _ACTIONABLE:
                continue
            if job.status == ImageJobStatus.POLLING:
                if job.poll_after and now < job.poll_after:
                    continue
            candidates.append(job)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda job: (
                _PRIORITY[job.status],
                job.poll_after if job.status == ImageJobStatus.POLLING else 0.0,
            ),
        )

    async def run_once(self, *, now: float | None = None) -> str | None:
        """Advance exactly one job; returns its id, or ``None`` when idle."""
        job = self.next_actionable(now=now)
        if job is None:
            return None
        try:
            if job.status == ImageJobStatus.CANCEL_REQUESTED:
                await self._worker.run_cancel(job.id)
            elif job.status == ImageJobStatus.POLLING:
                await self._worker.poll_job(job.id)
            else:
                await self._worker.run_job(job.id)
        except JobStateError as exc:
            # A concurrent transition already finalized the job; this is a
            # diagnostic skip, not a failure.
            logger.debug("scheduler: job %s already advanced (%s)", job.id, exc)
        except Exception as exc:  # noqa: BLE001 - one job must never stop the loop
            logger.warning("scheduler: job %s failed to advance (%s)", job.id, type(exc).__name__)
        return job.id

    async def run_forever(
        self,
        *,
        interval: float = 1.0,
        stop: asyncio.Event | None = None,
    ) -> None:
        """Process jobs until *stop* is set (or forever)."""
        while stop is None or not stop.is_set():
            await self.run_once()
            await self._sleep(interval)


__all__ = ["MediaScheduler", "SleepFn", "NowFn"]
