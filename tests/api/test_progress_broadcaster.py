from __future__ import annotations

import asyncio

import pytest

from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster


class _Socket:
    def __init__(self, *, blocked=False, failed=False):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()
        self.failed = failed
        self.started = []
        self.sent = []

    async def send_json(self, payload):
        self.started.append(payload)
        self.entered.set()
        await self.release.wait()
        if self.failed:
            raise RuntimeError("closed socket")
        self.sent.append(payload)


@pytest.fixture
def broadcaster(monkeypatch):
    manager = ProgressBroadcaster()
    monkeypatch.setattr(manager, "_connections", {})
    monkeypatch.setattr(manager, "_lock", asyncio.Lock())
    return manager


@pytest.mark.asyncio
async def test_slow_kb_does_not_block_other_subscriptions(broadcaster):
    slow, fast = _Socket(blocked=True), _Socket()
    await broadcaster.connect("kb-a", slow)
    sending = asyncio.create_task(broadcaster.broadcast("kb-a", {"percent": 1}))
    await asyncio.wait_for(slow.entered.wait(), timeout=1)

    async def other_operations():
        await broadcaster.connect("kb-b", fast)
        await broadcaster.broadcast("kb-b", {"percent": 2})
        await broadcaster.disconnect("kb-b", fast)
        await broadcaster.disconnect("kb-a", slow)

    try:
        await asyncio.wait_for(other_operations(), timeout=1)
        assert fast.sent == [{"type": "progress", "data": {"percent": 2}}]
        assert broadcaster.get_connection_count("kb-a") == 0
        assert broadcaster.get_connection_count("kb-b") == 0
    finally:
        slow.release.set()
        await sending


@pytest.mark.asyncio
async def test_same_kb_broadcasts_keep_send_order_and_latest_progress(broadcaster):
    socket = _Socket(blocked=True)
    await broadcaster.connect("kb", socket)
    first = asyncio.create_task(broadcaster.broadcast("kb", {"percent": 1}))
    await asyncio.wait_for(socket.entered.wait(), timeout=1)
    second = asyncio.create_task(broadcaster.broadcast("kb", {"percent": 100}))
    try:
        await asyncio.sleep(0)
        assert socket.started == [{"type": "progress", "data": {"percent": 1}}]
    finally:
        socket.release.set()
        await asyncio.gather(first, second)
    assert socket.sent == [
        {"type": "progress", "data": {"percent": 1}},
        {"type": "progress", "data": {"percent": 100}},
    ]


@pytest.mark.asyncio
async def test_failed_send_cleanup_preserves_a_new_subscription(broadcaster):
    failed, replacement = _Socket(blocked=True, failed=True), _Socket()
    await broadcaster.connect("kb", failed)
    sending = asyncio.create_task(broadcaster.broadcast("kb", {"percent": 1}))
    await asyncio.wait_for(failed.entered.wait(), timeout=1)
    try:
        await asyncio.wait_for(broadcaster.disconnect("kb", failed), timeout=1)
        await broadcaster.connect("kb", replacement)
    finally:
        failed.release.set()
        await sending

    assert broadcaster.get_connection_count("kb") == 1
    await broadcaster.broadcast("kb", {"percent": 100})
    assert replacement.sent == [{"type": "progress", "data": {"percent": 100}}]


@pytest.mark.asyncio
async def test_failed_sockets_are_removed(broadcaster):
    await broadcaster.connect("kb", _Socket(failed=True))
    await broadcaster.broadcast("kb", {"percent": 1})
    assert broadcaster.get_connection_count("kb") == 0


@pytest.mark.asyncio
async def test_queued_broadcasts_do_not_roll_back_a_new_subscribers_replay(broadcaster):
    slow, newcomer = _Socket(blocked=True), _Socket()
    await broadcaster.connect("kb", slow)
    first = asyncio.create_task(broadcaster.broadcast("kb", {"percent": 0}))
    await asyncio.wait_for(slow.entered.wait(), timeout=1)
    queued = []
    for percent in (1, 2):
        queued.append(asyncio.create_task(broadcaster.broadcast("kb", {"percent": percent})))
        await asyncio.sleep(0)
    try:
        await asyncio.wait_for(broadcaster.connect("kb", newcomer), timeout=1)
        await newcomer.send_json({"type": "progress", "data": {"percent": 2}})
    finally:
        slow.release.set()
        await asyncio.gather(first, *queued)
    assert newcomer.sent == [{"type": "progress", "data": {"percent": 2}}]
