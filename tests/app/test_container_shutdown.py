"""Shutdown cancels active work while still awaiting its resource cleanup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.app.container import ApplicationContainer, RuntimeRegistry
from deeptutor.services.session.turns.lifecycle import TurnLifecycle


@pytest.mark.asyncio
async def test_container_cancels_turn_and_waits_for_cleanup(monkeypatch):
    events = []
    ready = asyncio.Event()
    execution = SimpleNamespace(task=None, subscribers=[], shutdown_requested=False)

    async def run_turn():
        try:
            ready.set()
            await asyncio.Event().wait()
        finally:
            assert execution.shutdown_requested
            await asyncio.sleep(0.01)  # asynchronous persistence/subprocess cleanup
            events.append("turn cleaned")

    async def close_store():
        events.append("store closed")

    runtime = object.__new__(TurnLifecycle)
    runtime._lock = asyncio.Lock()
    runtime._accepting_turns = True
    runtime._reply_queues = {}
    runtime._inboxes = {}
    runtime.store = SimpleNamespace(close=close_store)
    execution.task = asyncio.create_task(run_turn())
    runtime._executions = {"turn": execution}
    registry = object.__new__(RuntimeRegistry)
    registry._runtimes = {"workspace": runtime}
    container = object.__new__(ApplicationContainer)
    container._started = True
    container.runtime_registry = registry
    container.coordinator = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr("deeptutor.runtime.memory_reclaim.cancel_idle_reclaim", lambda: None)
    monkeypatch.setattr("deeptutor.runtime.ts_engine.close_engine_clients", AsyncMock())

    await ready.wait()
    await asyncio.wait_for(container.close(), timeout=0.5)

    assert events == ["turn cleaned", "store closed"]
    assert execution.task.done()
    assert not runtime._accepting_turns
    assert not container._started
    container.coordinator.close.assert_awaited_once()
