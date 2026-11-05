"""A configured polling budget also bounds stalled HTTP and poll sleeps."""

import asyncio
import json

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
    adapter_type: type, stall: bool
) -> None:
    release = asyncio.Event()
    handlers: set[asyncio.Task] = set()
    requests = 0

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal requests
        task = asyncio.current_task()
        assert task is not None
        handlers.add(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            requests += 1
            if stall:
                await release.wait()
            else:
                payload = json.dumps(
                    {"status": "running", "output": {"task_status": "RUNNING"}}
                ).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(payload)).encode()
                    + b"\r\nConnection: close\r\n\r\n"
                    + payload
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    config = VideogenConfig(
        model="fixture-model",
        base_url=f"http://127.0.0.1:{port}",
        request_timeout=5,
        poll_interval=5,
        poll_timeout=1,
    )
    try:
        async with httpx.AsyncClient(timeout=config.request_timeout, trust_env=False) as client:
            with pytest.raises(GenerationProviderError, match="timed out"):
                await asyncio.wait_for(
                    adapter_type()._poll(client, config, {}, "task", None), timeout=2
                )
        assert requests == 1
    finally:
        release.set()
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers, return_exceptions=True)


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
