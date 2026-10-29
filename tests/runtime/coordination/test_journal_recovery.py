from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.coordination.journal import TurnEventJournal
from deeptutor.runtime.coordination.recovery import TurnRecoveryService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.mark.asyncio
async def test_journal_publishes_first_then_flushes_terminal_batch(tmp_path) -> None:
    repository = SQLiteSessionStore(tmp_path / "turns.db")
    session = await repository.ensure_session(None)
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn("turn-a", session["id"], "worker-a")
    assert lease is not None
    await repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    journal = TurnEventJournal(
        coordinator,
        repository,
        lease,
        batch_size=10,
        flush_interval_seconds=60,
    )

    published = await journal.publish({"type": "content", "content": "hello"})
    assert (await coordinator.read_events(lease.turn_id))[0] == published
    assert await repository.get_events(lease.turn_id) == []

    await journal.flush_terminal()
    assert (await repository.get_events(lease.turn_id))[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_recovery_preserves_unflushed_events_and_marks_retryable_failure(tmp_path) -> None:
    repository = SQLiteSessionStore(tmp_path / "turns.db")
    session = await repository.ensure_session(None)
    coordinator = MemoryCoordinator(lease_ttl_seconds=0.01)
    lease = await coordinator.acquire_turn("turn-a", session["id"], "worker-a")
    assert lease is not None
    await repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    await coordinator.publish_event(lease.turn_id, {"type": "content", "content": "survives"})
    await asyncio.sleep(0.02)

    recovery = TurnRecoveryService(coordinator, repository)
    assert await recovery.recover_once() == 1

    turn = await repository.get_turn(lease.turn_id)
    assert turn is not None
    assert turn["status"] == "failed"
    assert turn["failure_code"] == "worker_lost"
    assert turn["retryable"] is True
    assert (await repository.get_events(lease.turn_id))[0]["content"] == "survives"
    assert await coordinator.list_expired_turn_ids() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "waiting_input"])
async def test_restart_recovers_durable_turn_without_new_submission(tmp_path, status) -> None:
    repository = SQLiteSessionStore(tmp_path / "turns.db")
    session = await repository.ensure_session(None)
    old_coordinator = MemoryCoordinator()
    lease = await old_coordinator.acquire_turn("interrupted", session["id"], "old-worker")
    await repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    await repository.transition_turn(lease.turn_id, status)
    await repository.append_events(
        lease.turn_id,
        [
            {"type": "session", "content": ""},
            {"type": "content", "content": "partial answer"},
        ],
    )
    original = await repository.get_events(lease.turn_id)
    # A new process has neither the old lease index nor its event stream.
    coordinator = MemoryCoordinator()
    assert await coordinator.list_expired_turn_ids() == []
    recovery = TurnRecoveryService(coordinator, repository)

    assert await recovery.recover_once() == 1
    turn = await repository.get_turn(lease.turn_id)
    assert turn["status"] == "failed"
    assert turn["failure_code"] == "worker_lost"
    assert turn["retryable"] is True
    events = await repository.get_events(lease.turn_id)
    assert events[:2] == original
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert [e["type"] for e in events] == ["session", "content", "error", "done"]
    assert events[-1]["metadata"]["status"] == "failed"
    assert await recovery.recover_once() == 0
    assert await repository.get_events(lease.turn_id) == events
    # Recovery unblocks admission without a user-triggered reclaim path.
    assert (await repository.begin_turn(session["id"], "chat"))["id"] != lease.turn_id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "waiting_input"])
async def test_durable_scan_preserves_live_turns(tmp_path, status) -> None:
    repository = SQLiteSessionStore(tmp_path / "turns.db")
    session = await repository.ensure_session(None)
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn("live", session["id"], "worker")
    await repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    await repository.transition_turn(lease.turn_id, status)
    assert await TurnRecoveryService(coordinator, repository).recover_once() == 0
    assert (await repository.get_turn(lease.turn_id))["status"] == status
    assert await coordinator.get_lease(lease.turn_id) == lease
    assert await repository.get_events(lease.turn_id) == []


@pytest.mark.asyncio
async def test_recovery_rechecks_lease_after_expired_scan(tmp_path, monkeypatch) -> None:
    repository = SQLiteSessionStore(tmp_path / "turns.db")
    session = await repository.ensure_session(None)
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn("live", session["id"], "worker")
    await repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    monkeypatch.setattr(coordinator, "list_expired_turn_ids", AsyncMock(return_value=["live"]))
    assert await TurnRecoveryService(coordinator, repository).recover_once() == 0
    assert (await repository.get_turn("live"))["status"] != "failed"
    assert await repository.get_events("live") == []


@pytest.mark.asyncio
async def test_recovery_does_not_publish_failure_if_terminal_transition_loses(
    tmp_path, monkeypatch
):
    repository = SQLiteSessionStore(tmp_path / "turns.db")
    session = await repository.ensure_session(None)
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn("finished", session["id"], "worker")
    await repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    await coordinator.release_turn(lease)
    transition = repository.transition_turn

    async def complete_first(*args, **kwargs):
        await transition("finished", "completed")
        return False

    monkeypatch.setattr(repository, "transition_turn", complete_first)
    publish = AsyncMock(wraps=coordinator.publish_event)
    monkeypatch.setattr(coordinator, "publish_event", publish)
    assert await TurnRecoveryService(coordinator, repository).recover_once() == 0
    assert (await repository.get_turn("finished"))["status"] == "completed"
    assert await repository.get_events("finished") == []
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_user_repository_does_not_acknowledge_expired_turn(tmp_path) -> None:
    owner_repository = SQLiteSessionStore(tmp_path / "owner.db")
    other_repository = SQLiteSessionStore(tmp_path / "other.db")
    session = await owner_repository.ensure_session(None)
    coordinator = MemoryCoordinator(lease_ttl_seconds=0.01)
    lease = await coordinator.acquire_turn("turn-scoped", session["id"], "worker-a")
    assert lease is not None
    await owner_repository.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    await asyncio.sleep(0.02)

    assert await TurnRecoveryService(coordinator, other_repository).recover_once() == 0
    assert await coordinator.list_expired_turn_ids() == [lease.turn_id]

    assert await TurnRecoveryService(coordinator, owner_repository).recover_once() == 1
    assert await coordinator.list_expired_turn_ids() == []
