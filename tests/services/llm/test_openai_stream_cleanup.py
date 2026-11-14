"""Release the SDK-owned HTTP response on every provider stream exit."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest

from deeptutor.services.llm.provider_core.azure_openai_provider import AzureOpenAIProvider
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider


class WireBody(httpx.AsyncByteStream):
    def __init__(self, events, *, fail_read=False):
        self.events = events
        self.fail_read = fail_read
        self.closed = False
        self.reading = asyncio.Event()

    async def __aiter__(self):
        for event in self.events:
            yield ("data: " + json.dumps(event) + "\n\n").encode()
        self.reading.set()
        if self.fail_read:
            raise httpx.ReadError("fixture disconnect")
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def make_provider(kind, client):
    # Inject the real SDK client without creating a second HTTP client.
    if kind == "azure":
        with patch(
            "deeptutor.services.llm.provider_core.azure_openai_provider.AsyncOpenAI",
            return_value=client,
        ):
            return AzureOpenAIProvider(
                api_key="fixture", api_base="https://fixture.invalid", default_model="fixture"
            )
    with patch(
        "deeptutor.services.llm.provider_core.openai_compat_provider.AsyncOpenAI",
        return_value=client,
    ):
        return OpenAICompatProvider(
            api_key="fixture",
            api_base="https://fixture.invalid/v1",
            default_model="fixture",
            provider_name="custom",
            wire_api="responses" if kind == "responses" else "chat_completions",
        )


def content_event(kind):
    if kind == "chat":
        return {
            "id": "chat_fixture",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "fixture",
            "choices": [{"index": 0, "delta": {"content": "partial"}, "finish_reason": None}],
        }
    return {
        "type": "response.output_text.delta",
        "delta": "partial",
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
        "sequence_number": 1,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses", "azure"])
@pytest.mark.parametrize(
    "exit_kind", ["callback_error", "cancel_callback", "cancel_read", "read_error"]
)
async def test_actual_sdk_response_is_closed_on_early_exit(kind, exit_kind):
    body = WireBody([content_event(kind)], fail_read=exit_kind == "read_error")

    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = openai.AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/v1",
            http_client=http_client,
            max_retries=0,
        )
        provider = make_provider(kind, client)
        arrived = asyncio.Event()

        async def on_content(text):
            assert text == "partial"
            arrived.set()
            if exit_kind == "callback_error":
                raise ValueError("fixture callback failed")
            if exit_kind == "cancel_callback":
                await asyncio.Event().wait()

        task = asyncio.create_task(
            provider.chat_stream(
                messages=[{"role": "user", "content": "hello"}], on_content_delta=on_content
            )
        )
        try:
            if exit_kind.startswith("cancel"):
                event = arrived if exit_kind == "cancel_callback" else body.reading
                await asyncio.wait_for(event.wait(), timeout=2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                result = await asyncio.wait_for(task, timeout=2)
                assert result.finish_reason == "error"
                assert arrived.is_set()
            # Assert before closing the shared client or allowing GC to clean up.
            assert body.closed
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses", "azure"])
async def test_success_closes_stream_once_and_keeps_result(kind):
    events = [content_event(kind)]
    if kind != "chat":
        events.append(
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                },
            }
        )
    else:
        events.append(
            {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            }
        )

    def namespace(value):
        if isinstance(value, dict):
            return SimpleNamespace(**{key: namespace(item) for key, item in value.items()})
        if isinstance(value, list):
            return [namespace(item) for item in value]
        return value

    class Stream:
        close = AsyncMock()

        async def __aiter__(self):
            for event in events:
                if kind == "chat":
                    yield openai.types.chat.ChatCompletionChunk.model_validate(
                        {
                            "id": "chat_fixture",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "fixture",
                            **event,
                        }
                    )
                else:
                    yield namespace(event)

    stream = Stream()
    create = AsyncMock(return_value=stream)
    provider = make_provider(
        kind,
        SimpleNamespace(
            responses=SimpleNamespace(create=create),
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        ),
    )
    result = await provider.chat_stream(messages=[{"role": "user", "content": "hello"}])
    assert result.content == "partial"
    assert result.finish_reason == "stop"
    assert result.usage["total_tokens"] == 3
    stream.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses", "azure"])
async def test_timeout_closes_stream_before_returning_the_stall_error(kind):
    class Stream:
        close = AsyncMock()

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise asyncio.TimeoutError

    stream = Stream()
    create = AsyncMock(return_value=stream)
    provider = make_provider(
        kind,
        SimpleNamespace(
            responses=SimpleNamespace(create=create),
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        ),
    )
    result = await provider.chat_stream(messages=[])
    assert result.finish_reason == "error"
    assert "stream stalled" in result.content
    stream.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_cleanup_failure_preserves_the_original_error_or_cancellation(cancel):
    arrived = asyncio.Event()

    class Stream:
        close = AsyncMock(side_effect=LookupError("fixture cleanup failure"))

        async def __aiter__(self):
            yield SimpleNamespace(type="response.output_text.delta", delta="partial")

    stream = Stream()
    provider = make_provider(
        "azure", SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=stream)))
    )

    async def on_content(text):
        arrived.set()
        if cancel:
            await asyncio.Event().wait()
        raise ValueError("original callback failure")

    task = asyncio.create_task(provider.chat_stream(messages=[], on_content_delta=on_content))
    try:
        await asyncio.wait_for(arrived.wait(), timeout=1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.finish_reason == "error"
            assert "original callback failure" in result.content
        stream.close.assert_awaited_once()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
