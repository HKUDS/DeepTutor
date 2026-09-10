from __future__ import annotations

import asyncio

import pytest

from deeptutor.app.container import RuntimeRegistry
from deeptutor.app.service import TurnApplicationService
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import _TurnExecution


class _FixedStoreProvider:
    def __init__(self, store: SQLiteSessionStore) -> None:
        self.store = store

    def get(self) -> SQLiteSessionStore:
        return self.store


def _service(
    store: SQLiteSessionStore,
    coordinator: MemoryCoordinator,
    worker_id: str,
) -> tuple[TurnApplicationService, RuntimeRegistry]:
    registry = RuntimeRegistry(coordinator, worker_id)
    return (
        TurnApplicationService(_FixedStoreProvider(store), registry, coordinator),
        registry,
    )


@pytest.mark.asyncio
async def test_second_worker_reads_shared_event_tail_without_mutating_turn(tmp_path) -> None:
    db_path = tmp_path / "chat_history.db"
    owner_store = SQLiteSessionStore(db_path)
    subscriber_store = SQLiteSessionStore(db_path)
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    owner_service, owner_registry = _service(owner_store, coordinator, "worker-a")
    subscriber_service, _subscriber_registry = _service(subscriber_store, coordinator, "worker-b")

    session = await owner_store.ensure_session("shared-session")
    owner_runtime = owner_registry.get(owner_store)
    turn_id = "turn-shared-events"
    lease = await coordinator.acquire_turn(
        turn_id,
        f"{owner_runtime._coordination_scope}:{session['id']}",
        "worker-a",
    )
    assert lease is not None
    await owner_store.begin_turn(
        session["id"],
        capability="chat",
        turn_id=turn_id,
        owner_id="worker-a",
        fencing_token=lease.fencing_token,
    )
    await coordinator.publish_event(
        turn_id,
        {
            "type": "content",
            "content": "from worker a",
            "session_id": session["id"],
        },
    )
    await coordinator.publish_event(
        turn_id,
        {
            "type": "done",
            "content": "",
            "session_id": session["id"],
            "metadata": {"status": "completed"},
        },
    )

    active = await subscriber_service.check_active_turn(session["id"])
    assert active == {
        "turn_id": turn_id,
        "status": "running",
        "owner_id": "worker-a",
    }
    persisted = await subscriber_store.get_turn(turn_id)
    assert persisted is not None and persisted["status"] == "running"

    events = [event async for event in subscriber_service.subscribe_turn(turn_id)]
    assert [(event["seq"], event["type"]) for event in events] == [
        (1, "content"),
        (2, "done"),
    ]

    await owner_store.append_events(turn_id, events, fencing_token=lease.fencing_token)
    await owner_store.transition_turn(
        turn_id,
        "completed",
        expected_status="running",
        fencing_token=lease.fencing_token,
    )
    await coordinator.release_turn(lease)
    del owner_service


