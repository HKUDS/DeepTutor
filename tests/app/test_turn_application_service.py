from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.app.container import RuntimeRegistry
from deeptutor.app.service import TurnApplicationService
from deeptutor.core.stream import StreamEvent, StreamEventType
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


@pytest.fixture
def submission_service(monkeypatch, tmp_path):
    from deeptutor.services.path_service import PathService
    from deeptutor.services.session.turns.title_service import SessionTitleService

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    monkeypatch.setattr(PathService, "_instance", PathService(workspace_root=tmp_path / "data"))
    calls = {"count": 0, "fail": False}

    class Builder:
        def __init__(self, *args, **kwargs):
            pass

        async def build(self, **kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class Orchestrator:
        async def handle(self, context):
            calls["count"] += 1
            if calls["fail"]:
                from deeptutor.services.llm.exceptions import LLMProviderTransportError

                raise LLMProviderTransportError("controlled upstream failure")
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                content="Recovered answer",
                source="chat",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr("deeptutor.services.session.context_builder.ContextBuilder", Builder)
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", Orchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store", lambda: SimpleNamespace(emit=noop)
    )
    monkeypatch.setattr(SessionTitleService, "_maybe_generate_session_title", noop)
    store = SQLiteSessionStore(tmp_path / "submissions.db")
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    service, registry = _service(store, coordinator, "worker-a")
    return service, store, coordinator, registry, calls


@pytest.mark.asyncio
async def test_lost_first_session_ack_replays_the_same_submission_after_worker_restart(
    submission_service,
):
    service, store, coordinator, _registry, calls = submission_service
    payload = {"content": "Hello", "client_submission_id": "lost-first-ack"}
    first_session, first_turn = await service.start_turn(payload)
    [event async for event in service.subscribe_turn(first_turn["id"])]
    restarted_store = SQLiteSessionStore(store.db_path)
    restarted, _ = _service(restarted_store, coordinator, "worker-b")
    second_session, second_turn = await restarted.start_turn(payload)
    assert second_session["id"] == first_session["id"]
    assert second_turn["id"] == first_turn["id"]
    assert calls["count"] == 1
    assert len(await store.list_sessions()) == 1
    assert [row["role"] for row in await store.get_messages(first_session["id"])] == [
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_failed_first_submission_resends_in_its_original_conversation_without_a_duplicate_user(
    submission_service,
):
    service, store, _coordinator, _registry, calls = submission_service
    payload = {"content": "Hello", "client_submission_id": "failed-first-ack"}
    calls["fail"] = True
    first_session, failed_turn = await service.start_turn(payload)
    [event async for event in service.subscribe_turn(failed_turn["id"])]
    original_user = await store.get_last_message(first_session["id"], role="user")
    assert original_user is not None
    calls["fail"] = False
    session, retried_turn = await service.start_turn(payload)
    events = [event async for event in service.subscribe_turn(retried_turn["id"])]
    assert session["id"] == first_session["id"]
    assert retried_turn["id"] != failed_turn["id"]
    rows = await store.get_messages(session["id"])
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["id"] == original_user["id"]
    done = next(event for event in events if event["type"] == "done")
    assert done["metadata"]["user_message_id"] == original_user["id"]
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_submission_key_cannot_be_reused_for_different_content(submission_service):
    service, store, _coordinator, _registry, calls = submission_service
    payload = {"content": "Hello", "client_submission_id": "same-key"}
    session, turn = await service.start_turn(payload)
    [event async for event in service.subscribe_turn(turn["id"])]
    with pytest.raises(RuntimeError, match="different request"):
        await service.start_turn({**payload, "content": "Changed input"})
    assert len(await store.list_sessions()) == 1
    assert calls["count"] == 1


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
