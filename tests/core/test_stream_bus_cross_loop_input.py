"""Input from a frontend loop must wake a capability on its owning loop."""

import asyncio
from concurrent.futures import Future
import selectors
import threading

import pytest

from deeptutor.runtime.stream_bus import StreamBus


class _ParkingSelector(selectors.DefaultSelector):
    def __init__(self) -> None:
        super().__init__()
        self.armed = threading.Event()
        self.parked = threading.Event()

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        if timeout is None and self.armed.is_set():
            self.parked.set()
        return super().select(timeout)


def test_input_from_another_loop_wakes_a_parked_capability() -> None:
    bus = StreamBus()
    selector = _ParkingSelector()
    loop = asyncio.SelectorEventLoop(selector)
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    async def wait_for_answer() -> str:
        # This callback runs only after wait_for_input has reached its pending
        # queue read. The selector then signals that the loop has no work.
        loop.call_soon(selector.armed.set)
        return await bus.wait_for_input("Choose an option")

    answer: Future[str] = asyncio.run_coroutine_threadsafe(wait_for_answer(), loop)
    try:
        assert selector.parked.wait(timeout=2)
        bus.submit_input("continue")
        assert answer.result(timeout=1) == "continue"
    finally:
        # Wake even a broken implementation so the failed reproduction leaves
        # neither a pending task nor a worker thread behind.
        loop.call_soon_threadsafe(lambda: None)
        try:
            answer.result(timeout=2)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=2)
            loop.close()
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_input_still_reaches_all_waiters_on_the_same_loop() -> None:
    bus = StreamBus()
    first = asyncio.create_task(bus.wait_for_input("First question"))
    second = asyncio.create_task(bus.wait_for_input("Second question"))
    asyncio.get_running_loop().call_soon(bus.submit_input, "continue")

    assert await asyncio.wait_for(asyncio.gather(first, second), timeout=2) == [
        "continue",
        "continue",
    ]


@pytest.mark.asyncio
async def test_timed_out_input_does_not_consume_the_next_answer() -> None:
    bus = StreamBus()
    assert await bus.wait_for_input("Expired question", timeout=0) == ""
    pending = asyncio.create_task(bus.wait_for_input("Next question"))
    asyncio.get_running_loop().call_soon(bus.submit_input, "continue")

    assert await asyncio.wait_for(pending, timeout=2) == "continue"
