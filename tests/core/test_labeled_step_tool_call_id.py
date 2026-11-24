"""A tool call streamed without an id must still get a non-empty id.

Some OpenAI-compatible gateways stream a tool call's ``function.name`` and
``function.arguments`` but never an ``id`` delta. The id is needed to correlate
the follow-up ``role=tool`` result, so ``run_labeled_step`` must apply the same
positional fallback its sibling accumulator consumers do.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime.agentic.labeled_step import run_labeled_step
from deeptutor.runtime.stream_bus import StreamBus


def _tool_chunk() -> SimpleNamespace:
    # A tool-call delta with name + arguments but NO id.
    tc = SimpleNamespace(
        index=0,
        function=SimpleNamespace(name="ask_user", arguments='{"q": "hi"}'),
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, tool_calls=[tc]),
                finish_reason="tool_calls",
            )
        ],
        usage=None,
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _Client:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

        class _Completions:
            def __init__(self, parent: _Client) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any):
                return _async_stream(self.parent._chunks)

        class _Chat:
            def __init__(self, parent: _Client) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


async def _drain(bus: StreamBus, fn):
    async def _consume() -> None:
        async for _ in bus.subscribe():
            pass

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        result = await fn()
    finally:
        await bus.close()
        await consumer
    return result


@pytest.mark.asyncio
async def test_tool_call_without_id_gets_a_positional_id() -> None:
    client = _Client([_tool_chunk()])
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

    result = await _drain(bus, _run)

    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call["name"] == "ask_user"
    # The id must be non-empty so the assistant/tool messages can be paired and
    # the provider's non-empty-id schema is satisfied.
    assert call["id"]
