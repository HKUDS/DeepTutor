from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.learning.storage import LearningStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import (
    TurnRuntimeManager,
    _resolve_turn_outcome,
    _TurnExecution,
)


def _isolate_learning_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def _init(self, root=None):
        self._root = tmp_path / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)


def _mastery_payload(session_id: str, path_id: str) -> dict:
    return {
        "type": "start_turn",
        "session_id": session_id,
        "capability": "mastery_path",
        "mastery_path_id": path_id,
        "content": "continue",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }


def test_terminal_error_marks_turn_failed() -> None:
    error_message = "provider authentication failed"
    status, error = _resolve_turn_outcome(
        [
            {
                "type": "error",
                "content": error_message,
                "metadata": {"turn_terminal": True, "status": "failed"},
            }
        ],
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "failed"},
        ),
    )

    assert status == "failed"
    assert error == error_message


def test_non_terminal_error_keeps_completed_done_status() -> None:
    status, error = _resolve_turn_outcome(
        [
            {
                "type": "error",
                "content": "recoverable tool error",
                "metadata": {},
            }
        ],
        StreamEvent(
            type=StreamEventType.DONE,
            source="chat",
            metadata={"status": "completed"},
        ),
    )

    assert status == "completed"
    assert error == ""


@pytest.mark.asyncio
async def test_subscribe_turn_does_not_synthesize_done_for_running_turn(tmp_path) -> None:
    """A paused/replaced subscription must not make the UI think the turn ended."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    execution = _TurnExecution(
        turn_id=turn["id"],
        session_id=session["id"],
        capability="chat",
        payload={},
    )
    runtime._executions[turn["id"]] = execution

    events: list[dict] = []

    async def _collect() -> None:
        async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
            events.append(event)

    task = asyncio.create_task(_collect())
    for _ in range(200):
        if execution.subscribers:
            break
        await asyncio.sleep(0.01)

    assert execution.subscribers
    await execution.subscribers[0].queue.put(None)
    await asyncio.wait_for(task, timeout=1)

    assert events == []
    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "running"


@pytest.mark.asyncio
async def test_subscribe_turn_marks_orphan_running_turn_failed(tmp_path) -> None:
    """A DB-running turn with no in-process execution is stale after restart."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")

    events: list[dict] = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert "restart" in persisted["error"].lower()
    assert [event["type"] for event in events] == ["error", "done"]
    assert events[-1]["metadata"]["status"] == "failed"


@pytest.mark.asyncio
async def test_start_turn_clears_orphan_running_turn_before_create(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A stale active turn should not block the next user message after restart."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    stale = await store.create_turn(session["id"], capability="chat")

    async def _noop_run_turn(_execution):
        return None

    monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)

    _, new_turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "session_id": session["id"],
            "capability": "chat",
            "content": "hello",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
        }
    )

    assert new_turn["id"] != stale["id"]
    persisted = await store.get_turn(stale["id"])
    assert persisted is not None
    assert persisted["status"] == "failed"


