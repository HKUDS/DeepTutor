from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.learning.storage import LearningStore
from deeptutor.services.courses import CourseService
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


def _mastery_chat_payload(session_id: str, path_id: str) -> dict:
    return {
        **_mastery_payload(session_id, path_id),
        "capability": "chat",
        "workspace_mode": "mastery_path",
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
async def test_has_live_executions_counts_placeholders_and_running_tasks(tmp_path) -> None:
    runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "chat_history.db"))
    runtime._executions["placeholder"] = SimpleNamespace(task=None)  # type: ignore[assignment]
    assert await runtime.has_live_executions() is True

    runtime._executions.clear()
    task = asyncio.create_task(asyncio.sleep(0))
    runtime._executions["running"] = SimpleNamespace(task=task)  # type: ignore[assignment]
    assert await runtime.has_live_executions() is True

    await task
    assert await runtime.has_live_executions() is False


@pytest.mark.asyncio
async def test_managed_update_reservation_is_atomic_with_turn_ownership(tmp_path) -> None:
    runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "chat_history.db"))
    reserved = object()

    assert await runtime.reserve_managed_update(lambda: reserved) is reserved
    runtime._managed_update_is_active = lambda: True  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="preparing an update"):
        await runtime._ensure_accepting_turns()

    runtime._managed_update_is_active = lambda: False  # type: ignore[method-assign]
    await runtime._ensure_accepting_turns()


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
async def test_replacing_subscription_does_not_synthesize_duplicate_done(tmp_path) -> None:
    """Cancelling an old replay subscription must leave termination to its replacement."""

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
    assert await store.update_turn_status(turn["id"], "completed") is True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == []


@pytest.mark.asyncio
async def test_subscribe_turn_does_not_mutate_remote_running_turn(tmp_path) -> None:
    """A subscriber may be on a different worker from the turn owner."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")

    events: list[dict] = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    persisted = await store.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "running"
    assert persisted["error"] == ""
    assert events == []


@pytest.mark.asyncio
async def test_subscribe_terminal_turn_synthesizes_protocol_valid_done(tmp_path) -> None:
    """A recovered terminal turn must emit a consumable monotonic DONE."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    assert await store.update_turn_status(turn["id"], "completed") is True

    events = [event async for event in runtime.subscribe_turn(turn["id"], after_seq=0)]

    assert len(events) == 1
    done = events[0]
    assert done["type"] == "done"
    assert done["turn_id"] == turn["id"]
    assert done["session_id"] == session["id"]
    assert done["seq"] == 1
    assert isinstance(done["timestamp"], float)
    assert done["metadata"] == {"status": "completed", "synthesized": True}


@pytest.mark.asyncio
async def test_subscribe_failed_turn_synthesizes_ordered_error_and_done(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    turn = await store.create_turn(session["id"], capability="chat")
    assert await store.update_turn_status(turn["id"], "failed", "provider failed") is True

    events = [event async for event in runtime.subscribe_turn(turn["id"], after_seq=0)]

    assert [event["type"] for event in events] == ["error", "done"]
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0]["metadata"]["turn_terminal"] is True
    assert events[1]["metadata"]["status"] == "failed"


@pytest.mark.asyncio
async def test_close_cancels_local_turns_and_wakes_subscribers(tmp_path) -> None:
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
    execution.task = asyncio.create_task(asyncio.Event().wait())
    runtime._executions[turn["id"]] = execution

    collected: list[dict] = []

    async def _collect() -> None:
        async for event in runtime.subscribe_turn(turn["id"]):
            collected.append(event)

    subscriber_task = asyncio.create_task(_collect())
    for _ in range(100):
        if execution.subscribers:
            break
        await asyncio.sleep(0.01)

    await runtime.close()
    await asyncio.wait_for(subscriber_task, timeout=1)

    assert execution.task.cancelled()
    assert collected == []
    assert await runtime.has_live_executions() is False


