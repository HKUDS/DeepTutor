from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.agentic.labeled_step import run_labeled_step
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus


def _chunk(content: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=None,
            )
        ],
        usage=None,
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ToolRejectingClient:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._chunks = chunks

        class _Completions:
            def __init__(self, parent: _ToolRejectingClient) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any):
                self.parent.calls.append(dict(kwargs))
                if kwargs.get("tools"):
                    raise RuntimeError("Provider error: tools is not supported for this model")
                return _async_stream(self.parent._chunks)

        class _Chat:
            def __init__(self, parent: _ToolRejectingClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


async def _collect_events(bus: StreamBus, fn) -> tuple[list[Any], Any]:
    events: list[Any] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        result = await fn()
    finally:
        await bus.close()
        await consumer
    return events, result


@pytest.mark.asyncio
async def test_labeled_step_retries_without_tools_on_provider_schema_error() -> None:
    client = _ToolRejectingClient([_chunk("``FINISH``\nOK")])
    bus = StreamBus()

    async def _run():
        return await run_labeled_step(
            client=client,
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "hi"}],
            completion_kwargs={},
            tool_schemas=[
                {
                    "type": "function",
                    "function": {
                        "name": "ask_user",
                        "description": "ask",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            allowed_labels=("FINISH", "TOOL", "THINK", "PAUSE"),
            final_labels=frozenset({"FINISH"}),
            tool_label="TOOL",
            stream=bus,
            source="chat",
            stage="responding",
            iter_meta={"label": "Reasoning", "trace_id": "iter-1"},
        )

    events, result = await _collect_events(bus, _run)

    assert result.label == "FINISH"
    assert result.text == "OK"
    assert client.calls[0]["tools"]
    assert "tools" not in client.calls[1]
    warnings = [
        event
        for event in events
        if event.type == StreamEventType.PROGRESS
        and (event.metadata or {}).get("trace_kind") == "warning"
    ]
    assert warnings
