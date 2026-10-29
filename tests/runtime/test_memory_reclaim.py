from __future__ import annotations

import asyncio

import pytest

from deeptutor.runtime import memory_reclaim


@pytest.mark.asyncio
async def test_scheduled_reclaims_are_coalesced(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def _release() -> tuple[int, bool]:
        nonlocal calls
        calls += 1
        return 3, True

    monkeypatch.setattr(memory_reclaim, "release_unused_memory", _release)

    first = memory_reclaim.schedule_memory_reclaim()
    second = memory_reclaim.schedule_memory_reclaim()

    assert first is second
    assert first is not None
    assert await first == (3, True)
    await asyncio.sleep(0)
    assert calls == 1


@pytest.mark.asyncio
async def test_interactive_turns_collect_only_after_quiet_time(monkeypatch):
    memory_reclaim.cancel_idle_reclaim()
    calls = []
    monkeypatch.setattr(memory_reclaim, "_IDLE_SECONDS", 0.01)
    monkeypatch.setattr(memory_reclaim, "_MIN_IDLE_COLLECTION_INTERVAL", 0)
    monkeypatch.setattr(
        memory_reclaim, "release_unused_memory", lambda: (calls.append(1) or 0, False)
    )
    try:
        with memory_reclaim.interactive_memory_scope():
            with memory_reclaim.interactive_memory_scope():
                await asyncio.sleep(0.03)
            await asyncio.sleep(0.03)
            assert calls == []
        await asyncio.sleep(0.03)
        assert calls == [1]
    finally:
        memory_reclaim.cancel_idle_reclaim()


@pytest.mark.asyncio
async def test_new_turn_invalidates_pending_collection_and_reschedules(monkeypatch):
    memory_reclaim.cancel_idle_reclaim()
    calls = []
    monkeypatch.setattr(memory_reclaim, "_IDLE_SECONDS", 0.02)
    monkeypatch.setattr(memory_reclaim, "_MIN_IDLE_COLLECTION_INTERVAL", 0)
    monkeypatch.setattr(
        memory_reclaim, "release_unused_memory", lambda: (calls.append(1) or 0, False)
    )
    try:
        with memory_reclaim.interactive_memory_scope():
            pass
        with memory_reclaim.interactive_memory_scope():
            await asyncio.sleep(0.04)
            assert calls == []
        await asyncio.sleep(0.04)
        assert calls == [1]
    finally:
        memory_reclaim.cancel_idle_reclaim()


@pytest.mark.asyncio
async def test_queued_idle_work_rechecks_activity_and_collection_is_rate_limited(monkeypatch):
    memory_reclaim.cancel_idle_reclaim()
    calls = []
    monkeypatch.setattr(memory_reclaim, "_IDLE_SECONDS", 0.001)
    monkeypatch.setattr(memory_reclaim, "_MIN_IDLE_COLLECTION_INTERVAL", 1)
    monkeypatch.setattr(memory_reclaim, "_last_idle_collection", memory_reclaim.time.monotonic())
    monkeypatch.setattr(
        memory_reclaim, "release_unused_memory", lambda: (calls.append(1) or 0, False)
    )
    generation = memory_reclaim._activity_generation
    try:
        with memory_reclaim.interactive_memory_scope():
            assert await asyncio.to_thread(memory_reclaim._release_if_idle, generation) == (
                0,
                False,
            )
        await asyncio.sleep(0.03)
        assert calls == []
    finally:
        memory_reclaim.cancel_idle_reclaim()
