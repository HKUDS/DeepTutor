"""Tests for mastery loop hooks that bind persisted pending questions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.mastery.capability import MasteryPathCapability
from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
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


def test_pending_question_overrides_reauthored_ask_user_mapping(tmp_path, monkeypatch):
    _use_store_root(monkeypatch, tmp_path)
    progress = LearningProgress(book_id="path-1")
    progress.pending_question = PendingQuestion(
        question_id="stable-question",
        knowledge_point_id="kp-1",
        prompt="Which colour?",
        question_type="choice",
        expected_answer="B",
        options=["A: red", "B: blue"],
    )
    LearningStore().save(progress)

    rebound = MasteryLoopCapability().augment_kwargs(
        "ask_user",
        {
            "intro": "Keep this lead-in",
            "questions": [
                {
                    "id": "new-question",
                    "prompt": "Rewritten question",
                    "options": [
                        {"label": "A", "description": "blue"},
                        {"label": "B", "description": "red"},
                    ],
                }
            ],
        },
        _context(),
    )

    assert rebound == {
        "intro": "Keep this lead-in",
        "questions": [
            {
                "id": "stable-question",
                "prompt": "Which colour?",
                "options": [
                    {"label": "A", "description": "red"},
                    {"label": "B", "description": "blue"},
                ],
                "multi_select": False,
                "allow_free_text": True,
            }
        ],
    }


def test_ask_user_is_untouched_without_pending_question(tmp_path, monkeypatch):
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_progress_with_objective())
    authored = {"questions": [{"id": "clarify", "prompt": "Which scope?"}]}

    assert MasteryLoopCapability().augment_kwargs("ask_user", authored, _context()) == authored


@pytest.mark.asyncio
async def test_pause_and_resume_hooks_persist_interaction_boundaries(tmp_path, monkeypatch):
    _use_store_root(monkeypatch, tmp_path)
    pending = PendingQuestion(
        question_id="stable-question",
        knowledge_point_id="kp-1",
        prompt="Which colour?",
        question_type="choice",
        expected_answer="B",
        options=["A: red", "B: blue"],
    )
    LearningStore().save(_progress_with_objective())
    LearningService().register_question(
        "path-1",
        pending,
        session_id="session-1",
        turn_id="turn-2",
    )
    ask_user = {
        "questions": [
            {
                "id": "stable-question",
                "prompt": "Which colour?",
            }
        ]
    }
    capability = MasteryLoopCapability()

    await capability.on_user_pause(_context(), ask_user)
    awaiting = LearningStore().get_interaction("path-1", "stable-question")
    assert awaiting is not None
    assert awaiting.status == InteractionStatus.AWAITING_INPUT

    await capability.on_user_resume(
        _context(),
        ask_user,
        reply_text="fallback",
        answers=[{"questionId": "stable-question", "text": "B"}],
    )
    answered = LearningStore().get_interaction("path-1", "stable-question")
    assert answered is not None
    assert answered.status == InteractionStatus.ANSWERED
    assert answered.user_answer == "B"


@pytest.mark.asyncio
async def test_choice_clarifying_composer_text_does_not_commit_answer(tmp_path, monkeypatch):
    """Composer clarifying prose must not freeze a choice question as answered.

    Regression for #1004: typing "what is this?" into the composer used to
    persist as user_answer, after which mastery_grade could never map it to an
    option and the gate stalled forever.
    """
    _use_store_root(monkeypatch, tmp_path)
    pending = PendingQuestion(
        question_id="stable-question",
        knowledge_point_id="kp-1",
        prompt="Compute (2e^{iπ/3})³",
        question_type="choice",
        expected_answer="A",
        options=["A: -8", "B: -6", "C: 8", "D: -2"],
    )
    LearningStore().save(_progress_with_objective())
    LearningService().register_question(
        "path-1",
        pending,
        session_id="session-1",
        turn_id="turn-2",
    )
    ask_user = {"questions": [{"id": "stable-question", "prompt": pending.prompt}]}
    capability = MasteryLoopCapability()

    await capability.on_user_pause(_context(), ask_user)
    await capability.on_user_resume(
        _context(),
        ask_user,
        reply_text="为什么 B 不是正确答案？",
        answers=None,
    )

    still_open = LearningStore().get_interaction("path-1", "stable-question")
    assert still_open is not None
    assert still_open.status == InteractionStatus.AWAITING_INPUT
    assert still_open.user_answer == ""


@pytest.mark.asyncio
async def test_choice_composer_option_label_still_commits(tmp_path, monkeypatch):
    """Typing a readable option into the composer remains a valid commit."""
    _use_store_root(monkeypatch, tmp_path)
    pending = PendingQuestion(
        question_id="stable-question",
        knowledge_point_id="kp-1",
        prompt="Which colour?",
        question_type="choice",
        expected_answer="B",
        options=["A: red", "B: blue"],
    )
    LearningStore().save(_progress_with_objective())
    LearningService().register_question(
        "path-1",
        pending,
        session_id="session-1",
        turn_id="turn-2",
    )
    ask_user = {"questions": [{"id": "stable-question", "prompt": "Which colour?"}]}
    capability = MasteryLoopCapability()

    await capability.on_user_pause(_context(), ask_user)
    await capability.on_user_resume(_context(), ask_user, reply_text="选B", answers=None)

    answered = LearningStore().get_interaction("path-1", "stable-question")
    assert answered is not None
    assert answered.status == InteractionStatus.ANSWERED
    assert answered.user_answer == "选B"


@pytest.mark.asyncio
async def test_hooks_bind_to_the_open_interaction_not_the_card_id(tmp_path, monkeypatch):
    """A same-round mastery_quiz + ask_user leaves the model's id on the card.

    Every tool call in a round has its arguments bound before any of them runs,
    so nothing is persisted yet when ask_user is bound and its question keeps
    whatever id the model invented. Committing against that id used to raise
    StaleInteractionError out of the hook and kill the turn.
    """
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_progress_with_objective())
    LearningService().register_question(
        "path-1",
        PendingQuestion(
            question_id="persisted-id",
            knowledge_point_id="kp-1",
            prompt="Which colour?",
            expected_answer="B",
        ),
        session_id="session-1",
        turn_id="turn-2",
    )
    model_authored_card = {"questions": [{"id": "routing_choice", "prompt": "Which colour?"}]}
    capability = MasteryLoopCapability()

    await capability.on_user_pause(_context(), model_authored_card)
    await capability.on_user_resume(
        _context(),
        model_authored_card,
        reply_text="B",
        answers=[{"questionId": "routing_choice", "text": "B"}],
    )

    interaction = LearningStore().get_interaction("path-1", "persisted-id")
    assert interaction is not None
    assert interaction.status == InteractionStatus.ANSWERED
    assert interaction.user_answer == "B"


@pytest.mark.asyncio
async def test_hooks_are_inert_when_no_question_is_open(tmp_path, monkeypatch):
    """A generic clarification card must not invent an interaction."""
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_progress_with_objective())
    clarification = {"questions": [{"id": "clarify", "prompt": "Which scope?"}]}
    capability = MasteryLoopCapability()

    await capability.on_user_pause(_context(), clarification)
    await capability.on_user_resume(
        _context(), clarification, reply_text="the second one", answers=None
    )

    assert LearningStore().get_active_interaction("path-1") is None


@pytest.mark.asyncio
async def test_direct_capability_call_holds_path_lease(tmp_path, monkeypatch):
    _use_store_root(monkeypatch, tmp_path)
    observed = {}

    async def _observe_lease(_pipeline, context, _stream):
        observed["lease"] = LearningStore().get_path_lease(context.metadata["mastery_path_id"])

    monkeypatch.setattr(AgenticChatPipeline, "run", _observe_lease)
    context = _context()

    await MasteryPathCapability().run(context, StreamBus())

    lease = observed["lease"]
    assert lease is not None
    assert lease.session_id == "session-1"
    assert lease.turn_id == "turn-2"
    assert LearningStore().get_path_lease("path-1") is None
    assert LearningStore().list_session_ids("path-1") == ["session-1"]


def test_ask_user_card_never_marks_a_recommended_option(tmp_path, monkeypatch):
    """A quiz card must not point at its own answer.

    The generic ask_user contract tells the model to append "(Recommended)" to
    a suggested choice; on an assessment that marker is the answer key.
    """
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_progress_with_objective())
    authored = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Which one holds?",
                "options": [
                    {"label": "B（推荐）", "description": "the right one（推荐）"},
                    {"label": "A (Recommended)", "description": "a distractor"},
                    {"label": "C", "description": "another distractor"},
                ],
            }
        ]
    }

    bound = MasteryLoopCapability().augment_kwargs("ask_user", authored, _context())

    labels = [option["label"] for option in bound["questions"][0]["options"]]
    assert labels == ["B", "A", "C"]
    assert "推荐" not in json.dumps(bound, ensure_ascii=False)
    assert "Recommended" not in json.dumps(bound)


def test_stripping_hints_leaves_ordinary_option_text_alone(tmp_path, monkeypatch):
    _use_store_root(monkeypatch, tmp_path)
    LearningStore().save(_progress_with_objective())
    authored = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Which one?",
                "options": [
                    # "推荐" mid-sentence is subject matter, not a marker.
                    {"label": "推荐系统", "description": "Recommended reading is a use case"},
                ],
            }
        ]
    }

    bound = MasteryLoopCapability().augment_kwargs("ask_user", authored, _context())

    assert bound["questions"][0]["options"][0] == {
        "label": "推荐系统",
        "description": "Recommended reading is a use case",
    }


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
    from deeptutor.core.agentic.tool_dispatch import dispatch_tool_calls

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