@pytest.mark.asyncio
async def test_start_turn_does_not_mutate_apparently_orphaned_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Only the recovery service may resolve a persisted active turn."""

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session(None)
    stale = await store.create_turn(session["id"], capability="chat")

    async def _noop_run_turn(_execution):
        return None

    monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)

    with pytest.raises(RuntimeError, match="active turn"):
        await runtime.start_turn(
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

    persisted = await store.get_turn(stale["id"])
    assert persisted is not None
    assert persisted["status"] == "running"


@pytest.mark.asyncio
async def test_start_turn_preserves_selection_tutor_runtime_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Selected text must survive public config validation into turn execution."""

    store = SQLiteSessionStore(tmp_path / "selection-tutor.db")
    runtime = TurnRuntimeManager(store)

    async def _noop_run_turn(_execution):
        return None

    monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)

    parent = await store.ensure_session(None)
    source_text = "系统会把代码和静态数据加载进内存。"
    source_message_id = await store.add_message(
        parent["id"],
        "assistant",
        source_text,
    )
    selected_context = {
        "selected_text": "把代码和静态数据加载进内存",
        "parent_session_id": parent["id"],
        "source_message_id": source_message_id,
        "source_message_text": "untrusted client fallback",
    }
    _, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "session_id": None,
            "capability": "chat",
            "content": "内存不会爆炸吗？",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "zh",
            "config": {"selection_tutor_context": selected_context},
        }
    )

    execution = runtime._executions[turn["id"]]
    resolved = execution.payload["selection_tutor_context"]
    assert resolved["selected_text"] == selected_context["selected_text"]
    assert resolved["source_message_text"] == source_text


@pytest.mark.asyncio
async def test_start_turn_persists_requested_course(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = SQLiteSessionStore(tmp_path / "course-chat.db")
    runtime = TurnRuntimeManager(store)
    course_service = CourseService(tmp_path / "courses")
    course = course_service.create(name="Operating Systems")

    monkeypatch.setattr("deeptutor.services.courses.get_course_service", lambda: course_service)

    async def _noop_run_turn(_execution):
        return None

    monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)

    session, _ = await runtime.start_turn(
        {
            "type": "start_turn",
            "session_id": None,
            "capability": "chat",
            "content": "Explain virtual memory",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {"_course_id": course.id},
        }
    )

    persisted = await store.get_session(session["id"])
    assert persisted is not None
    assert persisted["preferences"]["course_id"] == course.id


@pytest.mark.asyncio
async def test_selection_tutor_inherits_parent_course(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = SQLiteSessionStore(tmp_path / "course-tutor.db")
    runtime = TurnRuntimeManager(store)
    course_service = CourseService(tmp_path / "courses")
    course = course_service.create(name="Operating Systems")
    parent = await store.ensure_session(None)
    await store.update_session_preferences(parent["id"], {"course_id": course.id})
    source_text = "Load code and static data into memory before execution."
    source_message_id = await store.add_message(parent["id"], "assistant", source_text)

    monkeypatch.setattr("deeptutor.services.courses.get_course_service", lambda: course_service)

    async def _noop_run_turn(_execution):
        return None

    monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)

    child, _ = await runtime.start_turn(
        {
            "type": "start_turn",
            "session_id": None,
            "capability": "chat",
            "content": "Will memory explode?",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {
                "selection_tutor_context": {
                    "selected_text": "Load code and static data into memory",
                    "parent_session_id": parent["id"],
                    "source_message_id": source_message_id,
                    "source_message_text": "forged fallback",
                }
            },
        }
    )

    persisted = await store.get_session(child["id"])
    assert persisted is not None
    assert persisted["preferences"]["course_id"] == course.id
    assert persisted["preferences"]["parent_session_id"] == parent["id"]
    assert persisted["preferences"]["session_kind"] == "selection_tutor"


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


