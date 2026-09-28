"""Event-loop isolation helpers for local LightRAG indexing.

LightRAG's local storage backends perform synchronous graph merging and
JSON serialization from inside async methods.  Running those methods on the
service event loop therefore stalls unrelated API and LLM work.  This module
provides one narrow boundary: run local LightRAG coroutines on a process-wide
worker event loop, while explicitly forwarding network I/O and callbacks to
the event loop that owns each request. LightRAG's storage locks are process-wide.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import concurrent.futures
import contextvars
import inspect
import logging
import os
import threading
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

DEFAULT_WORKER_CANCEL_GRACE_SECONDS = 10.0
_WORKER_LOOP_LOCK = threading.Lock()
_WORKER_LOOP: asyncio.AbstractEventLoop | None = None
_WORKER_THREAD: threading.Thread | None = None
_WORKER_PID: int | None = None


def _worker_loop() -> asyncio.AbstractEventLoop:
    """Return the one loop that owns all local LightRAG asyncio locks (#1578)."""
    global _WORKER_LOOP, _WORKER_THREAD, _WORKER_PID
    with _WORKER_LOOP_LOCK:
        pid = os.getpid()
        if _WORKER_PID != pid:
            # A fork inherits Python globals, but not the worker's thread.
            _WORKER_LOOP = None
            _WORKER_THREAD = None
            _WORKER_PID = pid
        if _WORKER_LOOP is None:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever,
                name="lightrag-worker-loop",
                daemon=True,
            )
            thread.start()
            _WORKER_LOOP = loop
            _WORKER_THREAD = thread
        elif _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            # A new loop in this process would reuse locks bound to the old one.
            raise RuntimeError("LightRAG worker loop stopped; restart DeepTutor.")
        return _WORKER_LOOP


class _WorkerLoopController:
    """Thread-safe cancellation handle for the worker loop's top-level task."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel_requested = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None

    def bind_current_task(self) -> None:
        """Bind from inside the worker loop and honor an earlier cancellation."""
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        if task is None:  # pragma: no cover - asyncio always owns this coroutine
            raise RuntimeError("Worker loop has no current task")
        with self._lock:
            self._loop = loop
            self._task = task
            cancel_requested = self._cancel_requested.is_set()
        if cancel_requested:
            task.cancel()

    def clear(self) -> None:
        """Drop references once the worker job reaches a terminal state."""
        with self._lock:
            self._loop = None
            self._task = None

    def cancel(self) -> None:
        """Cancel the worker's actual top-level task, including before bind."""
        if self._cancel_requested.is_set():
            return
        self._cancel_requested.set()
        with self._lock:
            loop = self._loop
            task = self._task
        if loop is None or task is None:
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            # The worker loop failed between the snapshot and the signal.
            pass


class OwnerLoopBridge:
    """Run selected awaitables and callbacks on the service event loop.

    The worker receives a copy of the caller's :mod:`contextvars` context.
    ``run`` schedules from that copied context, so request-local model and user
    configuration remains visible on the owner loop.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._cancelled = threading.Event()
        self._pending_lock = threading.Lock()
        self._pending: set[concurrent.futures.Future[Any]] = set()

    def cancel(self) -> None:
        """Reject new owner-loop work and cancel requests already in flight."""
        self._cancelled.set()
        with self._pending_lock:
            pending = tuple(self._pending)
        for future in pending:
            future.cancel()

    def raise_if_cancelled(self) -> None:
        """Cooperatively stop the worker at a safe async boundary."""
        if self._cancelled.is_set():
            raise asyncio.CancelledError

    async def run(self, factory: Callable[[], Awaitable[T]]) -> T:
        """Await ``factory`` on the owner loop and propagate its result/error."""
        self.raise_if_cancelled()
        if asyncio.get_running_loop() is self._loop:
            return await factory()

        async def invoke() -> T:
            return await factory()

        coroutine = invoke()
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        except BaseException:
            coroutine.close()
            raise
        with self._pending_lock:
            if self._cancelled.is_set():
                future.cancel()
            else:
                self._pending.add(future)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise
        finally:
            with self._pending_lock:
                self._pending.discard(future)

    async def call(self, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke a sync or async callback on the owner loop."""

        async def invoke() -> Any:
            result = callback(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        return await self.run(invoke)


async def run_in_worker_loop(
    job: Callable[[OwnerLoopBridge], Awaitable[T]],
    *,
    cancel_grace_seconds: float = DEFAULT_WORKER_CANCEL_GRACE_SECONDS,
) -> T:
    """Run one local LightRAG job on the process-wide worker event loop.

    ``job`` and every object it creates should remain confined to that worker.
    The supplied bridge is the only supported route back to the owner loop.
    Worker exceptions are re-raised in the awaiting task.
    """
    owner_loop = asyncio.get_running_loop()
    bridge = OwnerLoopBridge(owner_loop)
    controller = _WorkerLoopController()
    caller_context = contextvars.copy_context()

    finished: concurrent.futures.Future[T] = concurrent.futures.Future()

    async def run_bound_job() -> None:
        try:
            controller.bind_current_task()
            result = await job(bridge)
        except BaseException as exc:
            finished.set_exception(exc)
        else:
            finished.set_result(result)
        finally:
            controller.clear()

    worker_loop = _worker_loop()

    def submit() -> None:
        try:
            worker_loop.create_task(run_bound_job(), context=caller_context)
        except BaseException as exc:
            finished.set_exception(exc)

    worker_loop.call_soon_threadsafe(submit)
    # run_coroutine_threadsafe's Future becomes cancelled before its coroutine
    # finishes cleanup. This completion Future resolves only after job exits.
    worker = asyncio.wrap_future(finished)
    try:
        # Shielding keeps request cancellation from cancelling the completion
        # signal. The owner waits for the worker's cleanup below.
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        bridge.cancel()
        controller.cancel()
        grace = max(float(cancel_grace_seconds), 0.0)
        deadline = owner_loop.time() + grace
        while not worker.done() and owner_loop.time() < deadline:
            try:
                remaining = max(deadline - owner_loop.time(), 0.0)
                await asyncio.wait({worker}, timeout=remaining)
            except asyncio.CancelledError:
                # Repeated cancellation still must not strand the worker on a
                # request scheduled back to this owner loop.
                bridge.cancel()
                controller.cancel()
        if not worker.done():
            # Stopping this loop would strand unrelated jobs and leave locks
            # bound to a stopped loop. Wait for confirmed cleanup instead.
            logger.error(
                "LightRAG worker did not stop within %.1fs; waiting for confirmed cleanup",
                grace,
            )
            while not worker.done():
                try:
                    await asyncio.wait({worker})
                except asyncio.CancelledError:
                    bridge.cancel()
                    controller.cancel()
        # Retrieve the terminal exception so the completion Future never emits
        # an "exception was never retrieved" warning.  The caller's
        # cancellation remains authoritative.
        try:
            worker.result()
        except BaseException:
            pass
        raise


__all__ = [
    "DEFAULT_WORKER_CANCEL_GRACE_SECONDS",
    "OwnerLoopBridge",
    "run_in_worker_loop",
]
