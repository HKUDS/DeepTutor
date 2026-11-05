"""Numbered assessments use durable cards, including resuming partial groups."""

import json

import pytest

from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.core.context import UnifiedContext
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
def test_numbered_prose_is_not_a_reason_to_redirect(text):
    assert (
        MasteryLoopCapability().finish_instruction(
            UnifiedContext(metadata={"mastery_mode": True}), text
        )
        is None
    )


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
    assert (
        MasteryLoopCapability().finish_instruction(
            UnifiedContext(metadata={"mastery_mode": True}), text
        )
        is None
    )


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
async def test_markdown_discussion_preserves_existing_card(service, monkeypatch):
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
    assert instruction is None
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


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_id", [None, "", " \t"])
@pytest.mark.parametrize("questions", [None, []])
async def test_blank_optional_arguments_allow_single_question(
    service, monkeypatch, resume_id, questions
):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    progress = service.store.load("path").model_copy(deep=True)
    progress.book_id = "new-path"
    progress.version = 0
    progress.pending_question = None
    service.save(progress)
    ended = []
    result = await tools.MasteryQuizTool().execute(
        _mastery_path_id="new-path",
        knowledge_point_id="one",
        question="What is one plus one?",
        expected_answer="2",
        question_type="open",
        options=[],
        questions=questions,
        pending_action="retain",
        resume_question_id=resume_id,
        replace_question_id="",
        replacement_request="",
        _end_turn_on_card=lambda: ended.append(True),
    )
    assert result.success, result.content
    question_id = result.metadata["mastery_question"]["question_id"]
    assert service.store.get_active_interaction("new-path").interaction_id == question_id
    assert service.store.load("new-path").quiz_attempts == []
    assert ended == [True]
    assert "expected_answer" not in json.dumps(result.metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("resume_id", ["parent", False, 0, [], {}])
async def test_nonblank_or_malformed_resume_id_still_requires_resume(
    service, monkeypatch, resume_id
):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    before = service.store.load("path").model_dump()
    interaction = service.store.get_active_interaction("path").model_dump()
    result = await tools.MasteryQuizTool().execute(
        _mastery_path_id="path", pending_action="retain", resume_question_id=resume_id
    )
    assert not result.success
    assert "requires pending_action='resume'" in result.content
    assert service.store.load("path").model_dump() == before
    assert service.store.get_active_interaction("path").model_dump() == interaction


@pytest.mark.asyncio
@pytest.mark.parametrize("questions", [[{}], [{}, {}, {}, {}, {}], {}])
async def test_nonempty_malformed_groups_are_not_treated_as_single_questions(
    service, monkeypatch, questions
):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    before = service.store.load("path").model_dump()
    result = await tools.MasteryQuizTool().execute(
        _mastery_path_id="path",
        knowledge_point_id="one",
        question="What is one plus one?",
        expected_answer="2",
        questions=questions,
    )
    assert not result.success
    assert "two to four" in result.content
    assert service.store.load("path").model_dump() == before
