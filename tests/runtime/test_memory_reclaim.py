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
