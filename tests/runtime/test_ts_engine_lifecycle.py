"""Worker loss must be observable only after that worker can no longer be reused."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.runtime.ts_engine.client import EngineClient, EngineUnavailableError


@pytest.mark.asyncio
@pytest.mark.parametrize("last_frame", [b"", b"invalid protocol\n"])
async def test_worker_failure_waits_for_process_exit_before_notifying_turns(last_frame):
    reaping = asyncio.Event()
    exited = asyncio.Event()
    process = SimpleNamespace(
        stdout=SimpleNamespace(readline=AsyncMock(return_value=last_frame)),
        returncode=None,
        terminate=lambda: None,
    )

    async def wait():
        reaping.set()
        await exited.wait()
        process.returncode = -15
        return process.returncode

    process.wait = wait
    client = EngineClient()
    client._process = process
    queue = asyncio.Queue()
    client._runs["turn"] = queue
    reader = asyncio.create_task(client._read(process))
    try:
        await asyncio.wait_for(reaping.wait(), 1)
        # A notified caller may immediately start another turn. While returncode
        # is None, _ensure_started would still consider this worker reusable.
        assert queue.empty()
    finally:
        exited.set()
        await reader
    assert process.returncode is not None
    assert isinstance(queue.get_nowait(), EngineUnavailableError)