def _open_mastery_question(path_id: str, *, question_id: str = "q-1"):
    """A built path with one open choice question, answer key ``C``."""
    from deeptutor.learning.models import (
        KnowledgePoint,
        KnowledgeType,
        LearningModule,
        LearningProgress,
        PendingQuestion,
    )
    from deeptutor.learning.service import LearningService

    progress = LearningProgress(
        book_id=path_id,
        modules=[
            LearningModule(
                id="module-1",
                name="Routing",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp-1",
                        name="Adaptive routing",
                        type=KnowledgeType.MEMORY,
                        module_id="module-1",
                    )
                ],
            )
        ],
    )
    service = LearningService()
    service.store.save(progress)
    _, interaction, _ = service.register_question(
        path_id,
        PendingQuestion(
            question_id=question_id,
            knowledge_point_id="kp-1",
            prompt="What does the router do on a miss?",
            question_type="choice",
            options=[
                "A: give up and report no results",
                "B: lower the similarity threshold until something matches",
                "C: rewrite the query and retry",
                "D: jump back to the router with goto",
            ],
            expected_answer="C",
            explanation="A miss is feedback: rewrite the query and retry.",
        ),
    )
    return interaction


@pytest.mark.asyncio
async def test_card_answer_is_committed_before_the_turn_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """An answer from a question card is engine state before the tutor reads it.

    The card outlives the turn that posed it, so the answer arrives as the next
    turn's message. Committing it at turn start is what lets the tutor's first
    ``mastery_status`` report ``answered`` with the learner's own words instead
    of having to pair a bare "C" with a question from scrollback.
    """
    _isolate_learning_store(monkeypatch, tmp_path)
    from deeptutor.learning.models import InteractionStatus
    from deeptutor.learning.service import LearningService

    interaction = _open_mastery_question("shared")

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")
    hold = asyncio.Event()

    async def _hold_turn(_execution):
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    payload = {
        **_mastery_payload(session["id"], "shared"),
        "content": "C",
        "mastery_answer": {"question_id": interaction.interaction_id, "text": "C"},
    }
    _, turn = await runtime.start_turn(payload)

    committed = LearningService().store.get_active_interaction("shared")
    assert committed is not None
    assert committed.status is InteractionStatus.ANSWERED
    assert committed.user_answer == "C"

    await runtime.cancel_turn(turn["id"])
    LearningStore().release_path_lease("shared", turn_id=turn["id"])


