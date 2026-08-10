from __future__ import annotations

import asyncio

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.agents.research.recovery import seal_checkpoint
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import (
    TurnRuntimeManager,
    _resolve_turn_outcome,
    _TurnExecution,
)


class _ControlledOrchestrator:
    events: list[StreamEvent] = []
    exception: Exception | None = None
    checkpoint: dict | None = None

    async def handle(self, context):
        if self.checkpoint is not None:
            context.metadata["_research_attempt_checkpoint"] = self.checkpoint
        if self.exception is not None:
            raise self.exception
        for event in self.events:
            yield event


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


@pytest.mark.asyncio
async def test_runtime_persisted_assistant_excludes_opaque_continuation(monkeypatch, tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "opaque.db")
    runtime = TurnRuntimeManager(store)
    opaque_continuation = "opaque-SENTINEL"
    _ControlledOrchestrator.exception = None
    _ControlledOrchestrator.events = [
        StreamEvent(type=StreamEventType.CONTENT, source="chat", content="normal"),
        StreamEvent(
            type=StreamEventType.RESULT,
            source="chat",
            metadata={
                "response": "normal",
                "continuation_items": [opaque_continuation],
            },
        ),
        StreamEvent(type=StreamEventType.DONE, source="chat", metadata={"status": "completed"}),
    ]
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _ControlledOrchestrator)
    _, turn = await runtime.start_turn({"capability": "chat", "content": "hello", "tools": [], "knowledge_bases": [], "language": "en"})
    await runtime._executions[turn["id"]].task
    messages = await store.get_messages(turn["session_id"])
    assert opaque_continuation not in repr(messages)
    assert opaque_continuation not in repr(await store.get_turn_events(turn["id"]))


@pytest.mark.asyncio
async def test_runtime_research_secret_is_sanitized_before_history(monkeypatch, tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "secret.db")
    runtime = TurnRuntimeManager(store)
    _ControlledOrchestrator.events = []
    _ControlledOrchestrator.exception = RuntimeError(
        "https://secret.invalid bearer-SECRET"
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _ControlledOrchestrator)
    _, turn = await runtime.start_turn({"capability": "deep_research", "content": "hello", "tools": [], "knowledge_bases": [], "language": "en", "config": {"mode": "report", "depth": "quick"}})
    await runtime._executions[turn["id"]].task
    saved = repr(await store.get_messages(turn["session_id"]))
    events = repr(await store.get_turn_events(turn["id"]))
    persisted_turn = await store.get_turn(turn["id"])
    assert "secret.invalid" not in saved + events + repr(persisted_turn)
    assert "bearer-SECRET" not in saved + events + repr(persisted_turn)
    assert "Research could not be completed." in saved + events + repr(persisted_turn)


@pytest.mark.parametrize(
    "code", ["model_output_incomplete", "research_planning_failed", "model_output_empty"]
)
@pytest.mark.asyncio
async def test_runtime_reloads_durable_planning_failure_checkpoint(
    monkeypatch, tmp_path, code: str
) -> None:
    db_path = tmp_path / f"planning-{code}.db"
    store = SQLiteSessionStore(db_path)
    runtime = TurnRuntimeManager(store)
    failure = {
        "code": code, "stage": "decomposing", "summary": "Safe planning failure.",
        "retryable": code == "model_output_incomplete", "termination": {},
        "retry_strategy": "full_research",
    }
    checkpoint = seal_checkpoint({
        "schema_version": 1, "attempt_id": f"attempt_{code}", "strategy": "full_research",
        "input": {"topic": "hello", "confirmed_outline": []}, "blocks": [],
        "citations": [], "report": {"outcome": "failed", "content": ""},
        "failure": failure,
    })
    _ControlledOrchestrator.exception = None
    _ControlledOrchestrator.checkpoint = checkpoint
    _ControlledOrchestrator.events = [
        StreamEvent(
            type=StreamEventType.RESULT, source="deep_research",
            metadata={
                "response": "", "metadata": {
                    "outcome": "failed", "attempt_id": f"attempt_{code}", "failure": failure,
                },
            },
        ),
        StreamEvent(
            type=StreamEventType.ERROR, source="deep_research",
            content="Safe planning failure.",
            metadata={
                "turn_terminal": True, "status": "failed", "failure_code": code,
                "attempt_id": f"attempt_{code}",
            },
        ),
        StreamEvent(
            type=StreamEventType.DONE, source="deep_research", metadata={"status": "failed"}
        ),
    ]
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", _ControlledOrchestrator)
    _, turn = await runtime.start_turn({
        "capability": "deep_research", "content": "hello", "tools": [],
        "knowledge_bases": [], "language": "en",
        "config": {"mode": "report", "depth": "quick"},
    })
    await runtime._executions[turn["id"]].task

    reloaded = SQLiteSessionStore(db_path)
    messages = await reloaded.get_messages(turn["session_id"])
    assistant = next(message for message in messages if message["role"] == "assistant")
    assert assistant["metadata"]["research_attempt"]["failure"]["code"] == code
    assert assistant["metadata"]["research_attempt"]["blocks"] == []
    assert [event["type"] for event in assistant["events"][-2:]] == ["result", "error"]
    persisted_turn = await reloaded.get_turn(turn["id"])
    assert persisted_turn is not None and persisted_turn["status"] == "failed"
    assert persisted_turn["error"] == "Safe planning failure."


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
