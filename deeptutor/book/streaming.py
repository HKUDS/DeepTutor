"""
Book Engine streaming helpers
=============================

Thin wrapper around ``StreamBus`` that fixes ``source="book_engine"`` and
defines book-specific event metadata schemas.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.stream_bus import StreamBus

SOURCE = "book_engine"


# Stage names used across the pipeline
STAGE_IDEATION = "ideation"
STAGE_EXPLORATION = "exploration"  # SourceExplorer (Stage 2 prep)
STAGE_SYNTHESIS = "synthesis"  # SpineSynthesizer draft / revise
STAGE_CRITIQUE = "critique"  # SpineSynthesizer critique round
STAGE_OVERVIEW = "overview"  # Engine-injected Overview chapter
STAGE_SPINE = "spine"  # Outer wrapper for the spine stage
STAGE_PAGE_PLAN = "page_plan"
STAGE_COMPILATION = "compilation"
STAGE_BLOCK = "block"
STAGE_INTERACTION = "interaction"


class BookStream:
    """High-level helpers around a ``StreamBus`` for the BookEngine."""

    def __init__(self, bus: StreamBus) -> None:
        self.bus = bus

    @asynccontextmanager
    async def stage(self, name: str, metadata: dict[str, Any] | None = None):
        async with self.bus.stage(name, source=SOURCE, metadata=metadata or {}):
            yield

    async def content(
        self,
        text: str,
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.bus.content(text, source=SOURCE, stage=stage, metadata=metadata)

    async def thinking(
        self,
        text: str,
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.bus.thinking(text, source=SOURCE, stage=stage, metadata=metadata)

    async def progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0,
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.bus.progress(
            message,
            current=current,
            total=total,
            source=SOURCE,
            stage=stage,
            metadata=metadata,
        )

    async def result(self, data: dict[str, Any], metadata: dict[str, Any] | None = None) -> None:
        await self.bus.result(data, source=SOURCE, metadata=metadata)

    async def error(
        self,
        message: str,
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.bus.error(message, source=SOURCE, stage=stage, metadata=metadata)

    async def emit(self, event_type: StreamEventType, **kwargs: Any) -> None:
        kwargs.setdefault("source", SOURCE)
        await self.bus.emit(StreamEvent(type=event_type, **kwargs))

    # ── Book-specific events ────────────────────────────────────────────

    async def book_event(
        self,
        kind: str,
        data: dict[str, Any],
        stage: str = "",
    ) -> None:
        """Emit a custom 'book' progress event using the PROGRESS channel.

        Frontend distinguishes by ``metadata.kind``::

            kind ∈ {
              "proposal_ready", "spine_ready", "page_planned",
              "block_ready", "block_error", "page_ready",
              "compilation_complete", ...
            }
        """
        await self.bus.emit(
            StreamEvent(
                type=StreamEventType.PROGRESS,
                source=SOURCE,
                stage=stage,
                content=kind,
                metadata={"kind": kind, **data},
            )
        )


__all__ = [
    "BookStream",
    "SOURCE",
    "STAGE_IDEATION",
    "STAGE_EXPLORATION",
    "STAGE_SYNTHESIS",
    "STAGE_CRITIQUE",
    "STAGE_OVERVIEW",
    "STAGE_SPINE",
    "STAGE_PAGE_PLAN",
    "STAGE_COMPILATION",
    "STAGE_BLOCK",
    "STAGE_INTERACTION",
]
