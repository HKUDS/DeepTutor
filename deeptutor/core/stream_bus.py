"""
Stream Bus
==========

Async event channel that tools / capabilities emit into and consumers
(CLI renderer, WebSocket pusher, JSON writer) read from.

Usage::

    bus = StreamBus()

    # Producer side (inside a capability)
    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="Hello"))

    # Consumer side
    async for event in bus.subscribe():
        print(event.content)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any, AsyncIterator

from .stream import StreamEvent, StreamEventType
from .trace import merge_trace_metadata


class StreamBus:
    """Fan-out async event bus for a single chat turn."""

    def __init__(self, *, max_history: int | None = None) -> None:
        # Keep the owning loop with each queue. Production normally uses one
        # uvicorn loop, but desktop/TestClient hosts can serve sockets on
        # different loops; writing an asyncio.Queue from another loop does not
        # reliably wake its waiter.
        self._subscribers: list[
            tuple[asyncio.Queue[StreamEvent | None], asyncio.AbstractEventLoop]
        ] = []
        self._closed = False
        self._history: list[StreamEvent] = []
        self._input_listeners: list[asyncio.Queue[str]] = []
        # ``None`` keeps the full history (turn-scoped buses live and die with
        # one turn). Long-lived buses pass a bound so replay stays useful
        # without growing without limit.
        self._max_history = max_history

    async def emit(self, event: StreamEvent) -> None:
        """Push *event* to every active subscriber."""
        if self._closed:
            return
        self._history.append(event)
        if self._max_history is not None and len(self._history) > self._max_history:
            del self._history[: len(self._history) - self._max_history]
        current_loop = asyncio.get_running_loop()
        for q, loop in list(self._subscribers):
            if loop is current_loop:
                await q.put(event)
            elif not loop.is_closed():
                loop.call_soon_threadsafe(q.put_nowait, event)

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        """Yield events until the bus is closed."""
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        subscriber = (q, asyncio.get_running_loop())
        self._subscribers.append(subscriber)
        # Snapshot the replay range in the same synchronous step as the
        # queue registration: events emitted while we replay are delivered
        # via the queue only. Iterating the live list instead would yield
        # those events twice (list-append during iteration + queue copy).
        replay_count = len(self._history)
        try:
            for event in self._history[:replay_count]:
                yield event
            if self._closed and q.empty():
                return
            while True:
                event = await q.get()
                if event is None:
                    break
                yield event
        finally:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def mark_closed(self) -> None:
        """Synchronous ``close()``.

        Safe because subscriber queues are unbounded, so handing them the
        sentinel never blocks. Lets synchronous call sites (engine teardown,
        CLI paths) shut a bus down without an event loop.
        """
        self._closed = True
        for q, loop in list(self._subscribers):
            try:
                if loop.is_running():
                    loop.call_soon_threadsafe(q.put_nowait, None)
                elif not loop.is_closed():
                    q.put_nowait(None)
            except RuntimeError:
                continue

    async def close(self) -> None:
        """Signal all subscribers that the stream is finished."""
        self.mark_closed()

    # ---- convenience helpers for producers ----

    @asynccontextmanager
    async def stage(
        self,
        name: str,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        """Context manager that emits STAGE_START / STAGE_END around a block."""
        await self.emit(
            StreamEvent(
                type=StreamEventType.STAGE_START,
                source=source,
                stage=name,
                metadata=metadata or {},
            )
        )
        try:
            yield
        finally:
            await self.emit(
                StreamEvent(
                    type=StreamEventType.STAGE_END,
                    source=source,
                    stage=name,
                    metadata=metadata or {},
                )
            )

    async def content(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.CONTENT,
                source=source,
                stage=stage,
                content=text,
                metadata=metadata or {},
            )
        )

    async def thinking(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.THINKING,
                source=source,
                stage=stage,
                content=text,
                metadata=metadata or {},
            )
        )

    async def observation(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.OBSERVATION,
                source=source,
                stage=stage,
                content=text,
                metadata=metadata or {},
            )
        )

    async def tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.TOOL_CALL,
                source=source,
                stage=stage,
                content=tool_name,
                metadata=merge_trace_metadata({"args": args}, metadata),
            )
        )

    async def tool_result(
        self,
        tool_name: str,
        result: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.TOOL_RESULT,
                source=source,
                stage=stage,
                content=result,
                metadata=merge_trace_metadata({"tool": tool_name}, metadata),
            )
        )

    async def progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source=source,
                stage=stage,
                content=message,
                metadata=merge_trace_metadata(
                    {"current": current, "total": total},
                    metadata,
                ),
            )
        )

    async def sources(
        self,
        sources: list[dict[str, Any]],
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.SOURCES,
                source=source,
                stage=stage,
                metadata=merge_trace_metadata({"sources": sources}, metadata),
            )
        )

    async def result(
        self,
        data: dict[str, Any],
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.RESULT,
                source=source,
                metadata=merge_trace_metadata(data, metadata),
            )
        )

    async def error(
        self,
        message: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.emit(
            StreamEvent(
                type=StreamEventType.ERROR,
                source=source,
                stage=stage,
                content=message,
                metadata=metadata or {},
            )
        )

    async def wait_for_input(
        self,
        prompt: str,
        source: str = "",
        stage: str = "",
        timeout: float | None = None,
    ) -> str:
        """Pause capability execution and wait for user input from the frontend.

        Returns the user's input, or an empty string if *timeout* seconds elapse
        with no input (e.g. when running from a CLI that cannot send input).
        Pass ``timeout=None`` (the default) to wait indefinitely for interactive
        clients; pass a finite value for headless/CLI entry points.
        """
        await self.emit(
            StreamEvent(
                type=StreamEventType.WAIT_FOR_INPUT,
                source=source,
                stage=stage,
                content=prompt,
            )
        )
        input_queue: asyncio.Queue[str] = asyncio.Queue()
        self._input_listeners.append(input_queue)
        try:
            return await asyncio.wait_for(input_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return ""
        finally:
            if input_queue in self._input_listeners:
                self._input_listeners.remove(input_queue)

    def submit_input(self, content: str) -> None:
        """Receive user input from the frontend/WS and deliver to waiters."""
        for q in self._input_listeners:
            q.put_nowait(content)
        self._input_listeners.clear()

    # ---- consumer adapters ----

    @staticmethod
    def event_to_json(event: StreamEvent) -> str:
        """Serialize an event to a single-line JSON string (NDJSON)."""
        return json.dumps(event.to_dict(), ensure_ascii=False)


# ---- per-turn bus registry for user_input routing ----

_bus_registry: dict[str, StreamBus] = {}


def register_bus(turn_id: str, bus: StreamBus) -> None:
    """Register a bus so ``user_input`` WS messages can find it."""
    _bus_registry[turn_id] = bus


def unregister_bus(turn_id: str) -> None:
    """Remove a bus from the registry."""
    _bus_registry.pop(turn_id, None)


def get_bus(turn_id: str) -> StreamBus | None:
    """Look up the active bus for *turn_id*."""
    return _bus_registry.get(turn_id)
