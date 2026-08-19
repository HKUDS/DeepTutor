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
