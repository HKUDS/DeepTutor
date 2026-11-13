"""A transport EOF is not a Responses API completion event."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest

from deeptutor.services.llm.provider_core.openai_responses.parsing import (
    consume_sdk_stream,
    consume_sse,
)


def sdk_object(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: sdk_object(item) for key, item in value.items()})
    if isinstance(value, list):
        return [sdk_object(item) for item in value]
    return value


class SSEStream:
    def __init__(self, events):
        self.events = events

    async def aiter_lines(self):
        for event in self.events:
            yield "data: " + json.dumps(event)
            yield ""
        # Even this wire sentinel cannot replace response.completed/incomplete.
        yield "data: [DONE]"
        yield ""


async def consume(consumer, events, **kwargs):
    if consumer == "sse":
        return await consume_sse(SSEStream(events), **kwargs)

    async def stream():
        for event in events:
            yield sdk_object(event)

    return await consume_sdk_stream(stream(), **kwargs)


TOOL_DONE = {
    "type": "response.output_item.done",
    "item": {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "write_note",
        "arguments": '{"content":"partial"}',
    },
}


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sse", "sdk"])
@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "response.output_text.delta", "delta": "half an answer"}],
        [{"type": "response.reasoning_text.delta", "delta": "still thinking"}],
        [TOOL_DONE],
    ],
)
async def test_eof_without_response_terminal_event_raises(consumer, events):
    with pytest.raises(RuntimeError, match="without a terminal response event"):
        await consume(consumer, events)


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sse", "sdk"])
@pytest.mark.parametrize(
    ("terminal", "reason", "expected"),
    [
        ("completed", None, "stop"),
        ("incomplete", "max_output_tokens", "length"),
        ("incomplete", "content_filter", "content_filter"),
    ],
)
async def test_terminal_event_retains_finish_reason_and_usage(consumer, terminal, reason, expected):
    provider_events = []
    response = {"status": terminal, "usage": {"input_tokens": 7, "output_tokens": 3}}
    if reason:
        response["incomplete_details"] = {"reason": reason}
    result = await consume(
        consumer,
        [
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response." + terminal, "response": response},
        ],
        on_provider_event=lambda kind, payload: provider_events.append((kind, payload)),
    )
    assert result[:3] == ("answer", [], expected)
    assert provider_events == [
        ("usage", {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer", ["sse", "sdk"])
async def test_partial_deltas_are_visible_but_never_returned_as_a_completed_call(consumer):
    seen = []

    async def on_content(text):
        seen.append(text)

    with pytest.raises(RuntimeError, match="without a terminal response event"):
        await consume(
            consumer,
            [
                {"type": "response.output_text.delta", "delta": "partial"},
                TOOL_DONE,
            ],
            on_content_delta=on_content,
        )
    assert seen == ["partial"]


@pytest.mark.asyncio
async def test_truncated_sdk_response_cannot_dispatch_tools_or_emit_a_successful_finish():
    from deeptutor.runtime.agentic.client import LLMProviderError, _ProviderOpenAIAdapter
    from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider

    requests = []
    events = [{"type": "response.output_text.delta", "delta": "partial"}, TOOL_DONE]

    async def handler(request):
        requests.append(request)
        wire = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=wire)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = openai.AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/v1",
            http_client=http_client,
            max_retries=0,
        )
        with patch(
            "deeptutor.services.llm.provider_core.openai_compat_provider.AsyncOpenAI",
            return_value=client,
        ):
            provider = OpenAICompatProvider(
                api_key="fixture",
                api_base="https://fixture.invalid/v1",
                default_model="fixture",
                wire_api="responses",
            )
        stream = await _ProviderOpenAIAdapter(provider).chat.completions.create(
            model="fixture", messages=[{"role": "user", "content": "hello"}], stream=True
        )
        seen = []
        with pytest.raises(LLMProviderError, match="without a terminal response event"):
            async for chunk in stream:
                seen.append(chunk)
        assert len(requests) == 1
        assert [chunk.choices[0].delta.content for chunk in seen] == ["partial"]
        assert not any(chunk.choices[0].finish_reason for chunk in seen)
        assert not any(chunk.choices[0].delta.tool_calls for chunk in seen)
