"""Tests for mastery loop hooks that bind persisted pending questions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.mastery.capability import MasteryPathCapability
from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.capabilities.mastery.pipeline import MasteryLoopPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.runtime.stream_bus import StreamBus


def _use_store_root(monkeypatch, root: Path) -> None:
    def _init(self, root_arg=None):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)


def _context() -> UnifiedContext:
    return UnifiedContext(
        user_message="continue",
        session_id="session-1",
        metadata={"mastery_mode": True, "mastery_path_id": "path-1", "turn_id": "turn-2"},
    )


def _progress_with_objective() -> LearningProgress:
    return LearningProgress(
        book_id="path-1",
        modules=[
            LearningModule(
                id="module-1",
                name="Colours",
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id="kp-1",
                        name="Primary colours",
                        type=KnowledgeType.CONCEPT,
                        module_id="module-1",
                    )
                ],
            )
        ],
    )


_GRADED_REVIEW = """回答正确！你选择的 C 正是 Agentic RAG 的核心做法。

我们逐个看其他选项为什么不对：
- A. 直接返回“没找到”就结束，等于放弃了自愈能力。
- B. 无脑降低相似度阈值，会把噪声也召回进来。
- D. goto 语句与 Agentic 架构无关，是干扰项。

接下来我们看下一个知识点。"""


def test_graded_review_may_finish_in_prose():
    """Feedback on a graded answer is the reply, not a question in disguise.

    Reviewing the options one by one matches the plain-text-quiz heuristic
    exactly, and a rejected finish is discarded — so guarding it here left the
    learner with a mastery_grade card and no explanation at all.
    """
    capability = MasteryLoopCapability()
    context = _context()

    capability.augment_kwargs("mastery_quiz", {}, context)
    capability.augment_kwargs("mastery_grade", {}, context)

    assert capability.finish_instruction(context, _GRADED_REVIEW) is None


def test_open_question_still_allows_answering_the_learner():
    """A learner who asks something instead of answering deserves an answer.

    The card is already in front of them, so an open interaction is not proof
    that the tutor skipped a step — and the guard used to end such a turn in
    silence.
    """
    capability = MasteryLoopCapability()
    context = _context()

    capability.augment_kwargs("mastery_quiz", {}, context)

    assert capability.finish_instruction(context, "会的，路由失败时它会重写查询再试。") is None


def test_open_question_may_not_be_restated_in_prose():
    """Re-posing the open question as text is still redirected to the card."""
    capability = MasteryLoopCapability()
    context = _context()

    capability.augment_kwargs("mastery_quiz", {}, context)

    instruction = capability.finish_instruction(context, _GRADED_REVIEW)
    assert instruction is not None
    assert "mastery_grade" in instruction


def test_plain_text_quiz_is_redirected_to_the_card():
    """Posing a question as prose is still rejected before any grading."""
    instruction = MasteryLoopCapability().finish_instruction(_context(), _GRADED_REVIEW)
    assert instruction is not None
    assert "mastery_quiz" in instruction
    assert "ask_user" not in instruction


def test_announced_but_unposed_question_is_redirected():
    """An announced-but-unposed question is not a finished turn.

    Posing a question ends the turn, so a reply that only announces one leaves
    the learner reading a promise above an empty space with no way to answer.
    """
    instruction = MasteryLoopCapability().finish_instruction(
        _context(), "让我们通过这道题来看看你对状态定义的掌握程度："
    )
    assert instruction is not None
    assert "mastery_quiz" in instruction
    assert "SAME round" in instruction


def test_runtime_grading_also_frees_the_review_to_finish():
    """A ruling the runtime made counts as this turn having graded.

    A card answer is graded before the turn starts, so the tutor never calls
    ``mastery_grade`` for it — and reading only the tool-call flag put the
    option-by-option review that follows back under the plain-text-quiz guard,
    which discards it.
    """
    context = _context()
    context.metadata["mastery_card_grade"] = {"is_correct": True, "result": {}}

    assert MasteryLoopCapability().finish_instruction(context, _GRADED_REVIEW) is None


def test_reviewing_a_graded_attempt_is_not_an_announcement():
    """Discussing the question just graded must not be read as promising one."""
    capability = MasteryLoopCapability()
    context = _context()

    capability.augment_kwargs("mastery_quiz", {}, context)
    capability.augment_kwargs("mastery_grade", {}, context)

    assert capability.finish_instruction(context, "这道题的关键在于闭环反馈，你抓住了。") is None


def test_seed_hands_the_tutor_a_ruling_it_did_not_have_to_make():
    """The turn opens with the verdict already reached.

    A card answer is graded at turn start, so without this the tutor would
    open on a bare "C" with no open question to pair it with — and nothing
    left to grade.
    """
    context = _context()
    context.metadata["mastery_card_grade"] = {
        "is_correct": True,
        "mastered": False,
        "result": {"question_id": "q-1", "learner_answer": "C", "explanation": "why"},
    }

    seed = MasteryLoopCapability().pre_loop_seed(context)

    assert "already graded" in seed
    assert "correct" in seed
    assert "do not call mastery_grade" in seed
    assert "mastery_quiz" in seed


def test_seed_is_silent_when_the_turn_graded_nothing():
    assert MasteryLoopCapability().pre_loop_seed(_context()) == ""


def test_seed_tells_the_tutor_the_declined_question_is_already_gone():
    """A skipped card is settled before the turn starts, like a graded one.

    The tutor otherwise reads "let's skip this question", calls
    ``mastery_skip_question`` to find nothing open, and — not knowing the
    question was dropped — is liable to pose it again.
    """
    context = _context()
    context.metadata["mastery_card_skip"] = {"skipped": True, "question_id": "q-1"}

    seed = MasteryLoopCapability().pre_loop_seed(context)

    assert "already dropped it" in seed
    assert "do not call mastery_skip_question" in seed
    assert "no mastery credit" in seed


def test_seed_ignores_a_skip_that_dropped_nothing():
    context = _context()
    context.metadata["mastery_card_skip"] = {"skipped": False, "question_id": "q-1"}

    assert MasteryLoopCapability().pre_loop_seed(context) == ""


def test_ask_user_is_left_alone_in_mastery_mode(tmp_path, monkeypatch):
    """A clarifying card stays the card the tutor wrote.

    It used to be rewritten into whatever question the engine held open, on the
    theory that any card in this mode was really a quiz. Now the graded ones
    are posed by ``mastery_quiz``, so a card reaching ``ask_user`` is a
    clarifying question — and an open question no longer means the learner is
    mid-answer, since they are free to ask something else instead.
    """
    _use_store_root(monkeypatch, tmp_path)
    progress = _progress_with_objective()
    progress.pending_question = PendingQuestion(
        question_id="engine-question",
        knowledge_point_id="kp-1",
        prompt="Which colour is primary?",
        question_type="choice",
        options=["A: red", "B: green"],
        expected_answer="A",
    )
    LearningStore().save(progress)

    authored = {
        "questions": [
            {
                "id": "clarify-1",
                "prompt": "Which module do you want to revisit?",
                "options": [
                    {"label": "Routing", "description": "Start here (Recommended)"},
                    {"label": "Reranking", "description": "The later one"},
                ],
            }
        ]
    }

    assert MasteryLoopCapability().augment_kwargs("ask_user", authored, _context()) == authored


def test_read_source_is_owned_and_reads_the_topic_index_on_demand():
    """The tutor may call read_source itself; it must never see chat's index.

    ``read_source`` has to be mounted directly (not left to chat's
    explore_context pre-pass) so the model decides when to read a topic
    material instead of every material being force-read up front. Wiring it
    from ``source_index`` instead of ``mastery_topic_source_index`` would
    silently re-couple mastery to whatever a plain chat turn attached.
    """
    assert "read_source" in MasteryLoopCapability.owned_tools

    context = _context()
    context.metadata["source_index"] = {"nb-other": "unrelated chat attachment"}
    context.metadata["mastery_topic_source_index"] = {"bk-path-1-ch1": "chapter one text"}

    kwargs = MasteryLoopCapability().augment_kwargs(
        "read_source", {"source_id": "bk-path-1-ch1"}, context
    )

    assert kwargs["source_index"] == {"bk-path-1-ch1": "chapter one text"}


@pytest.mark.asyncio
async def test_mastery_sync_carries_provenance_to_question_bank(tmp_path, monkeypatch) -> None:
    from deeptutor.capabilities.mastery.tools import (
        _sync_mastery_attempt_to_question_bank,
    )
    import deeptutor.services.session as session_package
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(db_path=tmp_path / "sessions.db")
    monkeypatch.setattr(session_package, "get_sqlite_session_store", lambda: store)
    await store.create_session(session_id="session-1", title="Mastery")
    pending = PendingQuestion(
        question_id="stable-question",
        knowledge_point_id="kp-1",
        prompt="Which colour?",
        question_type="choice",
        expected_answer="B",
        options=["A: red", "B: blue"],
    )

    await _sync_mastery_attempt_to_question_bank(
        path_id="path-1",
        session_id="session-1",
        turn_id="turn-1",
        pending=pending,
        user_answer="A",
        is_correct=False,
        choice_options={"A": "red", "B": "blue"},
        correct_answer="B",
        material_title="Path A",
        section_title="Primary colours",
    )

    entries = await store.list_notebook_entries(source="mastery_path")
    assert entries["total"] == 1
    entry = entries["items"][0]
    assert entry["material_id"] == "path-1"
    assert entry["material_title"] == "Path A"
    assert entry["section_id"] == "kp-1"
    assert entry["section_title"] == "Primary colours"
    assert entry["resolved"] is False


@pytest.mark.asyncio
async def test_direct_capability_call_holds_path_lease(tmp_path, monkeypatch):
    _use_store_root(monkeypatch, tmp_path)
    observed = {}

    async def _observe_lease(_pipeline, context, _stream):
        observed["lease"] = LearningStore().get_path_lease(context.metadata["mastery_path_id"])

    monkeypatch.setattr(MasteryLoopPipeline, "run", _observe_lease)
    context = _context()

    await MasteryPathCapability().run(context, StreamBus())

    lease = observed["lease"]
    assert lease is not None
    assert lease.session_id == "session-1"
    assert lease.turn_id == "turn-2"
    assert LearningStore().get_path_lease("path-1") is None
    assert LearningStore().list_session_ids("path-1") == ["session-1"]


def test_only_path_switching_tools_get_a_handle_on_the_live_binding(tmp_path, monkeypatch):
    """The binder is the one thing that can move a turn between paths."""
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_progress_with_objective())
    capability = MasteryLoopCapability()
    context = _context()

    status_kwargs = capability.augment_kwargs("mastery_status", {}, context)
    switch_kwargs = capability.augment_kwargs("mastery_switch", {"path_id": "other"}, context)

    assert "_bind_active_path" not in status_kwargs
    assert status_kwargs["_mastery_path_id"] == "path-1"
    assert callable(switch_kwargs["_bind_active_path"])

    switch_kwargs["_bind_active_path"]("other")
    assert context.metadata["mastery_path_id"] == "other"
    # And the next tool call on this turn follows the new binding.
    assert capability.augment_kwargs("mastery_status", {}, context)["_mastery_path_id"] == "other"


# ---- reads must not create paths (#909) --------------------------------------


def _built_path(path_id: str, name: str = "Algebra") -> LearningProgress:
    return LearningProgress(
        book_id=path_id,
        modules=[
            LearningModule(
                id="m1",
                name=name,
                order=0,
                knowledge_points=[
                    KnowledgePoint(
                        id=f"{path_id}-kp1",
                        name="slope",
                        type=KnowledgeType.CONCEPT,
                        module_id="m1",
                    )
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_status_on_unknown_path_creates_nothing(tmp_path, monkeypatch):
    """A conversation that merely asks about its progress must leave no path.

    The turn's path id falls back to the conversation's own scratch id, so a
    creating read manufactured one empty path per fresh mastery chat (#909).
    """
    from deeptutor.capabilities.mastery.tools import MasteryStatusTool

    _use_store_root(monkeypatch, tmp_path)
    scratch_id = "unified_session_1787032617956"

    result = await MasteryStatusTool().execute(_mastery_path_id=scratch_id)

    assert json.loads(result.content)["status"] == "empty"
    assert LearningStore().list_all() == []
    assert LearningStore().exists(scratch_id) is False


@pytest.mark.asyncio
async def test_status_points_at_existing_paths_before_offering_to_build(tmp_path, monkeypatch):
    """With paths built elsewhere, the tutor must look for them, not replace them."""
    from deeptutor.capabilities.mastery.tools import MasteryStatusTool

    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_built_path("algebra-101"))

    result = await MasteryStatusTool().execute(_mastery_path_id="unified_session_123")

    payload = json.loads(result.content)
    assert payload["status"] == "empty"
    assert "mastery_paths" in payload["message"] and "mastery_switch" in payload["message"]
    # Still no path invented for this conversation.
    assert LearningStore().list_all() == ["algebra-101"]


@pytest.mark.asyncio
async def test_status_asks_which_path_when_several_could_be_meant(tmp_path, monkeypatch):
    """Picking one for the learner is how a conversation lands on the wrong course."""
    from deeptutor.capabilities.mastery.tools import MasteryStatusTool

    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_built_path("japanese-n2"))
    LearningStore().save(_built_path("english-writing"))

    result = await MasteryStatusTool().execute(_mastery_path_id="unified_session_123")

    message = json.loads(result.content)["message"]
    assert "ask the learner" in message and "do not pick for them" in message


@pytest.mark.asyncio
async def test_status_reports_no_paths_at_all_when_the_learner_has_none(tmp_path, monkeypatch):
    """The build prompt stays for a genuinely empty learner."""
    from deeptutor.capabilities.mastery.tools import MasteryStatusTool

    _use_store_root(monkeypatch, tmp_path)

    payload = json.loads((await MasteryStatusTool().execute(_mastery_path_id="fresh")).content)

    assert "mastery_build" in payload["message"]
    assert "mastery_switch" not in payload["message"]


@pytest.mark.asyncio
async def test_recording_tools_refuse_an_unbuilt_path_without_creating_it(tmp_path, monkeypatch):
    """quiz / grade / assess report the real problem instead of half-creating."""
    from deeptutor.capabilities.mastery.tools import (
        MasteryAssessTool,
        MasteryGradeTool,
        MasteryQuizTool,
    )

    _use_store_root(monkeypatch, tmp_path)

    quiz = await MasteryQuizTool().execute(
        _mastery_path_id="ghost",
        knowledge_point_id="kp-1",
        question="q?",
        expected_answer="a",
    )
    assess = await MasteryAssessTool().execute(
        _mastery_path_id="ghost", knowledge_point_id="kp-1", passed=True
    )
    grade = await MasteryGradeTool().execute(_mastery_path_id="ghost", answer="a")

    for result in (quiz, assess, grade):
        assert result.success is False
        assert "mastery_paths" in result.content
    assert LearningStore().list_all() == []


@pytest.mark.asyncio
async def test_a_switch_and_a_build_in_one_round_land_on_the_switched_path(tmp_path, monkeypatch):
    """The regression behind "my paths contaminate each other".

    Every tool call in a round has its arguments bound before any of them runs,
    so a ``mastery_switch`` + ``mastery_build`` round used to rebuild the map of
    the path the conversation was *leaving*: the learner edited path B's map and
    watched path A's map change instead. Driven through the real dispatcher so
    the ordering contract, not just the tool, is under test.
    """
    from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls

    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_built_path("path-a", name="Path A"))
    LearningStore().save(_built_path("path-b", name="Path B"))

    context = UnifiedContext(
        user_message="switch to path B and rebuild its map",
        session_id="session-1",
        metadata={"mastery_mode": True, "mastery_path_id": "path-a", "turn_id": "turn-1"},
    )
    capability = MasteryLoopCapability()
    pipeline = AgenticChatPipeline(language="en")

    await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "c1",
                "name": "mastery_build",
                "arguments": json.dumps(
                    {
                        "mode": "replace",
                        "modules": [
                            {
                                "name": "Rebuilt module",
                                "knowledge_points": [{"name": "New objective"}],
                            }
                        ],
                    }
                ),
            },
            {"id": "c2", "name": "mastery_switch", "arguments": '{"path_id": "path-b"}'},
        ],
        context=context,
        stream=StreamBus(),
        source="chat",
        stage="responding",
        iteration_index=0,
        kwarg_augmenter=pipeline._augment_tool_kwargs,
        rebinding_tools=frozenset(capability.rebinding_tools),
    )

    store = LearningStore()
    assert [m.name for m in store.load("path-b").modules] == ["Rebuilt module"]
    # The path the turn started on is untouched.
    assert [m.name for m in store.load("path-a").modules] == ["Path A"]


@pytest.mark.asyncio
async def test_a_mode_switch_and_a_quiz_in_one_round_use_the_new_mode(tmp_path, monkeypatch):
    """The regression behind "it asked a question, then answered it itself".

    ``mastery_mode`` repoints the turn exactly the way ``mastery_switch`` does,
    but it was not declared to the dispatcher as a rebinding tool — so it ran
    in the concurrent batch and ``mastery_quiz`` kept the mode bound before the
    switch. The prompt asks for precisely this round ("switch and get on with
    it"), and "继续学" at the end of an outline sitting produces it, so the
    quiz was refused for being in ``outline`` in the same round that left it.

    The tutor had already streamed the lead-in, no card appeared, and the turn
    carried on — which is one of the ways the question ends up answered in
    prose next to no card at all.
    """
    from deeptutor.runtime.agentic.tool_dispatch import dispatch_tool_calls

    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_built_path("path-a"))

    context = UnifiedContext(
        user_message="let's start studying",
        session_id="session-1",
        metadata={
            "mastery_mode": True,
            "mastery_path_id": "path-a",
            "mastery_session_mode": "outline",
            "turn_id": "turn-1",
        },
    )
    capability = MasteryLoopCapability()
    pipeline = AgenticChatPipeline(language="en")

    results = await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "c1",
                "name": "mastery_quiz",
                "arguments": json.dumps(
                    {
                        "knowledge_point_id": "path-a-kp1",
                        "question": "What is slope?",
                        "expected_answer": "rise over run",
                    }
                ),
            },
            {"id": "c2", "name": "mastery_mode", "arguments": '{"mode": "study"}'},
        ],
        context=context,
        stream=StreamBus(),
        source="chat",
        stage="responding",
        iteration_index=0,
        kwarg_augmenter=pipeline._augment_tool_kwargs,
        rebinding_tools=frozenset(capability.rebinding_tools),
    )

    quiz = next(message for message in results.tool_messages if message.get("tool_call_id") == "c1")
    assert "belongs to the" not in str(quiz.get("content", "")), quiz
    assert context.metadata["mastery_session_mode"] == "study"
