"""Numbered assessments use durable cards, including resuming partial groups."""

import json

import pytest

from deeptutor.capabilities.mastery.loop import _looks_like_multipart_assessment
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from deeptutor.learning.service import LearningService, MasteryInteractionError
from deeptutor.learning.storage import LearningStore


@pytest.mark.parametrize(
    "text",
    [
        "### 1. Topic\nWhat is alpha?\n\n### 2. Other topic\nWhat is beta?\nAnswer these numbered questions.",
        "**1. First**\nWhat is alpha?\n\n**2. Second**\nWhat is beta?\nVálaszolj számozva.",
        "1. What is alpha?\n2. What is beta?\nAnswer these.",
    ],
)
def test_multiline_numbered_assessment_requires_registered_card(text):
    assert _looks_like_multipart_assessment(text)


@pytest.mark.parametrize(
    "text",
    [
        "### 1. Why alpha?\nExplanation.\n### 2. Why beta?\nMore explanation.",
        "> ### 1. Topic\n> What is alpha?\n> ### 2. Topic\n> What is beta?\n> Answer these.",
        "```\n### 1. Topic\nWhat is alpha?\n### 2. Topic\nWhat is beta?\nAnswer these.\n```",
        "1. Alpha is useful.\n2. Beta is useful.\nAnswer these later if you want.",
        "### 1. What is alpha?\nVálaszolj számozva.",
    ],
)
def test_teaching_and_quoted_examples_are_not_assessments(text):
    assert not _looks_like_multipart_assessment(text)


@pytest.fixture
def service(tmp_path):
    svc = LearningService(LearningStore(tmp_path))
    svc.save(
        LearningProgress(
            book_id="path",
            modules=[
                LearningModule(
                    id="m",
                    name="Synthetic module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(id=key, name=key, module_id="m", type=KnowledgeType.MEMORY)
                        for key in ["one", "two"]
                    ],
                )
            ],
        )
    )
    parent = PendingQuestion(
        question_id="parent",
        knowledge_point_id="one",
        question_type="group",
        questions=[
            PendingQuestion(
                question_id=key,
                knowledge_point_id=key,
                module_id="m",
                prompt=f"Question {key}?",
                expected_answer="answer",
            )
            for key in ["one", "two"]
        ],
    )
    svc.register_question("path", parent)
    svc.mark_question_awaiting("path", interaction_id="parent")
    return svc


def test_resume_preserves_partial_answers_results_and_credit(service):
    service.grade_interaction("path", answer="", question_id="parent", answers={"one": "answer"})
    before = service.store.load("path").model_dump()
    saved = service.store.get_active_interaction("path").model_dump()
    progress, interaction, created = service.register_question(
        "path",
        None,
        pending_action="resume",
        resume_question_id="parent",
    )
    assert not created
    assert interaction.model_dump() == saved
    assert progress.model_dump() == before


@pytest.mark.parametrize("question_id", ["", "unknown", "one"])
def test_resume_rejects_noncurrent_parent_without_mutation(service, question_id):
    before = service.store.load("path").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.register_question(
            "path", None, pending_action="resume", resume_question_id=question_id
        )
    assert service.store.load("path").model_dump() == before


def test_resume_rejects_answered_group_until_grade_finishes(service):
    service.record_question_answer(
        "path", "", interaction_id="parent", answers={"one": "answer", "two": "answer"}
    )
    before = service.store.load("path").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.register_question(
            "path", None, pending_action="resume", resume_question_id="parent"
        )
    assert service.store.load("path").model_dump() == before


def test_resume_rejects_committed_partial_answer_until_grade_finishes(service):
    service.record_question_answer("path", "", interaction_id="parent", answers={"one": "answer"})
    before = service.store.load("path").model_dump()
    with pytest.raises(MasteryInteractionError, match="Grade the committed"):
        service.register_question(
            "path", None, pending_action="resume", resume_question_id="parent"
        )
    assert service.store.load("path").model_dump() == before


@pytest.mark.asyncio
async def test_tool_resumes_without_constructing_throwaway_question(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)

    async def forbidden(*args):
        raise AssertionError("Resume must not build a question or regenerate a key")

    monkeypatch.setattr(tools.MasteryQuizTool, "_build_question", forbidden)
    service.grade_interaction("path", answer="", question_id="parent", answers={"one": "answer"})
    ended = []
    result = await tools.MasteryQuizTool().execute(
        _mastery_path_id="path",
        pending_action="resume",
        resume_question_id="parent",
        _end_turn_on_card=lambda: ended.append(True),
    )
    assert result.success
    card = result.metadata["mastery_question"]
    assert card["question_id"] == "parent"
    receipt = result.metadata["mastery_grade"]
    assert receipt["replayed"] and not receipt["complete"]
    assert receipt["remaining_question_ids"] == ["two"]
    assert receipt["result"]["results"][0]["learner_answer"] == "answer"
    assert ended == [True]
    assert "expected_answer" not in json.dumps(result.metadata)
    assert len(service.store.load("path").quiz_attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"question": "Throwaway?"},
        {"questions": []},
        {"expected_answer": "secret"},
        {"replace_question_id": "parent"},
        {"pending_action": "retain"},
    ],
)
async def test_tool_resume_rejects_conflicting_payloads(service, monkeypatch, extra):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    before = service.store.load("path").model_dump()
    result = await tools.MasteryQuizTool().execute(
        **{
            "_mastery_path_id": "path",
            "pending_action": "resume",
            "resume_question_id": "parent",
            **extra,
        }
    )
    assert not result.success
    assert service.store.load("path").model_dump() == before


@pytest.mark.asyncio
async def test_guard_redirects_markdown_assessment_to_existing_card(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    context = UnifiedContext(
        user_message="Practice both", metadata={"mastery_mode": True, "mastery_path_id": "path"}
    )
    capability = MasteryLoopCapability()
    draft = "### 1. First\nWhat is alpha?\n### 2. Second\nWhat is beta?\nAnswer these."
    instruction = capability.finish_instruction(context, draft)
    assert "resume_question_id" in instruction
    kwargs = capability.augment_kwargs(
        "mastery_quiz",
        {
            "pending_action": "resume",
            "resume_question_id": "parent",
        },
        context,
    )
    result = await tools.MasteryQuizTool().execute(**kwargs)
    assert result.success
    assert result.metadata["mastery_question"]["question_id"] == "parent"
    assert capability.finish_instruction(context, "The questions are on your card.") is None
    assert service.store.load("path").quiz_attempts == []
