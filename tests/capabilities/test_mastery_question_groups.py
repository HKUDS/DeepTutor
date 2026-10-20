"""One durable parent, independently graded leaves, no answer-key projection."""

import json

from pydantic import ValidationError
import pytest

from deeptutor.learning.models import (
    InteractionStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
)
from deeptutor.learning.pending import public_pending_question
from deeptutor.learning.question_card import build_question_card
from deeptutor.learning.service import LearningService, MasteryInteractionError
from deeptutor.learning.storage import LearningStore


def leaf(question_id="q1", kp_id="kp1", expected="alpha"):
    return PendingQuestion(
        question_id=question_id,
        knowledge_point_id=kp_id,
        module_id="m",
        prompt="Name this.",
        expected_answer=expected,
        explanation="PRIVATE explanation",
    )


def group():
    return PendingQuestion(
        question_id="g",
        knowledge_point_id="kp1",
        module_id="m",
        prompt="Two questions",
        question_type="group",
        questions=[leaf(), leaf("q2", "kp2", "beta")],
    )


@pytest.fixture
def service(tmp_path):
    svc = LearningService(LearningStore(tmp_path))
    svc.save(
        LearningProgress(
            book_id="p",
            modules=[
                LearningModule(
                    id="m",
                    name="Module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(id=kp, name=kp, type=KnowledgeType.MEMORY, module_id="m")
                        for kp in ["kp1", "kp2"]
                    ],
                )
            ],
        )
    )
    return svc


def test_group_public_projection_and_reload(service):
    _, interaction, created = service.register_question("p", group())
    assert created
    reloaded = service._store.get_interaction("p", interaction.interaction_id)
    assert [q.question_id for q in reloaded.question.questions] == ["q1", "q2"]
    public = public_pending_question(reloaded.question).to_dict()
    card = build_question_card(reloaded.question)
    assert len(public["questions"]) == len(card["questions"]) == 2
    serialized = json.dumps([public, card])
    assert "expected_answer" not in serialized and "PRIVATE" not in serialized


def test_independent_mixed_results_and_duplicate_credit(service):
    service.register_question("p", group())
    progress, interaction, replayed = service.grade_interaction(
        "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "wrong"}
    )
    assert not replayed
    assert [r["is_correct"] for r in interaction.result["results"]] == [True, False]
    assert len(progress.quiz_attempts) == len(progress.learning_evidence) == 2
    assert {a.question_id for a in progress.quiz_attempts} == {"q1", "q2"}
    assert progress.mastery_levels["kp1"] > progress.mastery_levels["kp2"]
    assert progress.pending_question is None
    replay, _, replayed = service.grade_interaction(
        "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "wrong"}
    )
    assert replayed and len(replay.quiz_attempts) == 2


@pytest.mark.parametrize(
    "answers",
    [{}, {"q1": "alpha", "q2": ""}, {"q1": "alpha", "q2": "beta", "other": "x"}],
)
def test_empty_or_unknown_answers_do_not_mutate(service, answers):
    service.register_question("p", group())
    before = service._store.load("p").model_dump()
    with pytest.raises(MasteryInteractionError):
        service.grade_interaction("p", answer="", question_id="g", answers=answers)
    assert service._store.load("p").model_dump() == before


def test_partial_answers_are_retained_and_graded_once_after_reload(service):
    service.register_question("p", group())
    recorded = service.record_question_answer(
        "p", "second only", interaction_id="g", answers={"q2": "beta"}
    )
    assert recorded.status == InteractionStatus.AWAITING_INPUT
    assert recorded.answers == {"q2": "beta"}
    reloaded = LearningService(LearningStore(service._store._root))
    progress, partial, replayed = reloaded.grade_interaction("p", answer="", question_id="g")
    assert not replayed
    assert partial.status == InteractionStatus.AWAITING_INPUT
    assert partial.result["complete"] is False
    assert partial.result["remaining_question_ids"] == ["q1"]
    assert partial.result["is_correct"] is None
    assert [result["question_id"] for result in partial.result["results"]] == ["q2"]
    assert [attempt.question_id for attempt in progress.quiz_attempts] == ["q2"]
    assert progress.pending_question.question_id == "g"
    replay, _, replayed = reloaded.grade_interaction(
        "p", answer="", question_id="g", answers={"q2": "beta"}
    )
    assert replayed and len(replay.quiz_attempts) == 1
    final, completed, replayed = reloaded.grade_interaction(
        "p", answer="", question_id="g", answers={"q1": "alpha"}
    )
    assert not replayed
    assert completed.status == InteractionStatus.GRADED
    assert completed.answers == {"q1": "alpha", "q2": "beta"}
    assert completed.result["complete"] is True
    assert completed.result["remaining_question_ids"] == []
    assert [r["question_id"] for r in completed.result["results"]] == ["q1", "q2"]
    assert len(final.quiz_attempts) == len(final.learning_evidence) == 2
    assert final.pending_question is None


