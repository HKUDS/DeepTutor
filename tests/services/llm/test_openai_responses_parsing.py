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


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sse", "sdk"])
async def test_argument_deltas_are_preserved_without_a_done_event(consumer: str) -> None:
    """Cover delta accumulation independently from the final replacement event."""
    item = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "lookup",
    }
    events = [
        {"type": "response.output_item.added", "item": item},
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "delta": '{"topic":',
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "delta": '"calculus"}',
        },
        {"type": "response.output_item.done", "item": item},
    ]

    if consumer == "sse":
        _, tool_calls, _ = await consume_sse(_SSEFixture(events))
    else:
        sdk_events = [
            SimpleNamespace(
                **{
                    **event,
                    "item": SimpleNamespace(**event["item"]),
                }
            )
            if "item" in event
            else SimpleNamespace(**event)
            for event in events
        ]
        _, tool_calls, _, _, _ = await consume_sdk_stream(_sdk_events(sdk_events))

    assert tool_calls[0].arguments == {"topic": "calculus"}


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sse", "sdk"])
async def test_response_failed_raises_the_provider_error(consumer: str) -> None:
    error = {"code": "server_error", "message": "The model failed to generate a response."}

    with pytest.raises(RuntimeError, match="server_error: The model failed"):
        if consumer == "sse":
            await consume_sse(
                _SSEFixture([{"type": "response.failed", "response": {"error": error}}])
            )
        else:
            event = SimpleNamespace(
                type="response.failed",
                response=SimpleNamespace(error=SimpleNamespace(**error)),
            )
            await consume_sdk_stream(_sdk_events([event]))


@pytest.mark.asyncio
async def test_sdk_top_level_error_event_raises() -> None:
    event = SimpleNamespace(type="error", code="rate_limit_exceeded", message="Try again later")

    with pytest.raises(RuntimeError, match="Try again later"):
        await consume_sdk_stream(_sdk_events([event]))


@pytest.mark.asyncio
async def test_a_call_without_an_item_id_does_not_inherit_another_calls_identity() -> None:
    """The placeholder item id is not an identity, and must never resolve one.

    A provider that omits ``item.id`` on function-call items makes every call
    carry the same stand-in. If that stand-in were registered as a lookup key,
    a ``done`` event for a call that was never announced would find the
    previous call's buffer — and the tool would be dispatched under the wrong
    name with the wrong arguments.
    """
    events = [
        {
            "type": "response.output_item.added",
            "item": {"type": "function_call", "call_id": "call_1", "name": "delete_kb"},
        },
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call_1",
            "arguments": '{"kb":"secret"}',
        },
        {
            "type": "response.output_item.done",
            "item": {"type": "function_call", "call_id": "call_1", "name": "delete_kb"},
        },
        # Never announced with an ``added`` event, and carries no item id.
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "call_id": "call_2",
                "name": "list_kb",
                "arguments": '{"scope":"mine"}',
            },
        },
    ]

    _, tool_calls, _ = await consume_sse(_SSEFixture(events))

    assert [(call.name, call.arguments) for call in tool_calls] == [
        ("delete_kb", {"kb": "secret"}),
        ("list_kb", {"scope": "mine"}),
    ]
