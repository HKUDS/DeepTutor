"""The book event stream must outlive the request that started the work.

Regression cover for the bug this module exists to fix: background compilation
published into a bus the router had already closed, so every ``block_ready``
after ``confirm_spine`` returned was silently dropped and the reader watched a
frozen page for the whole build.
"""

import asyncio

import pytest

from deeptutor.book import event_hub
from deeptutor.book.event_hub import (
    BOOK_EVENT_HISTORY_LIMIT,
    close_book_bus,
    get_book_bus,
    get_book_stream,
)
from deeptutor.book.streaming import SOURCE as BOOK_SOURCE


@pytest.fixture(autouse=True)
def _clean_hub():
    event_hub._buses.clear()
    yield
    event_hub._buses.clear()


async def _drain(bus, count, timeout=1.0):
    """Collect *count* events from a fresh subscription."""
    received = []

    async def _read():
        async for event in bus.subscribe():
            received.append(event)
            if len(received) >= count:
                return

    await asyncio.wait_for(_read(), timeout=timeout)
    return received


def test_the_same_book_always_gets_the_same_bus() -> None:
    assert get_book_bus("bk_1") is get_book_bus("bk_1")
    assert get_book_bus("bk_1") is not get_book_bus("bk_2")


@pytest.mark.asyncio
async def test_a_late_subscriber_catches_up_on_what_it_missed() -> None:
    """A reader who refreshes mid-compilation must not see a frozen page."""
    stream = get_book_stream("bk_1")
    await stream.book_event("page_planned", {"page_id": "pg_1"})
    await stream.book_event("block_ready", {"block_id": "blk_1"})

    events = await _drain(get_book_bus("bk_1"), 2)

    assert [e.metadata["kind"] for e in events] == ["page_planned", "block_ready"]


@pytest.mark.asyncio
async def test_background_events_still_arrive_after_the_action_returns() -> None:
    """The exact shape of the original bug, in miniature.

    A client subscribes, an action finishes and its handler unwinds, and only
    *then* does background work emit. Those events must still be delivered.
    """
    bus = get_book_bus("bk_1")
    received: list[str] = []
    ready = asyncio.Event()

    async def watcher():
        async for event in bus.subscribe():
            received.append(str(event.metadata.get("kind")))
            ready.set()

    task = asyncio.create_task(watcher())
    await asyncio.sleep(0)

    # …the request handler returns here; previously it closed the bus …
    await get_book_stream("bk_1").book_event("block_ready", {"block_id": "blk_late"})

    await asyncio.wait_for(ready.wait(), timeout=1.0)
    task.cancel()
    assert received == ["block_ready"]


@pytest.mark.asyncio
async def test_history_is_bounded_so_a_long_build_cannot_grow_without_limit() -> None:
    stream = get_book_stream("bk_1")
    for index in range(BOOK_EVENT_HISTORY_LIMIT + 25):
        await stream.book_event("block_ready", {"index": index})

    bus = get_book_bus("bk_1")
    assert len(bus._history) == BOOK_EVENT_HISTORY_LIMIT
    # The tail is what a reconnecting client cares about.
    assert bus._history[-1].metadata["index"] == BOOK_EVENT_HISTORY_LIMIT + 24


@pytest.mark.asyncio
async def test_deleting_a_book_ends_its_stream() -> None:
    bus = get_book_bus("bk_1")
    finished = asyncio.Event()

    async def watcher():
        async for _ in bus.subscribe():
            pass
        finished.set()

    task = asyncio.create_task(watcher())
    await asyncio.sleep(0)

    close_book_bus("bk_1")

    await asyncio.wait_for(finished.wait(), timeout=1.0)
    await task
    assert get_book_bus("bk_1") is not bus, "a deleted book must not reuse its closed bus"


@pytest.mark.asyncio
async def test_events_carry_the_book_source_so_sockets_can_filter() -> None:
    await get_book_stream("bk_1").book_event("spine_ready", {"chapter_count": 3})
    (event,) = await _drain(get_book_bus("bk_1"), 1)
    assert event.source == BOOK_SOURCE
