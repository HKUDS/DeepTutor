from __future__ import annotations

import asyncio

import pytest

from deeptutor.runtime.coordination import MemoryCoordinator


@pytest.mark.asyncio
async def test_publish_between_read_and_wait_is_not_lost():
    coordinator = MemoryCoordinator()
    assert await coordinator.read_events("turn") == []
    await coordinator.publish_event("turn", {"type": "content", "content": "hello"})
    # The waiter must inspect the cursor atomically before registering itself.
    await asyncio.wait_for(coordinator.wait_for_events("turn", 0, timeout=10), 0.1)
    assert coordinator._event_waiters == {}


@pytest.mark.asyncio
async def test_fanout_wakes_all_consumers_and_preserves_replay():
    coordinator = MemoryCoordinator()
    tasks = [
        asyncio.create_task(coordinator.wait_for_events("turn", 0, timeout=10)) for _ in range(4)
    ]
    await asyncio.sleep(0)
    event = await coordinator.publish_event("turn", {"type": "content", "content": "hello"})
    await asyncio.wait_for(asyncio.gather(*tasks), 0.1)
    assert coordinator._event_waiters == {}
    assert await coordinator.read_events("turn", 0) == [event]


@pytest.mark.asyncio
async def test_timeout_and_cancel_remove_waiters_without_losing_other_subscribers():
    coordinator = MemoryCoordinator()
    cancelled = asyncio.create_task(coordinator.wait_for_events("turn", 0, timeout=10))
    live = asyncio.create_task(coordinator.wait_for_events("turn", 0, timeout=10))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert len(coordinator._event_waiters["turn"]) == 1
    await coordinator.publish_event("turn", {"type": "done"})
    await live
    await coordinator.wait_for_events("empty", 0, timeout=0.001)
    assert coordinator._event_waiters == {}


@pytest.mark.asyncio
async def test_release_and_shutdown_wake_waiters():
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn("turn", "session", "owner")
    assert lease is not None
    waiter = asyncio.create_task(coordinator.wait_for_events("turn", 0, timeout=10))
    await asyncio.sleep(0)
    await coordinator.release_turn(lease)
    await asyncio.wait_for(waiter, 0.1)
    waiter = asyncio.create_task(coordinator.wait_for_events("other", 0, timeout=10))
    await asyncio.sleep(0)
    await coordinator.close()
    await asyncio.wait_for(waiter, 0.1)
    assert coordinator._event_waiters == {}
