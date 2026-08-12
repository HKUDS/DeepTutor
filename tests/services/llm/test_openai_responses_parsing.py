"""Regression tests for OpenAI Responses API stream parsing."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    consume_sdk_stream,
    consume_sse,
)


class _SSEFixture:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    async def aiter_lines(self):
        for event in self._events:
            yield f"data: {json.dumps(event)}"
            yield ""


async def _sdk_events(events):
    for event in events:
        yield event


@pytest.mark.asyncio
async def test_sse_arguments_can_be_correlated_by_item_id() -> None:
    response = _SSEFixture(
        [
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "delta": '{"topic":',
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "arguments": '{"topic":"algebra"}',
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "lookup",
                },
            },
        ]
    )

    _, tool_calls, _ = await consume_sse(response)  # type: ignore[arg-type]

    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_1|fc_1"
    assert tool_calls[0].arguments == {"topic": "algebra"}


@pytest.mark.asyncio
async def test_sdk_arguments_can_be_correlated_by_item_id() -> None:
    function_call = SimpleNamespace(
        type="function_call",
        id="fc_1",
        call_id="call_1",
        name="lookup",
        arguments="",
    )
    events = [
        SimpleNamespace(type="response.output_item.added", item=function_call),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            item_id="fc_1",
            delta='{"topic":',
        ),
        SimpleNamespace(
            type="response.function_call_arguments.done",
            item_id="fc_1",
            arguments='{"topic":"geometry"}',
        ),
        SimpleNamespace(type="response.output_item.done", item=function_call),
    ]

    _, tool_calls, _, _, _ = await consume_sdk_stream(_sdk_events(events))

    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_1|fc_1"
    assert tool_calls[0].arguments == {"topic": "geometry"}
