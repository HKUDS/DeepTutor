"""Forward usage from SDK results the bridge already consumes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.sdk_bridge import _consume_messages

USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_read_input_tokens": 7,
    "cache_creation_input_tokens": 3,
}
EXPECTED = {
    "prompt_tokens": 20,
    "completion_tokens": 5,
    "total_tokens": 25,
    "cache_read_input_tokens": 7,
    "cache_creation_input_tokens": 3,
}


async def messages(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [False, True])
@pytest.mark.parametrize("as_dict", [False, True])
async def test_consumed_result_usage_survives_normal_and_error_completion(error, as_dict):
    result = {"type": "result", "result": "answer", "is_error": error, "usage": USAGE}
    if not as_dict:
        result = SimpleNamespace(**result)
    response = await _consume_messages(messages(result), on_content_delta=None)
    assert response.usage == EXPECTED
    assert response.finish_reason == ("error" if error else "stop")


@pytest.mark.asyncio
async def test_tool_handoff_retains_usage_from_the_existing_interrupt_drain():
    async def interrupt():
        pass

    tool = {
        "content": [
            {"type": "tool_use", "id": "call-1", "name": "mcp__deeptutor__lookup", "input": {}}
        ]
    }
    result = {"type": "result", "result": "interrupted", "usage": USAGE}
    response = await _consume_messages(
        messages(tool, result), on_content_delta=None, interrupt=interrupt
    )
    assert response.tool_calls[0].id == "call-1"
    assert response.usage == EXPECTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"other": 4},
        {"input_tokens": True},
        {"output_tokens": -1},
        {"input_tokens": "12"},
        {"input_tokens": 1.5},
    ],
)
async def test_absent_or_invalid_usage_stays_unknown(usage):
    response = await _consume_messages(
        messages({"type": "result", "result": "done", "usage": usage}), on_content_delta=None
    )
    assert response.content == "done"
    assert response.usage == {}


@pytest.mark.asyncio
async def test_repeated_final_snapshots_are_not_summed():
    result = {"type": "result", "result": "done", "usage": USAGE}
    response = await _consume_messages(messages(result, result), on_content_delta=None)
    assert response.usage == EXPECTED


@pytest.mark.asyncio
async def test_handoff_without_an_owned_drain_does_not_read_ahead_for_usage():
    async def stream():
        yield {
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "mcp__deeptutor__lookup", "input": {}}
            ]
        }
        raise AssertionError("Do not add an unowned read just to obtain accounting")

    response = await _consume_messages(stream(), on_content_delta=None)
    assert response.finish_reason == "tool_calls"
    assert response.usage == {}


@pytest.mark.asyncio
async def test_cancellation_during_interrupt_drain_propagates():
    async def interrupt():
        pass

    async def stream():
        yield {
            "content": [
                {"type": "tool_use", "id": "call-1", "name": "mcp__deeptutor__lookup", "input": {}}
            ]
        }
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _consume_messages(stream(), on_content_delta=None, interrupt=interrupt)


@pytest.mark.asyncio
async def test_usage_reaches_the_shared_openai_shaped_stream():
    from deeptutor.runtime.agentic.client import _ProviderOpenAIAdapter

    class Provider:
        async def chat_stream(self, **kwargs):
            return await _consume_messages(
                messages({"type": "result", "result": "answer", "usage": USAGE}),
                on_content_delta=kwargs.get("on_content_delta"),
            )

    client = _ProviderOpenAIAdapter(Provider())
    stream = await client.chat.completions.create(
        model="fixture", messages=[{"role": "user", "content": "question"}], stream=True
    )
    chunks = [chunk async for chunk in stream]
    reported = [chunk.usage for chunk in chunks if getattr(chunk, "usage", None)]
    assert len(reported) == 1
    assert reported[0] == EXPECTED
