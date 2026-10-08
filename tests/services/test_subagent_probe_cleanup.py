"""Probe timeouts and cancellation must reap native child processes."""

import asyncio
import sys

import pytest

from deeptutor.services.subagent import models, process


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["models_timeout", "models_cancel", "version_cancel"])
async def test_probe_reaps_child_on_timeout_or_cancellation(monkeypatch, kind):
    spawn = asyncio.create_subprocess_exec
    wait_for = asyncio.wait_for
    children = []
    started = asyncio.Event()

    async def native_child(*args, **kwargs):
        child = await spawn(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        children.append(child)
        started.set()
        return child

    async def bounded_wait(awaitable, timeout):
        return await wait_for(awaitable, timeout=0.05 if timeout in (20.0, 60.0) else timeout)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", native_child)
    monkeypatch.setattr(asyncio, "wait_for", bounded_wait)
    task = asyncio.create_task(
        process.probe_version([sys.executable])
        if kind == "version_cancel"
        else models._list_cli_models(sys.executable)
    )
    try:
        await wait_for(started.wait(), timeout=5)
        if kind.endswith("cancel"):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == []
        assert children[0].returncode is not None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for child in children:
            if child.returncode is None:
                child.kill()
            await child.wait()
