"""Regression tests for OpenAI Responses streaming tool arguments."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import AsyncIterator

from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    consume_sdk_stream,
    consume_sse,
)


class _FakeResponse:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = events

    async def aiter_lines(self) -> AsyncIterator[str]:
        for event in self._events:
            yield "data: " + json.dumps(event, ensure_ascii=False)
            yield ""


class _FakeStream:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        for event in self._events:
            yield event


def test_tool_argument_deltas_addressed_by_item_id_are_preserved() -> None:
    arguments = json.dumps(
        {
            "mode": "edit",
            "notebook_id": "notebook-123",
            "record_id": "record-123",
        }
    )
    response = _FakeResponse(
        [
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "fc_123",
                    "call_id": "call_123",
                    "name": "write_note",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_123",
                "delta": arguments,
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_123",
                "arguments": arguments,
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc_123",
                    "call_id": "call_123",
                    "name": "write_note",
                    "arguments": "",
                },
            },
        ]
    )

    _content, tool_calls, _finish_reason = asyncio.run(consume_sse(response))

    assert tool_calls[0].arguments == json.loads(arguments)


def test_sdk_tool_argument_deltas_addressed_by_item_id_are_preserved() -> None:
    arguments = json.dumps(
        {
            "mode": "edit",
            "notebook_id": "notebook-123",
            "record_id": "record-123",
        }
    )
    item = SimpleNamespace(
        type="function_call",
        id="fc_123",
        call_id="call_123",
        name="write_note",
        arguments="",
    )
    stream = _FakeStream(
        [
            SimpleNamespace(type="response.output_item.added", item=item),
            SimpleNamespace(
                type="response.function_call_arguments.delta",
                item_id="fc_123",
                delta=arguments,
            ),
            SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="fc_123",
                arguments=arguments,
            ),
            SimpleNamespace(type="response.output_item.done", item=item),
        ]
    )

    _content, tool_calls, _finish_reason, _usage, _reasoning = asyncio.run(
        consume_sdk_stream(stream)
    )

    assert tool_calls[0].arguments == json.loads(arguments)
