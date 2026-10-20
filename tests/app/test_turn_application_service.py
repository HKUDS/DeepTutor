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
async def test_subscriber_waits_for_owned_terminal_envelope_and_replays_after_eviction(tmp_path):
    """A slow subscriber must get the real DONE ids even across cleanup (#1971)."""
    store = SQLiteSessionStore(tmp_path / "turns.db")
    coordinator = MemoryCoordinator()
    service, _ = _service(store, coordinator, "worker")
    session = await store.ensure_session(None)
    lease = await coordinator.acquire_turn("owned-terminal", session["id"], "worker")
    assert lease is not None
    await store.begin_turn(
        session["id"],
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    await store.transition_turn(
        lease.turn_id, "completed", expected_status="running", fencing_token=lease.fencing_token
    )
    subscription = service.subscribe_turn(lease.turn_id)
    waiting = asyncio.create_task(anext(subscription))
    try:
        await asyncio.sleep(0.15)
        assert not waiting.done(), "live owner has not published the real DONE yet"
        done = await coordinator.publish_event(
            lease.turn_id,
            {
                "type": "done",
                "metadata": {"status": "completed", "assistant_message_id": "answer"},
            },
        )
        await store.append_events(lease.turn_id, [done], fencing_token=lease.fencing_token)
        await coordinator.release_turn(lease)
        await coordinator.acknowledge_expired_turn(lease.turn_id)
        received = await asyncio.wait_for(waiting, 2)
        assert received["metadata"]["assistant_message_id"] == "answer"
        assert not received["metadata"].get("synthesized")
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        await subscription.aclose()


@pytest.mark.asyncio
async def test_running_turn_flushes_visible_prefix_without_waiting_for_more_events(
    submission_service,
    monkeypatch,
):
    """A quiet model/tool must not leave already visible work only in RAM (#1971)."""
    service, store, coordinator, registry, _ = submission_service
    streamed = asyncio.Event()
    finish = asyncio.Event()

    class SlowOrchestrator:
        async def handle(self, context):
            yield StreamEvent(type=StreamEventType.CONTENT, content="visible prefix", source="chat")
            streamed.set()
            await finish.wait()
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", SlowOrchestrator)
    _, turn = await service.start_turn({"content": "Hello"})
    try:
        await asyncio.wait_for(streamed.wait(), 3)
        await asyncio.sleep(0.6)
        restarted = SQLiteSessionStore(store.db_path)
        events = await restarted.get_events(turn["id"])
        assert any(e.get("content") == "visible prefix" for e in events)
        assert (await restarted.get_turn(turn["id"]))["status"] == "running"
    finally:
        finish.set()
        [event async for event in service.subscribe_turn(turn["id"])]


@pytest.mark.asyncio
async def test_reconnect_after_done_keeps_the_live_post_turn_title(tmp_path):
    store = SQLiteSessionStore(tmp_path / "turns.db")
    coordinator = MemoryCoordinator()
    service, _ = _service(store, coordinator, "worker")
    session = await store.ensure_session(None)
    lease = await coordinator.acquire_turn("title-tail", session["id"], "worker")
    await store.begin_turn(
        session["id"],
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )
    done = await coordinator.publish_event(
        lease.turn_id,
        {
            "type": "done",
            "metadata": {"status": "completed"},
        },
    )
    await store.append_events(lease.turn_id, [done], fencing_token=lease.fencing_token)
    await store.transition_turn(
        lease.turn_id, "completed", expected_status="running", fencing_token=lease.fencing_token
    )
    stream = service.subscribe_turn(lease.turn_id)
    assert (await anext(stream))["type"] == "done"
    waiting = asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(0.05)
        assert not waiting.done(), "terminal status is not the end of the owned title tail"
        title = await coordinator.publish_event(
            lease.turn_id,
            {
                "type": "session_meta",
                "metadata": {"title": "Cell membrane"},
            },
        )
        await store.append_events(lease.turn_id, [title], fencing_token=lease.fencing_token)
        await coordinator.release_turn(lease)
        await coordinator.acknowledge_expired_turn(lease.turn_id)
        assert (await asyncio.wait_for(waiting, 2))["metadata"]["title"] == "Cell membrane"
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        await stream.aclose()


@pytest.mark.asyncio
async def test_replacement_endpoint_workflow_starts_once_and_branches_admitted_user(
    submission_service,
):
    service, store, _, _, calls = submission_service
    session, original_turn = await service.start_turn(
        {"content": "Original", "client_submission_id": "already-admitted"}
    )
    [event async for event in service.subscribe_turn(original_turn["id"])]
    payload = {
        "content": "Edited",
        "client_submission_id": "branch-edit",
        "session_id": session["id"],
    }
    receipt = await service.replace_submission("already-admitted", payload, start=True)
    assert receipt["status"] == "started"
    [event async for event in service.subscribe_turn(receipt["turn"]["id"])]
    replay = await service.replace_submission("already-admitted", payload, start=True)
    assert replay["turn"]["id"] == receipt["turn"]["id"]
    users = [row for row in await store.get_messages(session["id"]) if row["role"] == "user"]
    assert [row["content"] for row in users] == ["Original", "Edited"]
    assert users[0]["parent_message_id"] == users[1]["parent_message_id"]
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_edit_admitted_before_user_persistence_waits_for_cancellation(submission_service):
    service, store, _, _, calls = submission_service
    sid = await store.reserve_submission("before-user", "original-digest")
    original = await store.begin_turn(sid, submission_id="before-user")
    receipt = await service.replace_submission(
        "before-user",
        {
            "content": "Edited",
            "client_submission_id": "edit-before-user",
            "session_id": sid,
        },
        start=True,
    )
    assert (await store.get_turn(original["id"]))["status"] in {"cancelled", "failed"}
    [event async for event in service.subscribe_turn(receipt["turn"]["id"])]
    assert calls["count"] == 1
    assert [row["content"] for row in await store.get_messages(sid) if row["role"] == "user"] == [
        "Edited"
    ]


@pytest.mark.asyncio
async def test_reserved_edit_replays_exact_request_after_lost_receipt(submission_service):
    service, store, _, _, calls = submission_service
    payload = {
        "content": "Edited",
        "client_submission_id": "edited",
        "tools": ["reason"],
        "config": {},
        "attachments": [],
    }
    receipt = await service.replace_submission("unsent", payload)
    assert await service.replace_submission("unsent", payload) == receipt
    with pytest.raises(RuntimeError, match="superseded"):
        await service.start_turn({"content": "Original", "client_submission_id": "unsent"})
    session, turn = await service.start_turn({**payload, "session_id": receipt["session_id"]})
    [event async for event in service.subscribe_turn(turn["id"])]
    replay_session, replay_turn = await service.start_turn(payload)
    assert replay_session["id"] == session["id"]
    assert replay_turn["id"] == turn["id"]
    assert calls["count"] == 1


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


@pytest.mark.asyncio
async def test_replacement_availability_matches_configured_store_before_mutation(
    submission_service, monkeypatch
):
    from fastapi import HTTPException

    from deeptutor.api.routers import sessions
    from deeptutor.core.turn_request import TurnRequest

    service, store, _, _, calls = submission_service
    monkeypatch.setattr(sessions, "get_session_store", lambda: store)
    assert (await sessions.session_store_capabilities()).submission_replacement
    unsupported = SimpleNamespace()
    monkeypatch.setattr(sessions, "get_session_store", lambda: unsupported)
    monkeypatch.setattr(service, "_resolve", lambda: (unsupported, None))
    monkeypatch.setattr(sessions, "_turn_application_service", lambda: service)
    assert not (await sessions.session_store_capabilities()).submission_replacement
    body = sessions.SubmissionReplacementRequest(
        original_submission_id="original",
        request=TurnRequest(content="Edited", client_submission_id="edited"),
    )
    with pytest.raises(HTTPException) as error:
        await sessions.replace_submission(body)
    assert error.value.status_code == 501
    assert calls["count"] == 0
