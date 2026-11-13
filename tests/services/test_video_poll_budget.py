"""A configured polling budget also bounds stalled HTTP and poll sleeps."""

import asyncio
from contextlib import suppress

import httpx
import pytest

from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.adapters.dashscope import DashScopeVideogenAdapter
from deeptutor.services.videogen.adapters.xai import XaiVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type", [AsyncTaskVideogenAdapter, DashScopeVideogenAdapter, XaiVideogenAdapter]
)
@pytest.mark.parametrize("stall", [False, True])
async def test_poll_timeout_bounds_network_wait_and_interval(
    adapter_type: type, stall: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = 0
    drained = asyncio.Event()
    sleep_delays: list[float] = []
    sleep_drained = asyncio.Event()
    original_sleep = asyncio.sleep

    async def observing_sleep(delay: float) -> None:
        sleep_delays.append(delay)
        try:
            await original_sleep(delay)
        finally:
            sleep_drained.set()

    monkeypatch.setattr(asyncio, "sleep", observing_sleep)

    async def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        try:
            if stall:
                await asyncio.Event().wait()
            return httpx.Response(
                200, json={"status": "running", "output": {"task_status": "RUNNING"}}
            )
        finally:
            drained.set()

    config = VideogenConfig(
        model="fixture-model",
        base_url="https://fixture.invalid",
        request_timeout=5,
        poll_interval=5,
        poll_timeout=1,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(GenerationProviderError, match="timed out"):
            await asyncio.wait_for(
                adapter_type()._poll(client, config, {}, "task", None), timeout=2
            )
    assert requests == 1
    assert drained.is_set()
    if stall:
        assert sleep_delays == []
    else:
        assert sleep_delays == [config.poll_interval]
        assert sleep_drained.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type", [AsyncTaskVideogenAdapter, DashScopeVideogenAdapter, XaiVideogenAdapter]
)
async def test_poll_timeout_cancels_stalled_transport(
    adapter_type: type,
) -> None:
    attempts = 0
    cancelled = asyncio.Event()
    drained = asyncio.Event()

    class StalledTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finally:
                drained.set()
            raise AssertionError("unreachable")

    config = VideogenConfig(
        model="fixture-model", base_url="https://fixture.invalid", poll_timeout=1
    )
    async with httpx.AsyncClient(transport=StalledTransport()) as client:
        with pytest.raises(GenerationProviderError, match="timed out"):
            await asyncio.wait_for(
                adapter_type()._poll(client, config, {}, "task", None), timeout=2
            )
    assert attempts == 1
    assert cancelled.is_set()
    assert drained.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type", [AsyncTaskVideogenAdapter, DashScopeVideogenAdapter, XaiVideogenAdapter]
)
async def test_caller_cancellation_still_propagates_and_drains_request(adapter_type: type) -> None:
    started = asyncio.Event()
    drained = asyncio.Event()

    async def hold(_request: httpx.Request) -> httpx.Response:
        started.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        finally:
            drained.set()

    config = VideogenConfig(
        model="fixture-model", base_url="https://fixture.invalid", poll_timeout=60
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(hold)) as client:
        task = asyncio.create_task(adapter_type()._poll(client, config, {}, "task", None))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert drained.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type", [AsyncTaskVideogenAdapter, DashScopeVideogenAdapter, XaiVideogenAdapter]
)
async def test_callback_timeout_is_not_misclassified_as_poll_budget(adapter_type: type) -> None:
    async def pending(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "running", "output": {"task_status": "RUNNING"}})

    async def progress(_message: str) -> None:
        raise TimeoutError("callback timeout")

    config = VideogenConfig(
        model="fixture-model", base_url="https://fixture.invalid", poll_interval=0, poll_timeout=60
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(pending)) as client:
        with pytest.raises(TimeoutError, match="callback timeout"):
            await adapter_type()._poll(client, config, {}, "task", progress)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_type", [AsyncTaskVideogenAdapter, DashScopeVideogenAdapter, XaiVideogenAdapter]
)
async def test_real_tcp_cancellation_closes_inflight_poll_request(adapter_type: type) -> None:
    request_started = asyncio.Event()
    request_eof = asyncio.Event()
    handlers: list[asyncio.Task] = []
    writers: list[asyncio.StreamWriter] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            request_started.set()
            if not await reader.read():
                request_eof.set()
        finally:
            writer.close()

    def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        handlers.append(asyncio.create_task(handle(reader, writer)))

    poll_task: asyncio.Task | None = None
    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        config = VideogenConfig(
            model="fixture-model",
            base_url=f"http://127.0.0.1:{port}",
            poll_timeout=60,
            request_timeout=30,
        )
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            poll_task = asyncio.create_task(adapter_type()._poll(client, config, {}, "task", None))
            await asyncio.wait_for(request_started.wait(), timeout=10)
            poll_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(poll_task, timeout=5)
            await asyncio.wait_for(request_eof.wait(), timeout=5)
    finally:
        if poll_task is not None:
            poll_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(poll_task, timeout=5)
        server.close()
        for handler in handlers:
            handler.cancel()
        for writer in writers:
            writer.close()
        if handlers:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.gather(*handlers, return_exceptions=True), timeout=5)
        for writer in writers:
            with suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), timeout=5)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(server.wait_closed(), timeout=5)
