"""A demonstrated pass survives later partial or wrong attempts, and a targeted
completion of a partial answer is a correction, not new independent evidence
(#2458).

The gate is earned only by independent attempts. Once that evidence has
cleared it, later attempts keep shaping the recent quality score and the
spaced-repetition schedule, but they no longer push the objective back into
re-learning. Before the pass nothing changes: incomplete or wrong answers keep
the objective below its gate.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.mastery import compute_mastery
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.policy import (
    find_knowledge_point,
    is_assessed_mastered,
    is_mastered,
    next_objective,
    reviewable_tasks,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

# Result sequence from the follow-up on #2458: 1.0 = correct, 0.5 = partial,
# 0.0 = incorrect, every attempt independent.
REPORTED = [0, 1, 0.5, 1, 1, 1, 0.5, 1, 0.5, 1, 0.5, 0.5, 1]
_RESULT = {1: "correct", 0.5: "partial", 0: "incorrect"}


def _progress(kind: KnowledgeType = KnowledgeType.PROCEDURE) -> LearningProgress:
    progress = LearningProgress(book_id="synthetic")
    progress.modules = [
        LearningModule(
            id="m1",
            name="Module",
            order=0,
            knowledge_points=[
                KnowledgePoint(id="kp", name="Objective", type=kind, module_id="m1"),
                KnowledgePoint(id="kp2", name="Next objective", type=kind, module_id="m1"),
            ],
        )
    ]
    progress.current_module_id = "m1"
    progress.knowledge_types.update({"kp": kind, "kp2": kind})
    return progress


def _grade(service, progress, quality, *, kp="kp", independent=True):
    result = _RESULT[quality]
    index = len(progress.quiz_attempts)
    return service._apply_grade(
        progress,
        question_id=f"{kp}-q{index}",
        knowledge_point_id=kp,
        module_id="m1",
        user_answer=f"answer {index}",
        expected_answer="expected",
        question_type="short",
        scheduler=SpacedRepetitionScheduler(),
        assistance_used=not independent,
        verdict={
            "result": result,
            "is_correct": result == "correct",
            "final": True,
            "confidence": 0.95,
            "feedback": "",
        },
    )


def _kp(progress, kp_id="kp") -> KnowledgePoint:
    kp = find_knowledge_point(progress, kp_id)[0]
    assert kp is not None
    return kp


@pytest.fixture
def service(tmp_path):
    return LearningService(LearningStore(tmp_path))


# ── before a pass: honest gating is unchanged ─────────────────────────────


def test_initial_incomplete_answers_never_open_the_gate(service):
    progress = _progress()
    for _ in range(6):
        _grade(service, progress, 0.5)
    assert progress.mastery_levels["kp"] == pytest.approx(0.5)
    assert not is_assessed_mastered(progress, _kp(progress))
    assert next_objective(progress).knowledge_point_id == "kp"


def test_a_real_error_before_the_pass_keeps_the_objective_below_its_gate(service):
    progress = _progress()
    for quality in (1, 1, 0, 1):
        _grade(service, progress, quality)
    assert progress.mastery_levels["kp"] < 0.9
    assert not is_mastered(progress, _kp(progress))
    step = next_objective(progress)
    assert (step.knowledge_point_id, step.action) == ("kp", "practice")


def test_assisted_answers_cannot_earn_the_pass(service):
    progress = _progress()
    for _ in range(5):
        _grade(service, progress, 1, independent=False)
    assert not is_assessed_mastered(progress, _kp(progress))


# ── after a pass: recent quality is reported, the pass is kept ────────────


def test_reported_sequence_keeps_the_pass_earned_after_attempt_six(service):
    progress = _progress()
    levels, passed = [], []
    for quality in REPORTED:
        _grade(service, progress, quality)
        levels.append(progress.mastery_levels["kp"])
        passed.append(is_assessed_mastered(progress, _kp(progress)))

    # The recency-weighted score is still the honest recent quality ...
    assert levels[5] == pytest.approx(0.9125)
    assert levels[6] == pytest.approx(0.8125)
    assert levels[-1] == pytest.approx(0.7125)
    # ... but the pass earned at attempt 6 is not revoked by later partials.
    assert passed == [False] * 5 + [True] * 8
    step = next_objective(progress, now=0)
    assert step.knowledge_point_id != "kp" or step.action == "review"
    # Partials after the pass still reach the review schedule.
    assert progress.repetition_states["kp"].review_count == len(REPORTED)


def test_a_correct_answer_after_a_kept_failure_does_not_demote(service):
    """Freezing the stored level on failure is not enough (#2459): the next
    correct answer recomputes over a window that contains the failure."""
    progress = _progress(KnowledgeType.MEMORY)
    for _ in range(5):
        _grade(service, progress, 1)
    assert is_assessed_mastered(progress, _kp(progress))
    _grade(service, progress, 0.5)
    _grade(service, progress, 1)
    assert progress.mastery_levels["kp"] < 0.9
    assert is_assessed_mastered(progress, _kp(progress))


def test_passed_objective_with_failed_review_stays_reviewable(service):
    progress = _progress()
    for _ in range(3):
        _grade(service, progress, 1)
    _grade(service, progress, 0)
    state = progress.repetition_states["kp"]
    assert state.lapse_count == 1
    assert "kp" in {task.knowledge_point_id for task in reviewable_tasks(progress)}


def test_voiding_the_passing_evidence_removes_the_pass(service):
    progress = _progress()
    for _ in range(3):
        _grade(service, progress, 1)
    assert is_assessed_mastered(progress, _kp(progress))
    progress.quiz_attempts[-1].voided = True
    service._recompute_objective_state(progress, "kp", SpacedRepetitionScheduler())
    assert not is_assessed_mastered(progress, _kp(progress))


def test_study_mode_recovers_a_path_demoted_before_this_fix(service, tmp_path):
    """Persisted state from an older release: level already lowered to 0.7125."""
    progress = _progress()
    for quality in REPORTED:
        _grade(service, progress, quality)
    progress.mastery_levels["kp"] = 0.7125
    service.save(progress)

    loaded = service.store.load("synthetic")
    assert loaded.mastery_levels["kp"] == pytest.approx(0.7125)
    assert is_mastered(loaded, _kp(loaded))
    step = next_objective(loaded, now=0)
    assert step.knowledge_point_id == "kp2"
    assert step.action in {"probe", "teach"}


# ── targeted completion of a partial answer (tool level) ──────────────────


def _store_init_factory(root):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    from deeptutor.learning import semantic_assessment

    async def judge(_config, items):
        verdicts = {}
        for item in items:
            answer = item["answer"]
            result = "partial" if answer.startswith("PARTIAL") else "incorrect"
            verdicts[item["question_id"]] = semantic_assessment.Verdict(
                result=result, confidence=0.95, feedback="The yearly comparison is missing."
            )
        return verdicts

    monkeypatch.setattr(semantic_assessment, "judge_answers", judge)
    return "test_path"


async def _build(path_id):
    from deeptutor.tools.mastery_tool import MasteryBuildTool, MasteryStatusTool

    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[
            {
                "name": "Module",
                "knowledge_points": [
                    {"name": "Compare two plans", "type": "procedure"},
                    {"name": "Next step", "type": "procedure"},
                ],
            }
        ],
    )
    status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
    return status["next"]["knowledge_point_id"]


async def _ask(path_id, kp_id, *, expected="42", **extra):
    from deeptutor.tools.mastery_tool import MasteryQuizTool

    result = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        knowledge_point_id=kp_id,
        question="Compare both plans and show the annual difference.",
        expected_answer=expected,
        question_type="short",
        **extra,
    )
    return result


async def _answer(path_id, answer):
    from deeptutor.tools.mastery_tool import MasteryGradeTool

    return json.loads(
        (await MasteryGradeTool().execute(_mastery_path_id=path_id, answer=answer)).content
    )


def _load(path_id):
    return LearningService(LearningStore()).store.load(path_id)


@pytest.mark.asyncio
async def test_targeted_completion_corrects_without_independent_credit(path_id):
    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    partial = await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    assert partial["result"]["result"] == "partial"
    assert "completes_question_id" in partial["instruction"]
    before = _load(path_id).mastery_levels[kp_id]

    posed = await _ask(path_id, kp_id, expected="7", completes_question_id=partial["question_id"])
    assert posed.success, posed.content
    graded = await _answer(path_id, "7")

    assert graded["is_correct"] is True
    assert graded["result"]["independent"] is False
    progress = _load(path_id)
    first, completion = progress.quiz_attempts
    assert (first.result, first.independent) == ("partial", True)
    assert completion.independent is False
    assert completion.completes_question_id == partial["question_id"]
    assert progress.mastery_levels[kp_id] == before
    assert "fresh" in graded["instruction"]


@pytest.mark.asyncio
async def test_a_fresh_question_after_a_partial_is_independent_evidence(path_id):
    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    await _ask(path_id, kp_id, expected="9")
    graded = await _answer(path_id, "9")

    assert graded["result"]["independent"] is True
    progress = _load(path_id)
    assert [attempt.independent for attempt in progress.quiz_attempts] == [True, True]
    assert progress.mastery_levels[kp_id] == pytest.approx(compute_mastery([0.5, 1.0]))


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["unknown", "correct", "second", "stale"])
async def test_completion_link_is_refused_unless_it_names_an_open_partial(path_id, target):
    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    first = await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    question_id = {"unknown": "missing"}.get(target, first["question_id"])
    if target == "correct":
        await _ask(path_id, kp_id, expected="9")
        question_id = (await _answer(path_id, "9"))["question_id"]
    elif target == "stale":
        # A fresh attempt came in between: the old partial is no longer "the missing part".
        await _ask(path_id, kp_id, expected="9")
        await _answer(path_id, "9")
    elif target == "second":
        # A completion already exists: the same partial cannot be completed twice.
        await _ask(path_id, kp_id, expected="7", completes_question_id=question_id)
        await _answer(path_id, "7")

    refused = await _ask(path_id, kp_id, expected="8", completes_question_id=question_id)

    assert refused.success is False
    assert "completes_question_id" in refused.content


@pytest.mark.asyncio
async def test_a_wrong_or_partial_completion_is_still_independent_evidence(path_id):
    """The completion label must never hide a failure from the gate."""
    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    first = await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    await _ask(path_id, kp_id, expected="7", completes_question_id=first["question_id"])
    wrong = await _answer(path_id, "nonsense")

    assert wrong["is_correct"] is False
    assert wrong["result"]["independent"] is True
    attempts = _load(path_id).quiz_attempts
    assert [a.independent for a in attempts] == [True, True]


@pytest.mark.asyncio
async def test_a_correct_completion_is_assisted_evidence_for_every_gate(path_id):
    """Visual-task achievements read ``hints_used``; a completion must not open them."""
    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    first = await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    await _ask(path_id, kp_id, expected="7", completes_question_id=first["question_id"])
    await _answer(path_id, "7")

    assert _load(path_id).learning_evidence[-1].hints_used == 1


@pytest.mark.asyncio
async def test_completion_is_refused_for_question_groups(path_id):
    from deeptutor.tools.mastery_tool import MasteryQuizTool

    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    first = await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    leaf = {"knowledge_point_id": kp_id, "expected_answer": "1"}
    group = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        completes_question_id=first["question_id"],
        questions=[{**leaf, "question": "first part"}, {**leaf, "question": "second part"}],
    )
    leaf_label = await MasteryQuizTool().execute(
        _mastery_path_id=path_id,
        questions=[
            {**leaf, "question": "first part", "completes_question_id": first["question_id"]},
            {**leaf, "question": "second part"},
        ],
    )

    assert group.success is False and leaf_label.success is False


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_correct", [True, False])
async def test_repair_completion_rederives_independence_and_replay(path_id, initial_correct):
    kp_id = await _build(path_id)
    await _ask(path_id, kp_id)
    partial = await _answer(path_id, "PARTIAL: 42 but no annual comparison")
    await _ask(path_id, kp_id, expected="7", completes_question_id=partial["question_id"])
    graded = await _answer(path_id, "7" if initial_correct else "nonsense")
    service = LearningService(LearningStore())
    # Native correction, not a direct mutation: a correction toggles correctness
    # without the completion mark becoming assistance that never happened.
    corrected, _ = await service.repair_question_semantic(
        path_id,
        graded["question_id"],
        action="correct",
        reason="Correct the synthetic answer key",
        expected_answer="different" if initial_correct else "nonsense",
        scheduler=SpacedRepetitionScheduler(),
    )
    attempt = corrected.quiz_attempts[-1]
    assert attempt.is_correct is not initial_correct
    assert attempt.independent is initial_correct
    evidence = corrected.learning_evidence[-1]
    assert evidence.hints_used == (0 if initial_correct else 1)
    # The exact same receipt is replayed, no extra attempt.
    replay = await service.grade_interaction_semantic(
        path_id, answer="ignored", question_id=graded["question_id"]
    )
    assert replay[2] is True
    assert replay[1].result["independent"] is initial_correct
    assert len(replay[0].quiz_attempts) == 2


def test_native_registration_refuses_completion_groups(service):
    from deeptutor.learning.models import PendingQuestion
    from deeptutor.learning.service import MasteryInteractionError

    service.save(_progress())
    leaves = [
        PendingQuestion(
            question_id=f"g-{i}",
            knowledge_point_id="kp",
            prompt=f"part {i}",
            expected_answer="1",
            completes_question_id="partial" if i == 0 else "",
        )
        for i in range(2)
    ]
    group = PendingQuestion(
        question_id="g",
        knowledge_point_id="kp",
        question_type="group",
        questions=leaves,
    )
    with pytest.raises(MasteryInteractionError, match="not supported for groups"):
        service.register_question("synthetic", group)
