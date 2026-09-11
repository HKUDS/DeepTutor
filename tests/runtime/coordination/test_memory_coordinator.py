from __future__ import annotations

import asyncio

import pytest

from deeptutor.runtime.coordination import MemoryCoordinator, RuntimeCoordinator


@pytest.mark.asyncio
async def test_session_lease_is_exclusive_and_fenced() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    assert isinstance(coordinator, RuntimeCoordinator)

    first = await coordinator.acquire_turn("turn-a", "session-1", "worker-a")
    assert first is not None
    assert await coordinator.acquire_turn("turn-b", "session-1", "worker-b") is None

    assert await coordinator.release_turn(first) is True
    second = await coordinator.acquire_turn("turn-b", "session-1", "worker-b")
    assert second is not None
    assert second.fencing_token > first.fencing_token


@pytest.mark.asyncio
async def test_only_owner_with_current_fence_can_renew_or_release() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    lease = await coordinator.acquire_turn("turn-a", "session-1", "worker-a")
    assert lease is not None
    stale = lease.__class__(
        turn_id=lease.turn_id,
        session_id=lease.session_id,
        owner_id="worker-b",
        fencing_token=lease.fencing_token,
        expires_at=lease.expires_at,
    )

    assert await coordinator.renew_turn(stale) is None
    assert await coordinator.release_turn(stale) is False
    assert await coordinator.get_lease("turn-a") == lease


@pytest.mark.asyncio
async def test_events_are_sequenced_replayable_and_idempotent() -> None:
    coordinator = MemoryCoordinator()
    one = await coordinator.publish_event("turn-a", {"type": "content", "content": "a"})
    two = await coordinator.publish_event("turn-a", {"type": "content", "content": "b"})

    assert [one["seq"], two["seq"]] == [1, 2]
    assert [item["content"] for item in await coordinator.read_events("turn-a", 1)] == ["b"]
    assert await coordinator.publish_event("turn-a", dict(one)) == one
    with pytest.raises(ValueError, match="conflict"):
        await coordinator.publish_event(
            "turn-a", {"seq": 1, "type": "content", "content": "replacement"}
        )


@pytest.mark.asyncio
async def test_commands_are_deduplicated_and_keep_stream_cursor() -> None:
    coordinator = MemoryCoordinator()
    command = await coordinator.submit_command("turn-a", "cancel", {}, command_id="command-1")
    duplicate = await coordinator.submit_command("turn-a", "cancel", {}, command_id="command-1")

    assert command is not None
    assert duplicate is None
    rows = await coordinator.read_commands("turn-a")
    assert len(rows) == 1
    cursor, persisted = rows[0]
    assert persisted == command
    assert await coordinator.read_commands("turn-a", after_id=cursor) == []


@pytest.mark.asyncio
async def test_background_commands_are_deduplicated_and_acknowledged_globally() -> None:
    coordinator = MemoryCoordinator()
    command = await coordinator.submit_background_command(
        "partner_start",
        {"partner_id": "ada"},
        command_id="background-1",
    )
    duplicate = await coordinator.submit_background_command(
        "partner_start",
        {"partner_id": "ada"},
        command_id="background-1",
    )

    assert command is not None
    assert duplicate is None
    rows = await coordinator.read_background_commands()
    assert len(rows) == 1
    cursor, persisted = rows[0]
    assert persisted == command

    await coordinator.acknowledge_background_command(cursor)
    assert await coordinator.read_background_commands() == []


@pytest.mark.asyncio
async def test_background_command_ack_rejects_stale_leader_fence() -> None:
    coordinator = MemoryCoordinator()
    await coordinator.submit_background_command("cron_reload", command_id="reload-1")
    cursor, _ = (await coordinator.read_background_commands())[0]
    leader = await coordinator.acquire_leader("worker-a")
    assert leader is not None
    stale = leader.__class__("worker-b", leader.fencing_token, leader.expires_at)

    assert await coordinator.acknowledge_background_command(cursor, stale) is False
    assert len(await coordinator.read_background_commands()) == 1
    assert await coordinator.acknowledge_background_command(cursor, leader) is True
    assert await coordinator.read_background_commands() == []


@pytest.mark.asyncio
async def test_expired_lease_is_reported_without_changing_turn_state() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=0.01)
    lease = await coordinator.acquire_turn("turn-a", "session-1", "worker-a")
    assert lease is not None
    await asyncio.sleep(0.02)

    assert await coordinator.get_lease("turn-a") is None
    assert await coordinator.list_expired_turn_ids() == ["turn-a"]


@pytest.mark.asyncio
async def test_background_leader_is_singleton_and_transferable() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    leader = await coordinator.acquire_leader("worker-a")
    assert leader is not None
    assert await coordinator.acquire_leader("worker-b") is None
    assert await coordinator.leader_id() == "worker-a"

    assert await coordinator.release_leader(leader) is True
    successor = await coordinator.acquire_leader("worker-b")
    assert successor is not None
    assert successor.fencing_token > leader.fencing_token
