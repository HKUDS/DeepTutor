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
async def test_cancelled_waiter_does_not_cancel_shared_producer() -> None:
    """A disconnected request must not cancel another request's hints."""
    subject = cache([1.0])
    entered = asyncio.Event()
    release = asyncio.Event()
    started = 0

    async def produce() -> Value:
        """Generate a real shared result after callers have joined."""
        nonlocal started
        started += 1
        entered.set()
        await release.wait()
        return Value("ready", 1.0)

    first = asyncio.create_task(subject.get_or_create("key", produce))
    second = asyncio.create_task(subject.get_or_create("key", produce))
    third = None
    try:
        await entered.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        third = asyncio.create_task(subject.get_or_create("key", produce))
        release.set()
        assert await asyncio.wait_for(second, 1) == Value("ready", 1.0)
        assert await asyncio.wait_for(third, 1) == Value("ready", 1.0)
        assert started == 1
        assert subject.recall("key") == Value("ready", 1.0)
        assert subject.inflight == {}
    finally:
        release.set()
        for task in (first, second, third):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (first, second, third) if task is not None),
            return_exceptions=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_producer_finishes_and_cleans_up_without_waiters(fails: bool) -> None:
    """An abandoned producer must cache successes and retain no failed task."""
    subject = cache([1.0])
    entered = asyncio.Event()
    release = asyncio.Event()

    async def produce() -> Value:
        """Complete only after its sole requester has disconnected."""
        entered.set()
        await release.wait()
        if fails:
            raise RuntimeError("producer failed")
        return Value("ready", 1.0)

    waiter = asyncio.create_task(subject.get_or_create("key", produce))
    pending = None
    try:
        await entered.wait()
        pending = subject.inflight["key"]
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not pending.done()
        assert subject.inflight["key"] is pending
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        assert subject.inflight == {}
        assert subject.recall("key") == (None if fails else Value("ready", 1.0))
    finally:
        release.set()
        waiter.cancel()
        if pending is not None:
            pending.cancel()
        await asyncio.gather(
            *(task for task in (waiter, pending) if task is not None),
            return_exceptions=True,
        )
