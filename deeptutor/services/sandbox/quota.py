"""
Per-user execution quotas.

Two cheap in-process guards against a runaway or abusive session:

* a concurrency cap (semaphore per user) — no more than N executions in
  flight at once;
* a sliding 60-second rate cap — no more than M executions started per
  minute.

In-process is sufficient for the single-container deployment; a multi-replica
deployment would move these to a shared store. Quotas are keyed by user id so
one user cannot starve another.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
import time


class QuotaExceeded(Exception):
    """Raised when a user is over their concurrency or rate quota."""


class UserExecQuota:
    def __init__(self, *, max_concurrent: int, max_per_minute: int) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._max_per_minute = max(1, max_per_minute)
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._recent: dict[str, deque[float]] = defaultdict(deque)

    def _semaphore(self, user_id: str) -> asyncio.Semaphore:
        sem = self._semaphores.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(self._max_concurrent)
            self._semaphores[user_id] = sem
        return sem

    def _check_rate(self, user_id: str, now: float) -> None:
        window = self._recent[user_id]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max_per_minute:
            raise QuotaExceeded(f"execution rate limit reached ({self._max_per_minute}/min)")
        window.append(now)

    class _Lease:
        def __init__(self, sem: asyncio.Semaphore) -> None:
            self._sem = sem

        async def __aenter__(self) -> "UserExecQuota._Lease":
            return self

        async def __aexit__(self, *exc: object) -> None:
            self._sem.release()

    async def acquire(self, user_id: str, *, now: float | None = None) -> "_Lease":
        """Reserve a slot for *user_id*; raise :class:`QuotaExceeded` if over.

        Use as an async context manager so the concurrency slot is always
        released::

            async with await quota.acquire(uid):
                ...
        """
        now = time.monotonic() if now is None else now
        sem = self._semaphore(user_id)
        if sem.locked() and sem._value <= 0:  # type: ignore[attr-defined]
            raise QuotaExceeded(f"too many concurrent executions (max {self._max_concurrent})")
        self._check_rate(user_id, now)
        await sem.acquire()
        return UserExecQuota._Lease(sem)


__all__ = ["QuotaExceeded", "UserExecQuota"]
