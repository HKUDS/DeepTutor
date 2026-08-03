"""Best-effort memory reclamation after infrequent, allocation-heavy jobs."""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)
_reclaim_tasks: dict[asyncio.AbstractEventLoop, asyncio.Task[tuple[int, bool]]] = {}
_reclaim_tasks_lock = threading.Lock()


def release_unused_memory() -> tuple[int, bool]:
    """Collect cycles and ask glibc to return free heap pages on Linux.

    Python normally keeps freed arenas for reuse, which is fast but makes RSS
    look permanently pinned after document parsing or index construction.
    ``malloc_trim`` is glibc-specific, so every other platform simply gets the
    portable cycle collection step.
    """
    collected = gc.collect()
    trimmed = False
    if not sys.platform.startswith("linux"):
        return collected, trimmed

    try:
        import ctypes

        libc = ctypes.CDLL(None)
        malloc_trim = getattr(libc, "malloc_trim", None)
        if malloc_trim is not None:
            malloc_trim.argtypes = [ctypes.c_size_t]
            malloc_trim.restype = ctypes.c_int
            trimmed = bool(malloc_trim(0))
    except Exception:
        logger.debug("malloc_trim unavailable", exc_info=True)
    return collected, trimmed


def schedule_memory_reclaim() -> asyncio.Task[tuple[int, bool]] | None:
    """Coalesce reclamation after the current coroutine releases its locals."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    with _reclaim_tasks_lock:
        pending = _reclaim_tasks.get(loop)
        if pending is not None and not pending.done():
            return pending

    async def _reclaim() -> tuple[int, bool]:
        await asyncio.sleep(0)
        return await asyncio.to_thread(release_unused_memory)

    task = loop.create_task(_reclaim())
    with _reclaim_tasks_lock:
        _reclaim_tasks[loop] = task

    def _forget(completed: asyncio.Task[Any]) -> None:
        with _reclaim_tasks_lock:
            if _reclaim_tasks.get(loop) is completed:
                _reclaim_tasks.pop(loop, None)

    task.add_done_callback(_forget)
    return task


__all__ = ["release_unused_memory", "schedule_memory_reclaim"]