@pytest.mark.asyncio
async def test_card_answer_is_ruled_on_before_the_tutor_speaks(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The verdict reaches the card in milliseconds, not after an LLM round.

    Everything it needs was registered when the question was posed, so making
    the learner watch their own pick until the tutor got around to calling
    ``mastery_grade`` was a wait for nothing. The ruling is published as the
    same ``mastery_grade`` tool result the card already reads, so it renders
    unchanged and survives a reload with the turn.
    """
    _isolate_learning_store(monkeypatch, tmp_path)
    interaction = _open_mastery_question("shared")

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")
    hold = asyncio.Event()

    async def _hold_turn(_execution):
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    _, turn = await runtime.start_turn(_mastery_payload(session["id"], "shared"))
    execution = runtime._executions[turn["id"]]

    grade = await runtime._grade_submitted_card_answer(
        execution,
        path_id="shared",
        answer={"question_id": interaction.interaction_id, "text": "C"},
    )

    assert grade is not None
    assert grade["is_correct"] is True
    result = grade["result"]
    assert result["correct_label"] == "C"
    assert result["explanation"].startswith("A miss is feedback")
    # The answer key travels to the card only now that the gate has ruled.
    published = [
        event
        for event in execution.events
        if event.get("type") == "tool_result"
        and (event.get("metadata") or {}).get("tool_metadata", {}).get("mastery_grade")
    ]
    assert len(published) == 1
    carried = published[0]["metadata"]["tool_metadata"]["mastery_grade"]["result"]
    assert carried["question_id"] == interaction.interaction_id
    assert carried["is_correct"] is True

    await runtime.cancel_turn(turn["id"])
    LearningStore().release_path_lease("shared", turn_id=turn["id"])


@pytest.mark.asyncio
async def test_declining_a_card_drops_the_question_before_the_tutor_speaks(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A question the learner declined is gone by the time the tutor reads.

    The engine holds one open question per path, so a question left open is the
    one the tutor's next ``mastery_quiz`` re-presents: without this the learner
    could never get past a question they did not want to answer.
    """
    _isolate_learning_store(monkeypatch, tmp_path)
    from deeptutor.learning.service import LearningService

    interaction = _open_mastery_question("shared")

    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")
    hold = asyncio.Event()

    async def _hold_turn(_execution):
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    _, turn = await runtime.start_turn(_mastery_payload(session["id"], "shared"))
    execution = runtime._executions[turn["id"]]

    # A card that is no longer the open question drops nothing: by then it is
    # one the learner cannot have been declining.
    assert (
        await runtime._skip_card_question(
            execution, path_id="shared", skip={"question_id": "some-other-question"}
        )
        is None
    )
    assert LearningService().store.get_active_interaction("shared") is not None

    skip = await runtime._skip_card_question(
        execution, path_id="shared", skip={"question_id": interaction.interaction_id}
    )

    assert skip is not None
    assert skip["skipped"] is True
    assert skip["question_id"] == interaction.interaction_id
    assert LearningService().store.get_active_interaction("shared") is None
    # The card reads the same channel a grade arrives on, so it can show that
    # this question was set aside rather than staying answerable forever.
    published = [
        event
        for event in execution.events
        if event.get("type") == "tool_result"
        and (event.get("metadata") or {}).get("tool_metadata", {}).get("mastery_skip_question")
    ]
    assert len(published) == 1

    await runtime.cancel_turn(turn["id"])
    LearningStore().release_path_lease("shared", turn_id=turn["id"])


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
async def test_chat_action_inside_mastery_keeps_path_binding_and_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")
    hold = asyncio.Event()

    async def _hold_turn(_execution):
        await hold.wait()

    monkeypatch.setattr(runtime, "_run_turn", _hold_turn)
    _, turn = await runtime.start_turn(_mastery_chat_payload(session["id"], "shared"))

    lease = LearningStore().get_path_lease("shared")
    assert lease is not None
    assert lease.turn_id == turn["id"]
    detail = await store.get_session(session["id"])
    assert detail is not None
    assert detail["preferences"]["workspace_mode"] == "mastery_path"
    assert detail["preferences"]["capability"] == "chat"

    await runtime.cancel_turn(turn["id"])
    LearningStore().release_path_lease("shared", turn_id=turn["id"])


@pytest.mark.asyncio
async def test_mastery_turn_rejects_session_from_an_unrelated_topic(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_learning_store(monkeypatch, tmp_path)
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    session = await store.ensure_session("session-1")
    await store.update_session_preferences(
        session["id"],
        {"mastery_path_id": "topic-a"},
    )
    LearningStore().bind_session("topic-a", session["id"])

    with pytest.raises(RuntimeError, match="mastery_session_topic_mismatch"):
        await runtime.start_turn(_mastery_payload(session["id"], "topic-b"))

    detail = await store.get_session(session["id"])
    assert detail is not None
    assert detail["preferences"]["mastery_path_id"] == "topic-a"
    assert await store.get_active_turn(session["id"]) is None
    assert LearningStore().path_id_for_session(session["id"]) == "topic-a"


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
async def test_mastery_path_does_not_steal_apparently_orphaned_lease(
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
    with pytest.raises(RuntimeError, match="mastery_path_busy"):
        await runtime.start_turn(_mastery_payload(new_session["id"], "shared"))

    persisted = await store.get_turn(stale_turn["id"])
    lease = LearningStore().get_path_lease("shared")
    assert persisted is not None
    assert persisted["status"] == "running"
    assert lease is not None
    assert lease.turn_id == stale_turn["id"]
    LearningStore().release_path_lease("shared", turn_id=stale_turn["id"])


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
