"""Scripted chat-loop event sequences for partner runtime tests.

A partner turn is a chat-loop run; these build the event streams a real
loop would emit so tests can assert on what the runner makes of them.
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.stream import StreamEvent, StreamEventType


def event(
    event_type: StreamEventType,
    *,
    content: str = "",
    source: str = "chat",
    metadata: dict[str, Any] | None = None,
) -> StreamEvent:
    return StreamEvent(type=event_type, source=source, content=content, metadata=metadata or {})


def narration_round(call_id: str, text: str) -> list[StreamEvent]:
    return [
        event(StreamEventType.CONTENT, content=text, metadata={"call_id": call_id}),
        event(
            StreamEventType.PROGRESS,
            metadata={
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_role": "narration",
                "call_id": call_id,
            },
        ),
    ]


def finish(text: str) -> list[StreamEvent]:
    return [
        event(StreamEventType.CONTENT, content=text, metadata={"call_id": "c-finish"}),
        event(StreamEventType.RESULT, metadata={"response": text}),
        event(StreamEventType.DONE),
    ]


def answer_visible_narration(call_id: str, text: str) -> list[StreamEvent]:
    return [
        event(StreamEventType.CONTENT, content=text, metadata={"call_id": call_id}),
        event(
            StreamEventType.PROGRESS,
            metadata={
                "trace_kind": "call_status",
                "call_state": "complete",
                "call_role": "narration",
                "answer_visible": True,
                "call_id": call_id,
            },
        ),
    ]