@pytest.mark.asyncio
async def test_durable_done_remains_terminal_when_post_turn_metadata_follows(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    service, _registry = _service(store, coordinator, "worker-a")
    session = await store.ensure_session("post-turn-metadata")
    turn = await store.begin_turn(session["id"], capability="chat")
    await store.append_events(
        turn["id"],
        [
            {
                "type": "done",
                "metadata": {"status": "completed"},
                "session_id": session["id"],
                "turn_id": turn["id"],
            },
            {
                "type": "session_meta",
                "stage": "title",
                "content": "Recovered title",
                "metadata": {"title": "Recovered title"},
                "session_id": session["id"],
                "turn_id": turn["id"],
            },
        ],
    )
    assert await store.update_turn_status(turn["id"], "completed") is True

    events = [event async for event in service.subscribe_turn(turn["id"], after_seq=0)]

    assert [(event["seq"], event["type"]) for event in events] == [
        (1, "done"),
        (2, "session_meta"),
    ]


@pytest.mark.asyncio
async def test_legacy_terminal_row_synthesizes_protocol_valid_done(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    service, _registry = _service(store, coordinator, "worker-a")
    session = await store.ensure_session("legacy-terminal")
    turn = await store.begin_turn(session["id"], capability="chat")
    assert await store.update_turn_status(turn["id"], "completed") is True

    events = [event async for event in service.subscribe_turn(turn["id"], after_seq=0)]

    assert len(events) == 1
    assert events[0]["type"] == "done"
    assert events[0]["seq"] == 1
    assert isinstance(events[0]["timestamp"], float)
    assert events[0]["metadata"]["synthesized"] is True


@pytest.mark.asyncio
async def test_second_worker_cancel_is_consumed_by_owner_worker(tmp_path) -> None:
    db_path = tmp_path / "chat_history.db"
    owner_store = SQLiteSessionStore(db_path)
    remote_store = SQLiteSessionStore(db_path)
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    _owner_service, owner_registry = _service(owner_store, coordinator, "worker-a")
    remote_service, _remote_registry = _service(remote_store, coordinator, "worker-b")

    session = await owner_store.ensure_session("shared-session")
    owner_runtime = owner_registry.get(owner_store)
    turn_id = "turn-remote-cancel"
    lease = await coordinator.acquire_turn(
        turn_id,
        f"{owner_runtime._coordination_scope}:{session['id']}",
        "worker-a",
    )
    assert lease is not None
    await owner_store.begin_turn(
        session["id"],
        capability="chat",
        turn_id=turn_id,
        owner_id="worker-a",
        fencing_token=lease.fencing_token,
    )

    execution = _TurnExecution(
        turn_id=turn_id,
        session_id=session["id"],
        capability="chat",
        payload={},
        lease=lease,
    )
    execution.task = asyncio.create_task(asyncio.Event().wait())
    owner_runtime._executions[turn_id] = execution
    execution.coordination_task = asyncio.create_task(
        owner_runtime._coordinate_execution(execution)
    )

    assert await remote_service.cancel_turn(turn_id, command_id="cancel-once") is True
    # A retry of an already accepted command is acknowledged as success so a
    # client that lost the first ACK can safely retire its outbox entry.
    assert await remote_service.cancel_turn(turn_id, command_id="cancel-once") is True
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(execution.task, timeout=1)
    await asyncio.wait_for(execution.coordination_task, timeout=1)

    # Command submission and observation are not allowed to write status; the
    # real owner coroutine performs that transition in its cancellation path.
    persisted = await remote_store.get_turn(turn_id)
    assert persisted is not None and persisted["status"] == "running"
    await owner_store.transition_turn(
        turn_id,
        "cancelled",
        expected_status="running",
        fencing_token=lease.fencing_token,
    )
    await coordinator.release_turn(lease)


@pytest.mark.asyncio
async def test_orphaned_waiting_input_is_closed_so_the_next_turn_can_start(
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    service, _registry = _service(store, coordinator, "worker-a")
    session = await store.ensure_session("orphaned-pause")
    turn = await store.begin_turn(session["id"], capability="chat")
    assert (
        await store.transition_turn(
            turn["id"],
            "waiting_input",
            expected_status="running",
        )
        is True
    )

    assert await service.submit_user_reply(turn["id"], "yes", command_id="reply-1") is False
    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["failure_code"] == "worker_lost"

    next_turn = await store.begin_turn(session["id"], capability="chat")
    assert next_turn["id"] != turn["id"]


@pytest.mark.asyncio
async def test_local_reply_queue_is_used_before_coordinator(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    service, registry = _service(store, coordinator, "worker-a")
    runtime = registry.get(store)
    session = await store.ensure_session("local-queue")
    turn = await store.begin_turn(session["id"], capability="chat")
    queue: asyncio.Queue = asyncio.Queue()
    runtime._reply_queues[turn["id"]] = queue
    lease = await coordinator.acquire_turn(
        turn["id"],
        f"{runtime._coordination_scope}:{session['id']}",
        "worker-a",
    )
    assert lease is not None

    assert await service.submit_user_reply(turn["id"], "picked", command_id="reply-local") is True
    payload = queue.get_nowait()
    assert payload["text"] == "picked"
    assert await service.submit_user_reply(turn["id"], "again", command_id="reply-local") is True
    assert queue.empty()
    await coordinator.release_turn(lease)
