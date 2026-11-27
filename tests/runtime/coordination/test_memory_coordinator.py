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


@pytest.mark.asyncio
async def test_a_released_turn_tail_is_dropped_after_its_retention(monkeypatch) -> None:
    """The durable journal holds a finished turn; the live tail is a bridge
    and must not outlive the process's interest in it."""
    coordinator = MemoryCoordinator()
    coordinator.retention_seconds = 0.0
    lease = await coordinator.acquire_turn("turn-a", "session-1", "worker-a")
    assert lease is not None
    for index in range(3):
        await coordinator.publish_event("turn-a", {"type": "content", "content": str(index)})
    await coordinator.submit_command("turn-a", "cancel", {}, command_id="cancel-1")

    # Still live: nothing is dropped while the lease is held.
    assert len(await coordinator.read_events("turn-a")) == 3

    await coordinator.release_turn(lease)
    assert await coordinator.read_events("turn-a") == []
    assert await coordinator.read_commands("turn-a") == []
    assert coordinator._events == {} and coordinator._commands == {}
    assert coordinator._command_ids == {}


@pytest.mark.asyncio
async def test_a_late_write_for_an_unleased_turn_still_expires() -> None:
    coordinator = MemoryCoordinator()
    coordinator.retention_seconds = 0.0
    await coordinator.publish_event("turn-late", {"type": "session_meta"})
    assert await coordinator.read_events("turn-late") == []


@pytest.mark.asyncio
async def test_replays_and_reads_use_the_sequence_not_a_scan() -> None:
    coordinator = MemoryCoordinator()
    published = [
        await coordinator.publish_event("turn-a", {"type": "content", "content": str(i)})
        for i in range(50)
    ]
    assert await coordinator.publish_event("turn-a", dict(published[17])) == published[17]
    with pytest.raises(ValueError, match="conflict"):
        await coordinator.publish_event("turn-a", {"seq": 18, "type": "content", "content": "x"})
    tail = await coordinator.read_events("turn-a", 45)
    assert [row["seq"] for row in tail] == [46, 47, 48, 49, 50]


@pytest.mark.asyncio
async def test_acknowledged_background_commands_are_released() -> None:
    coordinator = MemoryCoordinator()
    for index in range(3):
        await coordinator.submit_background_command("cron_reload", command_id=f"reload-{index}")
    rows = await coordinator.read_background_commands()
    await coordinator.acknowledge_background_command(rows[1][0])

    assert [command.command_id for _, command in coordinator._background_commands] == ["reload-2"]
    later = await coordinator.submit_background_command("cron_reload", command_id="reload-3")
    assert later is not None
    # Numbering keeps counting after the list was trimmed.
    assert [cursor for cursor, _ in await coordinator.read_background_commands()] == ["3-0", "4-0"]


@pytest.mark.asyncio
async def test_acknowledged_turn_releases_payloads_but_live_owner_keeps_them() -> None:
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn("turn-a", "session-a", "worker")
    assert lease is not None
    await coordinator.publish_event("turn-a", {"type": "content", "content": "large answer"})
    await coordinator.submit_command("turn-a", "cancel", command_id="cancel-a")
    await coordinator.acknowledge_expired_turn("turn-a")
    assert len(await coordinator.read_events("turn-a")) == 1
    assert len(await coordinator.read_commands("turn-a")) == 1
    await coordinator.release_turn(lease)
    await coordinator.acknowledge_expired_turn("turn-a")
    assert await coordinator.read_events("turn-a") == []
    assert await coordinator.read_commands("turn-a") == []
    assert "cancel-a" not in coordinator._command_ids
    assert await coordinator.list_expired_turn_ids() == []
