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


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running", "waiting_input"])
async def test_other_process_turn_survives_server_recovery_then_recovers_after_exit(
    tmp_path, status
):
    import subprocess
    import sys

    script = """
import asyncio, sys
from pathlib import Path
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.coordination.worker_identity import new_worker_id
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
async def run():
    store = SQLiteSessionStore(Path(sys.argv[1]))
    session = await store.ensure_session(None)
    coordinator = MemoryCoordinator()
    lease = await coordinator.acquire_turn('cli-turn', session['id'], new_worker_id())
    await store.begin_turn(session['id'], 'chat', turn_id=lease.turn_id,
                          owner_id=lease.owner_id, fencing_token=lease.fencing_token)
    await store.transition_turn(lease.turn_id, sys.argv[2])
    await store.append_events(lease.turn_id, [{'type':'content', 'content':'live CLI'}])
    print('ready', flush=True)
    await asyncio.to_thread(sys.stdin.readline)
asyncio.run(run())
"""
    db = tmp_path / "shared.db"
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(db), status],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 15)
        assert ready == "ready\n", process.stderr.read() if not ready else ready
        store = SQLiteSessionStore(db)
        recovery = TurnRecoveryService(MemoryCoordinator(), store)
        original = await store.get_events("cli-turn")
        for _ in range(3):
            assert await recovery.recover_once() == 0
        assert (await store.get_turn("cli-turn"))["status"] == status
        assert await store.get_events("cli-turn") == original
        process.terminate()
        await asyncio.to_thread(process.wait, 5)
        assert await recovery.recover_once() == 1
        assert (await store.get_turn("cli-turn"))["failure_code"] == "worker_lost"
        assert [event["seq"] for event in await store.get_events("cli-turn")] == [1, 2, 3]
        assert await recovery.recover_once() == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def test_worker_identity_handles_pid_reuse_legacy_and_inaccessible_processes(monkeypatch):
    import os
    import socket
    import time

    import psutil

    from deeptutor.runtime.coordination import worker_identity as identity

    owner = identity.new_worker_id()
    assert identity.owner_process_may_be_alive({"owner_id": owner})
    parts = owner.split(":")
    parts[-1] = str(float(parts[-1]) - 100)
    assert not identity.owner_process_may_be_alive({"owner_id": ":".join(parts)})
    legacy = f"{socket.gethostname()}:{os.getpid()}:old"
    assert identity.owner_process_may_be_alive({"owner_id": legacy, "created_at": time.time()})
    assert not identity.owner_process_may_be_alive({"owner_id": legacy, "created_at": 1})
    assert identity.owner_process_may_be_alive({"owner_id": "another-host:123:old"})

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(identity.psutil, "Process", denied)
    assert identity.owner_process_may_be_alive({"owner_id": owner})


@pytest.mark.asyncio
async def test_locally_expired_lease_still_recovers_even_while_owner_process_exists(tmp_path):
    from deeptutor.runtime.coordination.worker_identity import new_worker_id

    store = SQLiteSessionStore(tmp_path / "expired.db")
    session = await store.ensure_session(None)
    coordinator = MemoryCoordinator(lease_ttl_seconds=-1)
    lease = await coordinator.acquire_turn("expired", session["id"], new_worker_id())
    await store.begin_turn(
        session["id"],
        "chat",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    assert await TurnRecoveryService(coordinator, store).recover_once() == 1
