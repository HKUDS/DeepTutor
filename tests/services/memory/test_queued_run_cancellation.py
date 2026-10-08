"""Cancellation before the driver starts must release the document slot."""

import asyncio

import pytest

from deeptutor.services.memory.consolidator.runs import RunManager


@pytest.mark.asyncio
async def test_cancel_queued_run_finishes_replay_and_allows_retry() -> None:
    """Cancel immediately, before yielding control to the newly created task."""
    manager = RunManager()
    calls = []

    async def runner(on_event):
        calls.append(True)

    run = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    assert await manager.cancel(run.id)
    assert run._task is not None
    await asyncio.gather(run._task, return_exceptions=True)
    assert calls == []
    assert run.status == "cancelled"
    assert run.ended_at is not None
    assert manager.active_for("L2", "chat") is None
    events = await asyncio.wait_for(manager.wait_for_events(run, since=0), timeout=1)
    assert [event.payload["stage"] for event in events] == ["cancelled", "run_ended"]
    assert await asyncio.wait_for(manager.wait_for_events(run, since=2), timeout=1) == []
    retry = await manager.start(layer="L2", key="chat", mode="update", runner=runner)
    assert retry._task is not None
    await retry._task
    assert retry.status == "done"
    assert calls == [True]
