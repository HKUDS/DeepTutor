"""Tests for the StreamBus async event channel."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


@pytest.mark.asyncio
async def test_emit_and_subscribe_receives_events() -> None:
    """Basic pub/sub: emitted events reach the subscriber."""
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="hello"))
    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="world"))
    await bus.close()
    await consumer

    assert len(events) == 2
    assert events[0].content == "hello"
    assert events[1].content == "world"


@pytest.mark.asyncio
async def test_multiple_subscribers_receive_all_events() -> None:
    """Fan-out: every subscriber gets every event."""
    bus = StreamBus()
    results_a: list[StreamEvent] = []
    results_b: list[StreamEvent] = []

    async def _consume(target: list[StreamEvent]) -> None:
        async for event in bus.subscribe():
            target.append(event)

    task_a = asyncio.create_task(_consume(results_a))
    task_b = asyncio.create_task(_consume(results_b))
    await asyncio.sleep(0)

    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="msg"))
    await bus.close()
    await task_a
    await task_b

    assert len(results_a) == 1
    assert len(results_b) == 1
    assert results_a[0].content == results_b[0].content == "msg"


@pytest.mark.asyncio
async def test_close_terminates_subscriber() -> None:
    """Closing the bus causes the async-for loop to exit."""
    bus = StreamBus()
    finished = asyncio.Event()

    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass
        finished.set()

    asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await bus.close()
    await asyncio.wait_for(finished.wait(), timeout=1.0)

    assert finished.is_set()


@pytest.mark.asyncio
async def test_stage_context_manager_emits_start_and_end() -> None:
    """The `stage()` context manager emits STAGE_START and STAGE_END."""
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    async with bus.stage("planning", source="test"):
        pass

    await bus.close()
    await consumer

    assert events[0].type == StreamEventType.STAGE_START
    assert events[0].stage == "planning"
    assert events[0].source == "test"
    assert events[1].type == StreamEventType.STAGE_END
    assert events[1].stage == "planning"


@pytest.mark.asyncio
async def test_content_helper_emits_correct_event() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.content("answer text", source="chat", stage="responding")
    await bus.close()
    await consumer

    assert len(events) == 1
    assert events[0].type == StreamEventType.CONTENT
    assert events[0].content == "answer text"
    assert events[0].source == "chat"
    assert events[0].stage == "responding"


@pytest.mark.asyncio
async def test_thinking_helper(stream_bus: StreamBus) -> None:
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in stream_bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await stream_bus.thinking("reasoning step", source="solver")
    await stream_bus.close()
    await consumer

    assert events[0].type == StreamEventType.THINKING
    assert events[0].content == "reasoning step"


@pytest.mark.asyncio
async def test_observation_helper(stream_bus: StreamBus) -> None:
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in stream_bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await stream_bus.observation("observed result", source="solver")
    await stream_bus.close()
    await consumer

    assert events[0].type == StreamEventType.OBSERVATION
    assert events[0].content == "observed result"


@pytest.mark.asyncio
async def test_tool_call_and_tool_result_helpers() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.tool_call("rag", {"query": "hello"}, source="chat", metadata={"extra": 1})
    await bus.tool_result("rag", "found it", source="chat")
    await bus.close()
    await consumer

    assert events[0].type == StreamEventType.TOOL_CALL
    assert events[0].content == "rag"
    assert events[0].metadata["args"] == {"query": "hello"}
    assert events[0].metadata["extra"] == 1

    assert events[1].type == StreamEventType.TOOL_RESULT
    assert events[1].content == "found it"
    assert events[1].metadata["tool"] == "rag"


@pytest.mark.asyncio
async def test_progress_helper() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.progress("step 2/3", current=2, total=3, source="solver")
    await bus.close()
    await consumer

    assert events[0].type == StreamEventType.PROGRESS
    assert events[0].content == "step 2/3"
    assert events[0].metadata["current"] == 2
    assert events[0].metadata["total"] == 3


@pytest.mark.asyncio
async def test_sources_helper() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    src_list: list[dict[str, Any]] = [{"type": "rag", "content": "grounding"}]
    await bus.sources(src_list, source="chat")
    await bus.close()
    await consumer

    assert events[0].type == StreamEventType.SOURCES
    assert events[0].metadata["sources"] == src_list


@pytest.mark.asyncio
async def test_error_helper() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.error("something broke", source="solver", stage="planning")
    await bus.close()
    await consumer

    assert events[0].type == StreamEventType.ERROR
    assert events[0].content == "something broke"


@pytest.mark.asyncio
async def test_result_helper() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.result({"response": "done"}, source="solver")
    await bus.close()
    await consumer

    assert events[0].type == StreamEventType.RESULT
    assert events[0].metadata["response"] == "done"


def test_event_to_json_roundtrip() -> None:
    """event_to_json produces valid JSON that round-trips the key fields."""
    event = StreamEvent(
        type=StreamEventType.CONTENT,
        source="chat",
        stage="responding",
        content="test text",
        metadata={"key": "val"},
    )
    json_str = StreamBus.event_to_json(event)
    parsed = json.loads(json_str)

    assert parsed["type"] == "content"
    assert parsed["source"] == "chat"
    assert parsed["content"] == "test text"
    assert parsed["metadata"]["key"] == "val"


@pytest.mark.asyncio
async def test_emit_after_close_is_ignored() -> None:
    """Emitting after close() should silently no-op."""
    bus = StreamBus()
    await bus.close()

    # Should not raise
    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="late"))

    # History should not include the late event
    assert len(bus._history) == 0


@pytest.mark.asyncio
async def test_history_replay_for_late_subscriber() -> None:
    """A subscriber joining after events are emitted still gets the history."""
    bus = StreamBus()

    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="early"))

    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    await bus.emit(StreamEvent(type=StreamEventType.CONTENT, content="later"))
    await bus.close()
    await consumer

    contents = [e.content for e in events]
    assert "early" in contents
    assert "later" in contents


@pytest.mark.asyncio
async def test_double_close_is_safe(stream_bus: StreamBus) -> None:
    """Closing the stream bus multiple times should not raise an error."""
    await stream_bus.close()
    await stream_bus.close()
    assert stream_bus._closed is True


@pytest.mark.asyncio
async def test_stage_with_metadata(stream_bus: StreamBus) -> None:
    """Stage metadata should be passed correctly to start and end events."""
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in stream_bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    async with stream_bus.stage("test_stage", metadata={"key": "val"}):
        pass

    await stream_bus.close()
    await consumer

    assert events[0].metadata["key"] == "val"
    assert events[1].metadata["key"] == "val"


@pytest.mark.asyncio
async def test_concurrent_emit_and_subscribe(stream_bus: StreamBus) -> None:
    """Stress test for multiple producers emitting simultaneously to multiple consumers."""
    results_a: list[StreamEvent] = []
    results_b: list[StreamEvent] = []

    async def _consume(target: list[StreamEvent]) -> None:
        async for event in stream_bus.subscribe():
            target.append(event)

    task_a = asyncio.create_task(_consume(results_a))
    task_b = asyncio.create_task(_consume(results_b))
    
    async def _produce(val: str) -> None:
        await stream_bus.content(val)
        
    await asyncio.sleep(0)
    await asyncio.gather(
        _produce("first"),
        _produce("second"),
        _produce("third"),
    )
    
    await stream_bus.close()
    await task_a
    await task_b

    assert len(results_a) == 3
    assert len(results_b) == 3

