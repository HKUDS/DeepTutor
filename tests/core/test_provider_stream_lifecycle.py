"""Terminal reads and explicit close on the shared provider adapter."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.runtime.agentic.client import LLMProviderError, _ProviderOpenAIAdapter
from deeptutor.services.llm.provider_core.base import LLMResponse


async def make_stream(provider):
    return await _ProviderOpenAIAdapter(provider).chat.completions.create(
        model="fixture", messages=[{"role": "user", "content": "hello"}], stream=True
    )


async def assert_exhausted(stream):
    for _ in range(2):
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(stream), timeout=0.5)


@pytest.mark.asyncio
async def test_exhaustion_is_sticky_after_a_successful_response():
    class Provider:
        async def chat_stream(self, **kwargs):
            return LLMResponse(content="done", usage={"total_tokens": 3})

    stream = await make_stream(Provider())
    chunks = [chunk async for chunk in stream]
    assert chunks[-1].usage == {"total_tokens": 3}
    await assert_exhausted(stream)


@pytest.mark.asyncio
async def test_error_is_reported_once_then_iteration_stays_exhausted():
    class Provider:
        async def chat_stream(self, **kwargs):
            return LLMResponse(content="fixture failure", finish_reason="error")

    stream = await make_stream(Provider())
    with pytest.raises(LLMProviderError, match="fixture failure"):
        await anext(stream)
    await assert_exhausted(stream)


@pytest.mark.asyncio
async def test_close_before_first_read_never_starts_the_provider():
    class Provider:
        calls = 0

        async def chat_stream(self, **kwargs):
            self.calls += 1
            return LLMResponse(content="must not run")

    provider = Provider()
    stream = await make_stream(provider)
    await stream.close()
    await stream.close()
    await assert_exhausted(aiter(stream))
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_close_immediately_after_iteration_starts_does_not_need_producer_finally():
    class Provider:
        async def chat_stream(self, **kwargs):
            raise AssertionError("Task must be cancelled before it starts")

    stream = aiter(await make_stream(Provider()))
    await stream.close()
    await assert_exhausted(stream)


@pytest.mark.asyncio
async def test_close_wakes_pending_readers_and_cancels_the_producer():
    started, stopped = asyncio.Event(), asyncio.Event()

    class Provider:
        async def chat_stream(self, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    stream = await make_stream(Provider())
    readers = [asyncio.create_task(anext(stream)) for _ in range(2)]
    await asyncio.wait_for(started.wait(), timeout=1)
    try:
        await stream.close()
        results = await asyncio.wait_for(
            asyncio.gather(*readers, return_exceptions=True), timeout=0.5
        )
        assert all(isinstance(result, StopAsyncIteration) for result in results)
        assert stopped.is_set()
        await assert_exhausted(stream)
    finally:
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_close_does_not_cancel_provider_cleanup_twice():
    started, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))

    class Provider:
        async def chat_stream(self, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                cleaned.set()

    stream = aiter(await make_stream(Provider()))
    await asyncio.wait_for(started.wait(), timeout=1)
    first = asyncio.create_task(stream.close())
    await asyncio.wait_for(cleaning.wait(), timeout=1)
    second = asyncio.create_task(stream.close())
    try:
        # Let the second close enter while the first awaits provider cleanup.
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=1)
        assert cleaned.is_set()
        await assert_exhausted(stream)
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