@pytest.mark.asyncio
async def test_reconnect_after_turn_completion_still_carries_message_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A client that (re)subscribes after the turn already finished and its
    in-process execution was cleaned up must still get the persisted-id
    metadata on DONE, not just the bare status.

    This is the ``resume_from`` path: the WS drops mid-turn (network blip,
    backgrounded tab) and reconnects after the turn has already completed
    server-side. Without persisted ids on DONE, the reconnecting client can
    never run its optimistic-id reconcile swap for that turn -- the
    assistant reply stays a real, correctly-persisted row, but the client's
    local tree treats it as unreachable until a full session reload.
    """

    store = SQLiteSessionStore(tmp_path / "reconnect.db")
    runtime = TurnRuntimeManager(store)

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, _context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="hello there",
                metadata={"call_kind": "llm_final_response"},
            )

    async def _noop_title(**_kwargs):
        return None

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder",
        FakeContextBuilder,
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(runtime, "_maybe_generate_session_title", _noop_title)

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "what is 2+2?",
            "session_id": None,
            "capability": "chat",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
        }
    )
    turn_id = turn["id"]

    # No one ever subscribed while the turn ran -- ``_run_turn`` is an
    # independent task started inside ``start_turn``, so it runs (and its
    # ``finally`` pops ``execution`` from ``_executions``) regardless.
    execution = runtime._executions[turn_id]
    await execution.task
    assert turn_id not in runtime._executions

    messages = await store.get_messages(session["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    real_assistant_id = messages[1]["id"]

    # The client reconnects now and asks to catch up from the start.
    events = [event async for event in runtime.subscribe_turn(turn_id, after_seq=0)]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["metadata"].get("assistant_message_id") == real_assistant_id


@pytest.mark.asyncio
async def test_mastery_path_allows_only_one_live_turn_across_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    first_session = await store.ensure_session("session-1")
    second_session = await store.ensure_session("session-2")
    hold = asyncio.Event()

    async def _hold_turn(_execution):
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    _, first_turn = await runtime.start_turn(_mastery_payload(first_session["id"], "shared"))

    with pytest.raises(RuntimeError, match="mastery_path_busy"):
        await runtime.start_turn(_mastery_payload(second_session["id"], "shared"))

    lease = LearningStore().get_path_lease("shared")
    assert lease is not None
    assert lease.turn_id == first_turn["id"]
    rejected = await store.get_active_turn(second_session["id"])
    assert rejected is None

    await runtime.cancel_turn(first_turn["id"])
    LearningStore().release_path_lease("shared", turn_id=first_turn["id"])


@pytest.mark.asyncio
async def test_mastery_turn_takes_over_a_path_parked_on_ask_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A turn waiting on the learner must not lock the path forever."""
    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    first_session = await store.ensure_session("session-1")
    second_session = await store.ensure_session("session-2")
    parked = asyncio.Event()

    async def _park_turn(execution) -> None:
        # Mirrors the real turn: flag the ask_user pause, then wait for a
        # reply that never comes, then finalize like ``_run_turn`` does.
        execution.awaiting_user_reply = True
        try:
            await parked.wait()
        finally:
            execution.awaiting_user_reply = False
            await store.update_turn_status(execution.turn_id, "cancelled", "Turn cancelled")
            async with runtime._lock:
                runtime._executions.pop(execution.turn_id, None)

    monkeypatch.setattr(runtime, "_run_turn", _park_turn)
    _, parked_turn = await runtime.start_turn(_mastery_payload(first_session["id"], "shared"))
    while not runtime._executions[parked_turn["id"]].awaiting_user_reply:
        await asyncio.sleep(0)

    _, resuming_turn = await runtime.start_turn(_mastery_payload(second_session["id"], "shared"))

    superseded = await store.get_turn(parked_turn["id"])
    assert superseded is not None
    assert superseded["status"] == "cancelled"
    lease = LearningStore().get_path_lease("shared")
    assert lease is not None
    assert lease.turn_id == resuming_turn["id"]
    assert lease.session_id == second_session["id"]

    parked.set()
    await runtime.cancel_turn(resuming_turn["id"])
    LearningStore().release_path_lease("shared", turn_id=resuming_turn["id"])


