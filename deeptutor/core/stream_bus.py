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
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .stream import StreamEvent, StreamEventType
from .trace import merge_trace_metadata


class StreamBus:
    """Fan-out async event bus for a single chat turn."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._closed = False
        self._history: list[StreamEvent] = []

    async def emit(self, event: StreamEvent) -> None:
        """Push *event* to every active subscriber."""
        if self._closed:
            return
        self._history.append(event)
        for q in self._subscribers:
            await q.put(event)

    async def subscribe(self) -> AsyncIterator[StreamEvent]:
        """Yield events until the bus is closed."""
        q: asyncio.Queue[StreamEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        try:
            for event in self._history:
                yield event
            if self._closed and q.empty():
                return
            while True:
                event = await q.get()
                if event is None:
                    break
                yield event
        finally:
            self._subscribers.remove(q)

    async def close(self) -> None:
        """Signal all subscribers that the stream is finished."""
        self._closed = True
        for q in self._subscribers:
            await q.put(None)

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

    # ---- consumer adapters ----

    @staticmethod
    def event_to_json(event: StreamEvent) -> str:
        """Serialize an event to a single-line JSON string (NDJSON)."""
        return json.dumps(event.to_dict(), ensure_ascii=False)
