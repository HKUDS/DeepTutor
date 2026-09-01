"""Regression tests for OpenAI Responses API stream parsing."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    consume_sdk_stream,
    consume_sse,
    parse_response_output,
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


class _SDKItem(SimpleNamespace):
    def model_dump(self):
        return dict(vars(self))


def test_nonstream_prefers_reasoning_text_and_preserves_complete_output_order() -> None:
    output = [
        {
            "type": "reasoning",
            "id": "rs_1",
            "content": [{"type": "reasoning_text", "text": "raw reasoning"}],
            "summary": [{"type": "summary_text", "text": "summary fallback"}],
            "encrypted_content": "encrypted-token",
            "status": "completed",
        },
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "phase": "final_answer",
            "content": [{"type": "output_text", "text": "visible answer"}],
            "status": "completed",
        },
    ]

    result = parse_response_output(
        {
            "output": output,
            "status": "completed",
            "usage": {"input_tokens": 3, "output_tokens": 5},
        }
    )

    assert result.content == "visible answer"
    assert result.reasoning_content == "raw reasoning"
    assert result.provider_specific_fields["native_output_items"] == output


def test_nonstream_uses_summary_only_when_raw_reasoning_is_absent() -> None:
    result = parse_response_output(
        {
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [{"type": "summary_text", "text": "summary only"}],
                }
            ],
            "status": "completed",
        }
    )

    assert result.reasoning_content == "summary only"


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
async def test_sdk_deepseek_reasoning_text_and_function_call_are_forwarded_in_order() -> None:
    reasoning_item = _SDKItem(
        type="reasoning",
        id="rs_1",
        content=[{"type": "reasoning_text", "text": "inspect then call"}],
        encrypted_content="encrypted-token",
        status="completed",
    )
    function_item = _SDKItem(
        type="function_call",
        id="fc_1",
        call_id="call_1",
        name="lookup",
        arguments='{"topic":"geometry"}',
        status="completed",
        caller="assistant",
    )
    events = [
        SimpleNamespace(type="response.reasoning_text.delta", delta="inspect "),
        SimpleNamespace(type="response.reasoning_text.delta", delta="then call"),
        SimpleNamespace(type="response.reasoning_text.done", text="inspect then call"),
        SimpleNamespace(type="response.output_item.done", item=reasoning_item),
        SimpleNamespace(type="response.output_item.added", item=function_item),
        SimpleNamespace(
            type="response.function_call_arguments.done",
            item_id="fc_1",
            arguments='{"topic":"geometry"}',
        ),
        SimpleNamespace(type="response.output_item.done", item=function_item),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", usage=None),
        ),
    ]
    reasoning_deltas: list[str] = []
    provider_events: list[tuple[str, dict]] = []

    _, tool_calls, _, _, reasoning = await consume_sdk_stream(
        _sdk_events(events),
        on_reasoning_delta=lambda text: _append_async(reasoning_deltas, text),
        on_provider_event=lambda kind, payload: provider_events.append((kind, payload)),
    )

    assert reasoning == "inspect then call"
    assert reasoning_deltas == ["inspect ", "then call"]
    assert tool_calls[0].arguments == {"topic": "geometry"}
    assert [payload for kind, payload in provider_events if kind == "output_item"] == [
        reasoning_item.model_dump(),
        function_item.model_dump(),
    ]


async def _append_async(values: list[str], value: str) -> None:
    values.append(value)


@pytest.mark.asyncio
async def test_sse_supports_reasoning_text_and_preserves_message_item() -> None:
    reasoning_item = {
        "type": "reasoning",
        "id": "rs_1",
        "content": [{"type": "reasoning_text", "text": "raw"}],
        "encrypted_content": "encrypted-token",
    }
    message_item = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "phase": "final_answer",
        "content": [{"type": "output_text", "text": "answer"}],
    }
    events = [
        {"type": "response.reasoning_text.delta", "delta": "raw"},
        {"type": "response.reasoning_text.done", "text": "raw"},
        {"type": "response.output_item.done", "item": reasoning_item},
        {"type": "response.output_text.delta", "delta": "answer"},
        {"type": "response.output_item.done", "item": message_item},
    ]
    reasoning_deltas: list[str] = []
    provider_events: list[tuple[str, dict]] = []

    content, _, _ = await consume_sse(
        _SSEFixture(events),
        on_reasoning_delta=lambda text: _append_async(reasoning_deltas, text),
        on_provider_event=lambda kind, payload: provider_events.append((kind, payload)),
    )

    assert content == "answer"
    assert reasoning_deltas == ["raw"]
    assert [payload for kind, payload in provider_events if kind == "output_item"] == [
        reasoning_item,
        message_item,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sse", "sdk"])
async def test_summary_reasoning_remains_supported(consumer: str) -> None:
    reasoning_deltas: list[str] = []
    if consumer == "sse":
        await consume_sse(
            _SSEFixture(
                [
                    {"type": "response.reasoning_summary_text.delta", "delta": "summary "},
                    {"type": "response.reasoning_summary_text.delta", "delta": "reasoning"},
                ]
            ),
            on_reasoning_delta=lambda text: _append_async(reasoning_deltas, text),
        )
        reasoning = "".join(reasoning_deltas)
    else:
        _, _, _, _, reasoning = await consume_sdk_stream(
            _sdk_events(
                [
                    SimpleNamespace(
                        type="response.reasoning_summary_text.delta", delta="summary "
                    ),
                    SimpleNamespace(
                        type="response.reasoning_summary_text.delta", delta="reasoning"
                    ),
                ]
            ),
            on_reasoning_delta=lambda text: _append_async(reasoning_deltas, text),
        )

    assert reasoning == "summary reasoning"
    assert reasoning_deltas == ["summary reasoning"]


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