@pytest.mark.asyncio
async def test_racing_mastery_start_does_not_steal_pre_task_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The execution marker must exist before the lease acquisition yields."""
    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    first_session = await store.ensure_session("session-1")
    second_session = await store.ensure_session("session-2")
    hold_turn = asyncio.Event()

    async def _hold_turn(_execution):
        await hold_turn.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    original_acquire = LearningStore.acquire_path_lease
    first_acquired = threading.Event()
    release_first_start = threading.Event()
    acquisition_count = 0
    count_lock = threading.Lock()

    def _controlled_acquire(self, *args, **kwargs):
        nonlocal acquisition_count
        lease = original_acquire(self, *args, **kwargs)
        with count_lock:
            acquisition_count += 1
            is_first = acquisition_count == 1
        if is_first:
            first_acquired.set()
            release_first_start.wait(timeout=5)
        return lease

    monkeypatch.setattr(LearningStore, "acquire_path_lease", _controlled_acquire)
    first_start = asyncio.create_task(
        runtime.start_turn(_mastery_payload(first_session["id"], "shared"))
    )
    assert await asyncio.to_thread(first_acquired.wait, 5)

    with pytest.raises(RuntimeError, match="mastery_path_busy"):
        await asyncio.wait_for(
            runtime.start_turn(_mastery_payload(second_session["id"], "shared")),
            timeout=2,
        )

    release_first_start.set()
    _, first_turn = await first_start
    persisted = await store.get_turn(first_turn["id"])
    assert persisted is not None
    assert persisted["status"] == "running"
    assert LearningStore().get_path_lease("shared").turn_id == first_turn["id"]

    await runtime.cancel_turn(first_turn["id"])


@pytest.mark.asyncio
async def test_mastery_path_recovers_restart_orphan_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    stale_session = await store.ensure_session("stale-session")
    stale_turn = await store.create_turn(stale_session["id"], capability="mastery_path")
    LearningStore().acquire_path_lease(
        "shared",
        stale_session["id"],
        stale_turn["id"],
    )

    runtime = TurnRuntimeManager(store)
    new_session = await store.ensure_session("new-session")
    hold = asyncio.Event()

    async def _hold_turn(_execution):
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    _, new_turn = await runtime.start_turn(_mastery_payload(new_session["id"], "shared"))

    recovered = await store.get_turn(stale_turn["id"])
    lease = LearningStore().get_path_lease("shared")
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert lease is not None
    assert lease.turn_id == new_turn["id"]

    await runtime.cancel_turn(new_turn["id"])
    LearningStore().release_path_lease("shared", turn_id=new_turn["id"])


@pytest.mark.asyncio
async def test_mastery_turn_cannot_steal_administrative_path_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_learning_store(monkeypatch, tmp_path)
    learning_store = LearningStore()
    learning_store.acquire_path_lease(
        "shared",
        "__path_api__",
        "api-operation",
        bind_session=False,
    )
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")

    try:
        with pytest.raises(RuntimeError, match="mastery_path_busy"):
            await runtime.start_turn(_mastery_payload(session["id"], "shared"))
        lease = learning_store.get_path_lease("shared")
        assert lease is not None
        assert lease.turn_id == "api-operation"
    finally:
        learning_store.release_path_lease("shared", turn_id="api-operation")


@pytest.mark.asyncio
async def test_a_mid_turn_path_switch_is_pushed_to_the_client(tmp_path) -> None:
    """Otherwise the composer keeps naming the path the turn started on."""
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    execution = _TurnExecution(
        turn_id="turn-1",
        session_id="session-1",
        capability="mastery_path",
        payload={},
    )

    await runtime._publish_mastery_path_change(
        execution,
        capability_name="mastery_path",
        started_on="calculus",
        ended_on="algebra",
    )

    pushed = [event for event in execution.events if event["type"] == "session_meta"]
    assert len(pushed) == 1
    assert pushed[0]["metadata"]["mastery_path_id"] == "algebra"


@pytest.mark.asyncio
async def test_no_path_push_when_the_turn_never_moved(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    execution = _TurnExecution(
        turn_id="turn-1", session_id="session-1", capability="mastery_path", payload={}
    )

    await runtime._publish_mastery_path_change(
        execution, capability_name="mastery_path", started_on="calculus", ended_on="calculus"
    )
    await runtime._publish_mastery_path_change(
        execution, capability_name="chat", started_on="", ended_on="algebra"
    )

    assert [event for event in execution.events if event["type"] == "session_meta"] == []