def test_changed_partial_reply_rolls_back_without_affecting_siblings(service):
    service.register_question("p", group())
    service.grade_interaction("p", answer="", question_id="g", answers={"q2": "wrong"})
    before = service._store.load("p").model_dump()
    with pytest.raises(MasteryInteractionError, match="committed answer"):
        service.grade_interaction(
            "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "beta"}
        )
    assert service._store.load("p").model_dump() == before


def test_partial_leaf_repair_updates_parent_without_inventing_sibling_reply(service):
    service.register_question("p", group())
    service.grade_interaction("p", answer="", question_id="g", answers={"q2": "wrong"})
    service.repair_question(
        "p", "q2", action="correct", expected_answer="wrong", reason="Verified key correction"
    )
    parent = service._store.get_interaction("p", "g")
    assert parent.result["results"][0]["is_correct"] is True
    assert parent.result["results"][0].get("result") != "incorrect"
    assert parent.result["complete"] is False
    assert parent.question.questions[0].question_id == "q1"
    assert parent.question.questions[1].expected_answer == "wrong"
    assert parent.answers == {"q2": "wrong"}
    assert service._store.load("p").pending_question.questions[1].expected_answer == "wrong"
    service.repair_question("p", "q2", action="void", reason="Uncertain key")
    assert service._store.get_interaction("p", "g").result["results"][0]["is_correct"] is None
    assert service._store.load("p").pending_question.question_id == "g"


def test_third_answer_first_does_not_score_unanswered_questions(service):
    progress = service._store.load("p")
    progress.modules[0].knowledge_points.append(
        KnowledgePoint(id="kp3", name="third", type=KnowledgeType.MEMORY, module_id="m")
    )
    service.save(progress)
    pending = group()
    pending.questions.append(leaf("q3", "kp3", "gamma"))
    service.register_question("p", pending)
    progress, interaction, _ = service.grade_interaction(
        "p", answer="", question_id="g", answers={"q3": "gamma"}
    )
    assert [attempt.question_id for attempt in progress.quiz_attempts] == ["q3"]
    assert interaction.result["remaining_question_ids"] == ["q1", "q2"]
    assert interaction.status == InteractionStatus.AWAITING_INPUT


def test_partial_group_cannot_reuse_a_leaf_from_another_group(service):
    service.register_question("p", group())
    service.grade_interaction("p", answer="", question_id="g", answers={"q2": "beta"})
    replacement = group()
    replacement.question_id = "new-group"
    service.register_question("p", replacement, pending_action="replace", replace_question_id="g")
    before = service._store.load("p").model_dump()
    with pytest.raises(MasteryInteractionError, match="another interaction"):
        service.grade_interaction("p", answer="", question_id="new-group", answers={"q2": "beta"})
    assert service._store.load("p").model_dump() == before


