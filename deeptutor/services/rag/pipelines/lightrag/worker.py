"""Event-loop isolation helpers for local LightRAG indexing.

RAG-Anything's local storage backends perform synchronous graph merging and
JSON serialization from inside async methods.  Running those methods on the
service event loop therefore stalls unrelated API and LLM work.  This module
provides one narrow boundary: run the indexing coroutine on a worker thread's
private event loop, while explicitly forwarding network I/O and callbacks to
the event loop that owns the request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import concurrent.futures
import contextvars
import inspect
import logging
import threading
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

DEFAULT_WORKER_CANCEL_GRACE_SECONDS = 10.0


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
        self._cancel_requested.set()
        with self._lock:
            loop = self._loop
            task = self._task
        if loop is None or task is None:
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            # The worker completed and closed its loop between the snapshot and
            # the signal. Its executor future will become done independently.
            pass

    def stop_loop(self) -> None:
        """Escalate an async cancellation that exceeded its grace period."""
        with self._lock:
            loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
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
    """Run one async indexing job on a worker thread's private event loop.

    ``job`` and every object it creates should remain confined to that worker.
    The supplied bridge is the only supported route back to the owner loop.
    Worker exceptions are re-raised in the awaiting task.
    """
    owner_loop = asyncio.get_running_loop()
    bridge = OwnerLoopBridge(owner_loop)
    controller = _WorkerLoopController()
    caller_context = contextvars.copy_context()

    async def invoke_job() -> T:
        return await job(bridge)

    async def run_bound_job() -> T:
        controller.bind_current_task()
        try:
            return await invoke_job()
        finally:
            controller.clear()

    def run() -> T:
        return asyncio.run(run_bound_job())

    worker = owner_loop.run_in_executor(None, caller_context.run, run)
    try:
        # Shielding keeps cancellation of the request task from orphaning a
        # running worker.  Python cannot interrupt arbitrary synchronous code
        # safely, so cancellation becomes cooperative at the next bridge or
        # explicit check; meanwhile the owner loop stays alive for cleanup.
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
            # Stopping the private loop interrupts async work and makes
            # asyncio.run() cancel its remaining tasks during teardown. It
            # still cannot interrupt arbitrary synchronous Python/native work,
            # so keep waiting rather than returning an orphan that may mutate
            # the KB after the request has reported cancellation.
            logger.error(
                "LightRAG worker did not stop within %.1fs; forcing worker-loop teardown",
                grace,
            )
            controller.stop_loop()
            while not worker.done():
                try:
                    await asyncio.wait({worker})
                except asyncio.CancelledError:
                    bridge.cancel()
                    controller.cancel()
                    controller.stop_loop()
        # Retrieve the terminal exception so the executor Future never emits
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
