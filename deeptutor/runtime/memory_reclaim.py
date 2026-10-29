"""Best-effort memory reclamation after infrequent, allocation-heavy jobs."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import gc
import logging
import sys
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)
_reclaim_tasks: dict[asyncio.AbstractEventLoop, asyncio.Task[tuple[int, bool]]] = {}
_reclaim_tasks_lock = threading.Lock()
_IDLE_SECONDS = 5.0
_MIN_IDLE_COLLECTION_INTERVAL = 30.0
_activity_lock = threading.Lock()
_active_turns = 0
_activity_generation = 0
_idle_handle: asyncio.TimerHandle | None = None
_idle_loop: asyncio.AbstractEventLoop | None = None
_last_idle_collection = 0.0


def cancel_idle_reclaim() -> None:
    """Invalidate scheduled idle work, including during application shutdown."""
    global _idle_handle, _idle_loop, _activity_generation
    with _activity_lock:
        _activity_generation += 1
        handle, loop = _idle_handle, _idle_loop
        _idle_handle = _idle_loop = None
    if handle is not None and loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(handle.cancel)


def _release_if_idle(generation: int) -> tuple[int, bool]:
    global _last_idle_collection
    # Check again in the worker, not just before to_thread: a new turn can
    # arrive while the executor is queuing this maintenance job.
    with _activity_lock:
        if _active_turns or generation != _activity_generation:
            return 0, False
        _last_idle_collection = time.monotonic()
    return release_unused_memory()


def _collect_when_idle(generation: int) -> None:
    global _idle_handle, _idle_loop
    with _activity_lock:
        if _active_turns or generation != _activity_generation:
            return
        _idle_handle = _idle_loop = None
    task = asyncio.create_task(asyncio.to_thread(_release_if_idle, generation))

    def observe(completed: asyncio.Task[Any]) -> None:
        if not completed.cancelled() and completed.exception() is not None:
            logger.debug("Idle memory reclamation failed", exc_info=completed.exception())

    task.add_done_callback(observe)


@contextmanager
def interactive_memory_scope():
    """Coalesce full GC after quiet time across chat, partner and capabilities.

    Generational GC stays enabled throughout. Full collection still takes the
    GIL; this policy moves it away from active turns rather than claiming a
    thread makes it non-blocking. A request arriving during collection can
    still briefly wait, so collections are also rate limited.
    """
    global _active_turns, _activity_generation, _idle_handle, _idle_loop
    cancel_idle_reclaim()
    with _activity_lock:
        _active_turns += 1
    try:
        yield
    finally:
        with _activity_lock:
            _active_turns -= 1
            _activity_generation += 1
            if _active_turns == 0:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None  # An abandoned async generator can close at shutdown.
                if loop is not None:
                    delay = max(
                        _IDLE_SECONDS,
                        _MIN_IDLE_COLLECTION_INTERVAL - (time.monotonic() - _last_idle_collection),
                    )
                    _idle_loop = loop
                    _idle_handle = loop.call_later(delay, _collect_when_idle, _activity_generation)


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


__all__ = [
    "cancel_idle_reclaim",
    "interactive_memory_scope",
    "release_unused_memory",
    "schedule_memory_reclaim",
]