@pytest.mark.asyncio
async def test_partial_grade_tool_and_status_preserve_child_identity(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    synced = []

    async def sync(**kwargs):
        synced.append(kwargs["pending"].question_id)

    monkeypatch.setattr(tools, "_sync_mastery_attempt_to_question_bank", sync)
    service.register_question("p", group())
    graded = await tools.MasteryGradeTool().execute(
        _mastery_path_id="p", question_id="g", answers={"q2": "beta"}
    )
    assert graded.success
    assert graded.metadata["mastery_grade"]["complete"] is False
    assert graded.metadata["mastery_grade"]["remaining_question_ids"] == ["q1"]
    assert synced == ["q2"]
    status = await tools.MasteryStatusTool().execute(_mastery_path_id="p")
    pending = status.metadata["mastery_status"]["pending_interaction"]
    assert pending["answers"] == {"q2": "beta"}
    assert pending["remaining_question_ids"] == ["q1"]
    assert "PRIVATE" not in json.dumps(pending)


def test_explicit_replacement_retains_abandoned_history(service):
    service.register_question("p", leaf("old"))
    with pytest.raises(MasteryInteractionError):
        service.register_question("p", group())
    _, _, created = service.register_question(
        "p", group(), pending_action="replace", replace_question_id="old"
    )
    assert created
    assert service._store.get_interaction("p", "old").status == InteractionStatus.ABANDONED
    assert not service._store.load("p").quiz_attempts


def test_invalid_group_leaf_objective_rolls_back_replacement(service):
    service.register_question("p", leaf("old"))
    bad = group()
    bad.questions[1].knowledge_point_id = "unknown"
    with pytest.raises(MasteryInteractionError):
        service.register_question("p", bad, pending_action="replace", replace_question_id="old")
    assert service._store.get_active_interaction("p").interaction_id == "old"


@pytest.mark.parametrize(
    "questions", [[leaf()], [leaf(), leaf()], [leaf(str(i)) for i in range(5)]]
)
def test_invalid_group_shape_rejected(questions):
    with pytest.raises(ValidationError):
        PendingQuestion(
            question_id="g", knowledge_point_id="kp1", question_type="group", questions=questions
        )


def test_native_single_compatibility(service):
    service.register_question("p", leaf())
    _, active, created = service.register_question("p", leaf("new"))
    assert not created and active.interaction_id == "q1"
    progress, interaction, _ = service.grade_interaction("p", answer="alpha", question_id="q1")
    assert interaction.result["is_correct"] is True
    assert len(progress.quiz_attempts) == 1


def test_group_rejects_duplicated_question_for_same_objective():
    with pytest.raises(ValidationError, match="distinct questions"):
        PendingQuestion(
            question_id="g",
            knowledge_point_id="kp1",
            question_type="group",
            questions=[leaf(), leaf("different-id")],
        )


@pytest.mark.asyncio
async def test_quiz_tool_group_and_grade_tool_use_independent_contract(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    synced = []

    async def sync(**kwargs):
        synced.append(kwargs["pending"].question_id)

    monkeypatch.setattr(tools, "_sync_mastery_attempt_to_question_bank", sync)
    result = await tools.MasteryQuizTool().execute(
        _mastery_path_id="p",
        questions=[
            {"knowledge_point_id": "kp1", "question": "First?", "expected_answer": "alpha"},
            {"knowledge_point_id": "kp2", "question": "Second?", "expected_answer": "beta"},
        ],
    )
    assert result.success
    card = result.metadata["mastery_question"]
    assert len(card["questions"]) == 2
    leaves = service._store.get_active_interaction("p").question.questions
    graded = await tools.MasteryGradeTool().execute(
        _mastery_path_id="p",
        question_id=card["question_id"],
        answers={q.question_id: q.expected_answer for q in leaves},
    )
    assert graded.success
    payload = graded.metadata["mastery_grade"]
    assert len(payload["result"]["results"]) == 2
    assert set(synced) == {q.question_id for q in leaves}


@pytest.mark.asyncio
async def test_replacement_requires_literal_current_learner_request(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    service.register_question("p", leaf("old"))
    kwargs = dict(
        _mastery_path_id="p",
        pending_action="replace",
        replace_question_id="old",
        replacement_request="Replace my question",
        _learner_message="Please explain",
        questions=[
            {"knowledge_point_id": "kp1", "question": "First?", "expected_answer": "alpha"},
            {"knowledge_point_id": "kp2", "question": "Second?", "expected_answer": "beta"},
        ],
    )
    result = await tools.MasteryQuizTool().execute(**kwargs)
    assert not result.success
    assert service._store.get_active_interaction("p").interaction_id == "old"
    kwargs["_learner_message"] = "Replace my question with two questions please"
    assert (await tools.MasteryQuizTool().execute(**kwargs)).success


def test_committed_group_answers_are_authoritative_after_reload(service):
    service.register_question("p", group())
    service.record_question_answer(
        "p", "display only", interaction_id="g", answers={"q1": "alpha", "q2": "wrong"}
    )
    reloaded = LearningService(LearningStore(service._store._root))
    stored = reloaded._store.get_active_interaction("p")
    assert stored.answers == {"q1": "alpha", "q2": "wrong"}
    with pytest.raises(MasteryInteractionError):
        reloaded.grade_interaction(
            "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "beta"}
        )
    _, interaction, _ = reloaded.grade_interaction("p", answer="", question_id="g")
    assert [r["is_correct"] for r in interaction.result["results"]] == [True, False]


def test_leaf_history_repair_does_not_change_sibling_credit(service):
    service.register_question("p", group())
    service.grade_interaction(
        "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "wrong"}
    )
    assert service._store.get_interaction("p", "q2").question.expected_answer == "beta"
    progress, _ = service.repair_question(
        "p", "q2", action="correct", expected_answer="wrong", reason="Verified key correction"
    )
    assert len(progress.quiz_attempts) == 2
    assert all(attempt.is_correct for attempt in progress.quiz_attempts)
    assert all(r["is_correct"] for r in service._store.get_interaction("p", "g").result["results"])
    assert service._store.get_interaction("p", "g").question.questions[1].expected_answer == "wrong"
    progress, _ = service.repair_question("p", "q2", action="void", reason="Uncertain key")
    assert progress.quiz_attempts[0].is_correct and not progress.quiz_attempts[0].voided
    assert progress.quiz_attempts[1].voided
    parent = service._store.get_interaction("p", "g")
    assert parent.result["results"][1]["is_correct"] is None
    assert parent.result["is_correct"] is None


def test_parent_repair_cannot_grant_aggregate_credit(service):
    service.register_question("p", group())
    with pytest.raises(MasteryInteractionError):
        service.repair_question(
            "p",
            "g",
            action="correct",
            expected_answer="anything",
            reason="Cannot apply aggregate key",
        )
    assert not service._store.load("p").quiz_attempts


def test_removing_second_objective_abandons_whole_group(service):
    service.register_question("p", group())
    progress = service._store.load("p")
    progress.modules[0].knowledge_points = progress.modules[0].knowledge_points[:1]
    service.replace_modules_for_path("p", progress.modules)
    assert service._store.load("p").pending_question is None
    assert service._store.get_interaction("p", "g").status == InteractionStatus.ABANDONED


def test_unrelated_outline_change_keeps_pending_group_snapshot(service):
    service.register_question("p", group())
    before = service._store.get_active_interaction("p").model_dump()
    progress = service._store.load("p")
    progress.modules[0].name = "Updated section title"
    service.replace_modules_for_path("p", progress.modules)
    assert service._store.get_active_interaction("p").model_dump() == before


def test_defer_second_objective_retires_group_without_mastery_credit(service):
    service.register_question("p", group())
    progress, _ = service.defer_objective("p", "kp2", note="Return later")
    assert progress.pending_question is None and not progress.quiz_attempts
    assert service._store.get_interaction("p", "g").status == InteractionStatus.ABANDONED


def test_different_group_cannot_silently_reuse_existing(service):
    service.register_question("p", group())
    different = group()
    different.questions[1].prompt = "An unrelated question?"
    with pytest.raises(MasteryInteractionError):
        service.register_question("p", different)


def test_stale_replace_id_and_stale_submission_cannot_change_new_pending(service):
    service.register_question("p", leaf("old"))
    with pytest.raises(MasteryInteractionError):
        service.register_question(
            "p", group(), pending_action="replace", replace_question_id="stale"
        )
    service.register_question("p", group(), pending_action="replace", replace_question_id="old")
    with pytest.raises(MasteryInteractionError):
        service.grade_interaction("p", answer="alpha", question_id="old")
    assert service._store.get_active_interaction("p").interaction_id == "g"


def test_unreadable_choice_does_not_mark_any_group_answer_wrong(service):
    pending = group()
    pending.questions[1] = PendingQuestion(
        question_id="q2",
        knowledge_point_id="kp2",
        prompt="Choose?",
        question_type="choice",
        expected_answer="A",
        options=[{"label": "A", "body": "right"}, {"label": "B", "body": "wrong"}],
    )
    service.register_question("p", pending)
    with pytest.raises(MasteryInteractionError):
        service.grade_interaction(
            "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "A or B"}
        )
    assert not service._store.load("p").quiz_attempts


def test_uncertain_visual_leaf_remains_ungraded_without_key_leak(service, monkeypatch):
    from deeptutor.learning import visual_practice

    pending = group()
    pending.questions[1].visual_context = {"task": "identification"}
    monkeypatch.setattr(
        visual_practice, "account_for_recent_assistance", lambda context, *_: context
    )
    monkeypatch.setattr(
        visual_practice, "evaluate_visual", lambda *_: ("ungraded", "Verify original image")
    )
    service.register_question("p", pending)
    progress, interaction, _ = service.grade_interaction(
        "p", answer="", question_id="g", answers={"q1": "alpha", "q2": "beta"}
    )
    assert len(progress.quiz_attempts) == 1
    result = interaction.result["results"][1]
    assert result["is_correct"] is None and result["result"] == "ungraded"
    assert result["correct_label"] == "" and "PRIVATE" not in json.dumps(result)
    assert interaction.result["is_correct"] is None


def test_group_definition_keeps_nested_answer_keys_sensitive():
    from deeptutor.capabilities.mastery.tools import MasteryQuizTool

    definition = MasteryQuizTool().get_definition()
    group_param = next(p for p in definition.parameters if p.name == "questions")
    assert group_param.sensitive
    assert group_param.items["properties"]["expected_answer"]["type"] == "string"


@pytest.mark.asyncio
async def test_grade_tool_cannot_redirect_stale_id_to_active_group(service, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: service)
    service.register_question("p", group())
    result = await tools.MasteryGradeTool().execute(
        _mastery_path_id="p", question_id="stale", answers={"q1": "alpha", "q2": "beta"}
    )
    assert not result.success
    assert not service._store.load("p").quiz_attempts
    assert service._store.get_active_interaction("p").interaction_id == "g"
