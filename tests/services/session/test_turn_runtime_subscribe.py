from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import (
    TurnRuntimeManager,
    _resolve_turn_outcome,
    _TurnExecution,
)


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
