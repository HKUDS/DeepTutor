"""Tests for StreamBus async event fan-out."""

from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


# ---------------------------------------------------------------------------
# Basic emit / subscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_subscriber_receives_events() -> None:
    bus = StreamBus()

    collected: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            collected.append(event)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)  # let consumer register

    await bus.content("hello", source="test")
    await bus.content("world", source="test")
    await bus.close()
    await asyncio.wait_for(task, timeout=2.0)

    assert len(collected) == 2
    assert collected[0].content == "hello"
    assert collected[1].content == "world"


@pytest.mark.asyncio
async def test_fan_out_to_multiple_subscribers() -> None:
    bus = StreamBus()

    results_a: list[str] = []
    results_b: list[str] = []

    async def _consume(target: list[str]) -> None:
        async for event in bus.subscribe():
            target.append(event.content)

    task_a = asyncio.create_task(_consume(results_a))
    task_b = asyncio.create_task(_consume(results_b))
    await asyncio.sleep(0)

    await bus.content("ping", source="test")
    await bus.close()

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2.0)

    assert results_a == ["ping"]
    assert results_b == ["ping"]


@pytest.mark.asyncio
async def test_emit_after_close_is_ignored() -> None:
    bus = StreamBus()
    await bus.content("before", source="test")
    await bus.close()
    await bus.content("after", source="test")

    assert len(bus._history) == 1
    assert bus._history[0].content == "before"


# ---------------------------------------------------------------------------
# History replay for late subscribers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_after_close_returns_history_without_hanging() -> None:
    """Regression: subscribe() after close() must not block forever."""
    bus = StreamBus()
    await bus.content("msg", source="test")
    await bus.close()

    collected: list[str] = []
    async for event in bus.subscribe():
        collected.append(event.content)

    assert collected == ["msg"]


@pytest.mark.asyncio
async def test_late_subscriber_receives_history() -> None:
    bus = StreamBus()
    await bus.content("early", source="test")

    collected: list[str] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            collected.append(event.content)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await bus.close()
    await asyncio.wait_for(task, timeout=2.0)

    assert "early" in collected


# ---------------------------------------------------------------------------
# Convenience helpers (sync-style, no subscriber needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_context_manager_emits_start_and_end() -> None:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)

    async with bus.stage("planning", source="solver"):
        await bus.content("step 1", source="solver", stage="planning")

    await bus.close()
    await asyncio.wait_for(task, timeout=2.0)

    types = [e.type for e in events]
    assert types[0] == StreamEventType.STAGE_START
    assert types[-1] == StreamEventType.STAGE_END
    assert events[0].stage == "planning"
    assert events[0].source == "solver"


@pytest.mark.asyncio
async def test_thinking_helper() -> None:
    bus = StreamBus()
    await bus.thinking("hmm", source="reason")
    assert bus._history[0].type == StreamEventType.THINKING
    assert bus._history[0].content == "hmm"


@pytest.mark.asyncio
async def test_observation_helper() -> None:
    bus = StreamBus()
    await bus.observation("noted", source="tool")
    assert bus._history[0].type == StreamEventType.OBSERVATION


@pytest.mark.asyncio
async def test_tool_call_and_result_helpers() -> None:
    bus = StreamBus()
    await bus.tool_call("web_search", {"query": "AI"}, source="chat")
    await bus.tool_result("web_search", "results here", source="chat")

    assert bus._history[0].type == StreamEventType.TOOL_CALL
    assert bus._history[0].metadata["args"] == {"query": "AI"}
    assert bus._history[1].type == StreamEventType.TOOL_RESULT
    assert bus._history[1].metadata["tool"] == "web_search"


@pytest.mark.asyncio
async def test_progress_helper() -> None:
    bus = StreamBus()
    await bus.progress("indexing", current=3, total=10, source="rag")

    event = bus._history[0]
    assert event.type == StreamEventType.PROGRESS
    assert event.metadata["current"] == 3
    assert event.metadata["total"] == 10


@pytest.mark.asyncio
async def test_sources_helper() -> None:
    bus = StreamBus()
    await bus.sources([{"url": "https://example.com"}], source="rag")

    event = bus._history[0]
    assert event.type == StreamEventType.SOURCES
    assert event.metadata["sources"] == [{"url": "https://example.com"}]


@pytest.mark.asyncio
async def test_result_helper() -> None:
    bus = StreamBus()
    await bus.result({"answer": "42"}, source="solver")

    event = bus._history[0]
    assert event.type == StreamEventType.RESULT
    assert event.metadata["answer"] == "42"


@pytest.mark.asyncio
async def test_error_helper() -> None:
    bus = StreamBus()
    await bus.error("something went wrong", source="chat")

    event = bus._history[0]
    assert event.type == StreamEventType.ERROR
    assert event.content == "something went wrong"


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


def test_event_to_json_roundtrip() -> None:
    event = StreamEvent(
        type=StreamEventType.CONTENT,
        source="test",
        stage="responding",
        content="Hello",
    )
    serialized = StreamBus.event_to_json(event)
    parsed = json.loads(serialized)

    assert parsed["type"] == "content"
    assert parsed["source"] == "test"
    assert parsed["content"] == "Hello"
    assert isinstance(parsed["timestamp"], float)
