from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from deeptutor.services.singleflight_cache import AsyncSingleFlightTTLCache


@dataclass(frozen=True)
class Value:
    text: str
    created_at: float


def cache(clock: list[float], *, limit: int = 2) -> AsyncSingleFlightTTLCache[str, Value]:
    return AsyncSingleFlightTTLCache(
        limit=limit,
        ttl_seconds=10,
        value_timestamp=lambda value: value.created_at,
        now=lambda: clock[0],
    )


def test_recall_expires_values_and_evicts_oldest_insertions() -> None:
    clock = [5.0]
    subject = cache(clock)
    subject.remember("a", Value("a", 5.0))
    subject.remember("b", Value("b", 5.0))
    subject.remember("c", Value("c", 5.0))

    assert list(subject.values) == ["b", "c"]
    assert subject.recall("b") == Value("b", 5.0)

    clock[0] = 16.0
    assert subject.recall("b") is None
    assert "b" not in subject.values


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_producer_and_cache_usable_result() -> None:
    clock = [1.0]
    subject = cache(clock)
    started = 0
    release = asyncio.Event()

    async def produce() -> Value:
        nonlocal started
        started += 1
        await release.wait()
        return Value("ready", clock[0])

    first = asyncio.create_task(subject.get_or_create("key", produce))
    second = asyncio.create_task(subject.get_or_create("key", produce))
    await asyncio.sleep(0)
    release.set()

    assert await first == await second == Value("ready", 1.0)
    assert started == 1
    assert subject.recall("key") == Value("ready", 1.0)
    assert subject.inflight == {}


@pytest.mark.asyncio
async def test_non_cacheable_results_and_failures_leave_no_state() -> None:
    subject = cache([1.0])

    value = await subject.get_or_create(
        "empty",
        lambda: asyncio.sleep(0, result=Value("", 1.0)),
        cache_when=lambda item: bool(item.text),
    )
    assert value.text == ""
    assert subject.values == {}

    async def fail() -> Value:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await subject.get_or_create("failed", fail)
    assert subject.inflight == {}


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_other_hint_requests() -> None:
    subject = cache([1.0])
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def produce() -> Value:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return Value("shared hint", 1.0)

    first = asyncio.create_task(subject.get_or_create("key", produce))
    await started.wait()
    second = asyncio.create_task(subject.get_or_create("key", produce))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    third = asyncio.create_task(subject.get_or_create("key", produce))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(second, third, return_exceptions=True)

    assert results == [Value("shared hint", 1.0), Value("shared hint", 1.0)]
    assert calls == 1
    assert subject.recall("key") == Value("shared hint", 1.0)
    assert subject.inflight == {}


@pytest.mark.asyncio
async def test_abandoned_producer_failure_is_cleaned_up_and_can_be_retried() -> None:
    subject = cache([1.0])
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    loop = asyncio.get_running_loop()
    unhandled: list[dict] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    async def fail() -> Value:
        started.set()
        try:
            await release.wait()
            raise RuntimeError("hint provider failed")
        finally:
            finished.set()

    try:
        caller = asyncio.create_task(subject.get_or_create("key", fail))
        await started.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        release.set()
        await finished.wait()
        await asyncio.sleep(0)
        assert subject.inflight == {}
        value = await subject.get_or_create(
            "key", lambda: asyncio.sleep(0, result=Value("retried", 1.0))
        )
        assert value == Value("retried", 1.0)
        assert not unhandled
    finally:
        loop.set_exception_handler(previous_handler)
