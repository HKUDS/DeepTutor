"""Tests for the Mastery Path policy — the per-type gate and the gate-driven
"what's next" decision that replaced the old linear stage march.

These assert the two Alpha-style principles the old engine violated:

* a HARD gate — an objective is not mastered (and never advanced past) until
  its evidence clears the threshold;
* compression — an already-proven objective is skipped, never re-taught.
"""

from __future__ import annotations

import time

import pytest

from deeptutor.learning import policy
from deeptutor.learning.models import (
    AttemptStatus,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    MasteryState,
    PendingQuestion,
    RepetitionState,
    ReviewState,
    ReviewTask,
    ServerGateResult,
)
from deeptutor.learning.scheduler import (
    FAILED_REVIEW_RETRY_DELAY_DAYS,
    PROVISIONAL_RETEACH_DELAY_DAYS,
    STABLE_MAINTENANCE_DELAY_DAYS,
)
from deeptutor.learning.tests.feynman_builders import (
    DAY,
    START,
    add_attempt,
    append_complete_chain,
    chain_evidence_ids,
    kp_progress,
    passing_assessment,
)


def _progress(*kps: KnowledgePoint) -> LearningProgress:
    progress = LearningProgress(book_id="b1")
    progress.modules = [LearningModule(id="m1", name="M1", order=0, knowledge_points=list(kps))]
    progress.current_module_id = "m1"
    for kp in kps:
        progress.knowledge_types[kp.id] = kp.type
    return progress


def _kp(kp_id: str, kp_type: KnowledgeType, name: str = "") -> KnowledgePoint:
    return KnowledgePoint(id=kp_id, name=name or kp_id, type=kp_type, module_id="m1")


# ── per-type gate ──────────────────────────────────────────────────────────


def test_memory_gate_requires_high_quantitative_mastery():
    kp = _kp("kp1", KnowledgeType.MEMORY)
    progress = _progress(kp)
    progress.mastery_levels["kp1"] = 0.8
    assert policy.is_mastered(progress, kp) is False
    progress.mastery_levels["kp1"] = 0.9
    assert policy.is_mastered(progress, kp) is True


def test_procedure_gate_uses_same_quantitative_bar():
    kp = _kp("kp1", KnowledgeType.PROCEDURE)
    progress = _progress(kp)
    progress.mastery_levels["kp1"] = 0.89
    assert policy.is_mastered(progress, kp) is False


def test_concept_gate_is_qualitative_not_quantitative():
    """A high accuracy score must NOT unlock a concept — only the qualitative
    flag does (a concept is gated by an explanation, not string matching)."""
    kp = _kp("kp1", KnowledgeType.CONCEPT)
    progress = _progress(kp)
    progress.mastery_levels["kp1"] = 1.0  # accuracy is high…
    assert policy.is_mastered(progress, kp) is False  # …but the gate is qualitative
    progress.qualitative_mastery["kp1"] = True
    assert policy.is_mastered(progress, kp) is True


def test_objective_status_new_learning_mastered():
    kp = _kp("kp1", KnowledgeType.MEMORY)
    progress = _progress(kp)
    assert policy.objective_status(progress, kp) == "new"
    from deeptutor.learning.models import QuizAttempt

    progress.quiz_attempts.append(
        QuizAttempt(question_id="q", knowledge_point_id="kp1", is_correct=False)
    )
    assert policy.objective_status(progress, kp) == "learning"
    progress.mastery_levels["kp1"] = 0.95
    assert policy.objective_status(progress, kp) == "mastered"


# ── next_objective: gate is the cursor, mastered objectives are skipped ─────


def test_next_objective_skips_mastered_and_returns_first_open():
    kp1, kp2 = _kp("kp1", KnowledgeType.MEMORY), _kp("kp2", KnowledgeType.MEMORY)
    progress = _progress(kp1, kp2)
    progress.mastery_levels["kp1"] = 0.95  # already proven -> compression
    step = policy.next_objective(progress)
    assert step.knowledge_point_id == "kp2"
    assert step.action == "probe"


def test_next_objective_new_is_probe_then_practice_when_seen():
    kp = _kp("kp1", KnowledgeType.PROCEDURE)
    progress = _progress(kp)
    assert policy.next_objective(progress).action == "probe"
    from deeptutor.learning.models import QuizAttempt

    progress.quiz_attempts.append(
        QuizAttempt(question_id="q", knowledge_point_id="kp1", is_correct=False)
    )
    assert policy.next_objective(progress).action == "practice"


def test_next_objective_qualitative_type_recommends_assess():
    kp = _kp("kp1", KnowledgeType.DESIGN)
    progress = _progress(kp)
    progress.qualitative_mastery["kp1"] = False  # seen but not passed
    assert policy.next_objective(progress).action == "assess"


def test_next_objective_pending_question_takes_precedence():
    kp = _kp("kp1", KnowledgeType.MEMORY)
    progress = _progress(kp)
    progress.pending_question = PendingQuestion(
        question_id="q1", knowledge_point_id="kp1", prompt="?", expected_answer="x"
    )
    step = policy.next_objective(progress)
    assert step.action == "answer_pending"
    assert step.pending_prompt == "?"


def test_next_objective_due_review_beats_new_ground():
    kp1, kp2 = _kp("kp1", KnowledgeType.MEMORY), _kp("kp2", KnowledgeType.MEMORY)
    progress = _progress(kp1, kp2)
    progress.mastery_levels["kp1"] = 0.95  # mastered, but due for review
    progress.review_queue = [
        ReviewTask(
            id="r1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=time.time() - 10,
            priority=1,
            state=RepetitionState(next_review_at=time.time() - 10),
        )
    ]
    step = policy.next_objective(progress)
    assert step.action == "review"
    assert step.knowledge_point_id == "kp1"


def test_next_objective_complete_when_all_mastered():
    kp = _kp("kp1", KnowledgeType.MEMORY)
    progress = _progress(kp)
    progress.mastery_levels["kp1"] = 0.95
    assert policy.next_objective(progress).action == "complete"


# ── map_summary ─────────────────────────────────────────────────────────────


def test_map_summary_counts_and_completion():
    kp1, kp2 = _kp("kp1", KnowledgeType.MEMORY), _kp("kp2", KnowledgeType.CONCEPT)
    progress = _progress(kp1, kp2)
    progress.mastery_levels["kp1"] = 0.95
    summary = policy.map_summary(progress)
    assert summary["counts"] == {"mastered": 1, "learning": 0, "new": 1, "total": 2}
    assert summary["complete"] is False
    progress.qualitative_mastery["kp2"] = True
    assert policy.map_summary(progress)["complete"] is True


# ── Feynman mastery/review projection (spec §6.2, §7.5) ─────────────────────


def _record_pass(progress, attempt, *, assessment_id="ra1", passed=True, created_at=None):
    """Append a recorded (server-computed) gate result to the attempt."""
    assessment = passing_assessment(
        attempt_id=attempt.id,
        assessment_id=assessment_id,
        evidence_ids=chain_evidence_ids(progress, attempt),
        created_at=created_at if created_at is not None else START + 50,
    )
    assessment.server_gate_result = ServerGateResult(passed=passed, reasons=["server gate (test)"])
    progress.rubric_assessments.append(assessment)
    return assessment


class TestProjectionMastery:
    def test_no_attempts_is_new_and_unscheduled(self):
        progress, _ = kp_progress()
        progress.attempts = []
        proj = policy.rebuild_projection(progress, "kp1", now=START)
        assert proj.mastery_state == MasteryState.NEW
        assert proj.review_state == ReviewState.UNSCHEDULED
        assert proj.next_review_at is None
        assert proj.provisional_since is None
        assert proj.stable_since is None

    def test_open_attempt_with_no_assessment_is_in_progress(self):
        progress, attempt = kp_progress()
        proj = policy.rebuild_projection(progress, "kp1", now=START)
        assert proj.mastery_state == MasteryState.IN_PROGRESS
        assert proj.review_state == ReviewState.UNSCHEDULED
        assert proj.active_attempt_id == attempt.id

    def test_open_attempt_with_only_invalidated_gates_is_in_progress(self):
        """An invalidated attempt's gate is ignored; a live open attempt keeps
        the projection in_progress rather than falling back to new."""
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.INVALIDATED  # gate no longer valid
        add_attempt(
            progress,
            attempt_id="a2",
            cycle_type="initial",
            status=AttemptStatus.COLLECTING,
            created_at=START + 100,
        )
        proj = policy.rebuild_projection(progress, "kp1", now=START + 100)
        assert proj.mastery_state == MasteryState.IN_PROGRESS
        assert proj.review_state == ReviewState.UNSCHEDULED
        assert proj.active_attempt_id == "a2"
        assert proj.latest_assessment_id == ""

    def test_initial_pass_is_provisional_never_stable(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.review_state == ReviewState.SCHEDULED
        assert proj.stable_since is None
        assert proj.latest_assessment_id == "ra1"

    def test_test_out_pass_is_provisional_only(self):
        progress, attempt = kp_progress(attempt_cycle="test_out")
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.review_state == ReviewState.SCHEDULED

    def test_delayed_reteach_pass_is_stable(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED

        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED

        proj = policy.rebuild_projection(progress, "kp1", now=START + 550)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY
        assert proj.stable_since == START + 550
        assert proj.provisional_since == START + 50
        assert proj.review_state == ReviewState.SCHEDULED

    def test_failed_review_projects_needs_revision(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED

        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", passed=False, created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED

        proj = policy.rebuild_projection(progress, "kp1", now=START + 550)
        assert proj.mastery_state == MasteryState.NEEDS_REVISION
        assert proj.review_state == ReviewState.SCHEDULED
        assert (
            proj.next_review_at
            == START + 550 + FAILED_REVIEW_RETRY_DELAY_DAYS[KnowledgeType.CONCEPT] * DAY
        )

    def test_stable_then_failed_review_keeps_history(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED

        review = add_attempt(
            progress, attempt_id="a3", cycle_type="delayed_reteach", chain_id="chain-3"
        )
        append_complete_chain(progress, review, start=START + 900)
        _record_pass(progress, review, assessment_id="ra3", passed=False, created_at=START + 950)
        review.status = AttemptStatus.ASSESSED

        proj = policy.rebuild_projection(progress, "kp1", now=START + 950)
        assert proj.mastery_state == MasteryState.NEEDS_REVISION
        # The historical stable record is preserved even though current is failed.
        assert proj.stable_since == START + 550

    def test_later_stable_recovery_after_failure(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", passed=False, created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        reteach2 = add_attempt(
            progress, attempt_id="a3", cycle_type="delayed_reteach", chain_id="chain-3"
        )
        append_complete_chain(progress, reteach2, start=START + 900)
        _record_pass(progress, reteach2, assessment_id="ra3", created_at=START + 950)
        reteach2.status = AttemptStatus.ASSESSED

        proj = policy.rebuild_projection(progress, "kp1", now=START + 950)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY

    def test_reevaluation_pass_never_grants_stable(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reeval = add_attempt(progress, attempt_id="a2", cycle_type="reevaluation")
        append_complete_chain(progress, reeval, start=START + 500)
        _record_pass(progress, reeval, assessment_id="ra2", created_at=START + 550)
        reeval.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 550)
        # A reevaluation pass confirms learning but is not a delayed reteach.
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.stable_since is None

    def test_reevaluation_pass_after_stable_keeps_stable(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        reeval = add_attempt(
            progress, attempt_id="a3", cycle_type="reevaluation", chain_id="chain-3"
        )
        append_complete_chain(progress, reeval, start=START + 900)
        _record_pass(progress, reeval, assessment_id="ra3", created_at=START + 950)
        reeval.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 950)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY

    def test_reevaluation_after_stable_keeps_maintenance_schedule(self):
        """A successful reevaluation of a stable learner keeps the next review
        on stable maintenance policy, not the shorter provisional reteach."""
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        reeval = add_attempt(
            progress,
            attempt_id="a3",
            cycle_type="reevaluation",
            chain_id="chain-3",
            created_at=START + 800,
        )
        append_complete_chain(progress, reeval, start=START + 900)
        _record_pass(progress, reeval, assessment_id="ra3", created_at=START + 950)
        reeval.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 950)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY
        assert proj.stable_since == START + 550
        assert (
            proj.next_review_at
            == START + 950 + STABLE_MAINTENANCE_DELAY_DAYS[KnowledgeType.CONCEPT] * DAY
        )

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_provisional_pass_schedules_type_specific_review(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.review_state == ReviewState.SCHEDULED
        assert proj.next_review_at == START + 50 + PROVISIONAL_RETEACH_DELAY_DAYS[kp_type] * DAY

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_delayed_reteach_schedules_maintenance_review(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 550)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY
        assert proj.review_state == ReviewState.SCHEDULED
        assert proj.next_review_at == START + 550 + STABLE_MAINTENANCE_DELAY_DAYS[kp_type] * DAY


class TestProjectionReview:
    def test_review_starts_change_review_only(self):
        """An open delayed-reteach attempt flips review to in_progress while
        mastery stays provisional."""
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        # A new delayed-reteach attempt is opened but not yet assessed.
        add_attempt(
            progress,
            attempt_id="a2",
            cycle_type="delayed_reteach",
            status=AttemptStatus.COLLECTING,
            created_at=START + 600,
        )
        proj = policy.rebuild_projection(progress, "kp1", now=START + 600)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.review_state == ReviewState.IN_PROGRESS
        assert proj.active_attempt_id == "a2"

    def test_due_is_derived_from_time(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        # Long after the scheduled reteach time, the review is due.
        later = START + 50 + PROVISIONAL_RETEACH_DELAY_DAYS[KnowledgeType.CONCEPT] * DAY + 1
        proj = policy.rebuild_projection(progress, "kp1", now=later)
        assert proj.review_state == ReviewState.DUE
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY

    def test_scheduled_review_is_not_due_before_time(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        proj = policy.rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.review_state == ReviewState.SCHEDULED
        assert proj.next_review_at > START + 50

    def test_project_all_covers_module_kps(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        projections = policy.project_all(progress, now=START + 50)
        assert set(projections) == {"kp1"}
        assert projections["kp1"].mastery_state == MasteryState.PROVISIONAL_MASTERY


class TestProjectionRebuildDeterminism:
    def test_rebuild_is_idempotent(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        first = policy.rebuild_projection(progress, "kp1", now=START + 50)
        second = policy.rebuild_projection(progress, "kp1", now=START + 50)
        assert first.model_dump() == second.model_dump()
        # And it does not mutate the progress.
        assert progress.projections == {}

    def test_rebuild_is_order_insensitive(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED

        # Shuffle the append-only lists; the projection must not change.
        progress.rubric_assessments.reverse()
        progress.attempts.reverse()
        proj = policy.rebuild_projection(progress, "kp1", now=START + 550)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY
        assert proj.latest_assessment_id == "ra2"

    def test_equal_timestamp_open_attempts_are_order_insensitive(self):
        """Equal ``created_at`` attempts tie-break by id, so ``active_attempt_id``
        never depends on the append-only list order."""
        progress, attempt = kp_progress()
        progress.attempts = []
        add_attempt(
            progress,
            attempt_id="a1",
            cycle_type="initial",
            status=AttemptStatus.COLLECTING,
            created_at=START,
        )
        add_attempt(
            progress,
            attempt_id="a2",
            cycle_type="initial",
            status=AttemptStatus.COLLECTING,
            created_at=START,
        )
        proj = policy.rebuild_projection(progress, "kp1", now=START)
        # Greatest (created_at, id) is the latest open attempt.
        assert proj.active_attempt_id == "a2"
        progress.attempts.reverse()
        proj2 = policy.rebuild_projection(progress, "kp1", now=START)
        assert proj2.active_attempt_id == "a2"
        assert proj2.model_dump() == proj.model_dump()

    def test_invalidated_attempt_gate_cannot_overwrite_latest_valid_state(self):
        """A later-sequence gate on an invalidated attempt (§7.7) is not valid
        projection input: the latest valid stable state must survive."""
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record_pass(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record_pass(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        # A later invalidated attempt with a failing gate must be ignored.
        invalid = add_attempt(
            progress,
            attempt_id="a3",
            cycle_type="reevaluation",
            status=AttemptStatus.INVALIDATED,
            chain_id="chain-3",
            created_at=START + 800,
        )
        append_complete_chain(progress, invalid, start=START + 900)
        _record_pass(progress, invalid, assessment_id="ra3", passed=False, created_at=START + 950)
        proj = policy.rebuild_projection(progress, "kp1", now=START + 950)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY
        assert proj.latest_assessment_id == "ra2"
        assert proj.active_attempt_id == "a2"

    def test_legacy_import_projects_provisional_and_scheduled(self):
        """LRN-01 legacy import is compatible with the rebuild: provisional,
        never stable, with a scheduled delayed reteach."""
        from deeptutor.learning.storage import migrate_legacy_projection

        progress = LearningProgress(book_id="book1")
        progress.modules = [
            LearningModule(
                id="m1",
                name="Module 1",
                order=0,
                knowledge_points=[
                    KnowledgePoint(id="kp1", name="KP1", type=KnowledgeType.CONCEPT, module_id="m1")
                ],
            )
        ]
        progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        progress.mastery_levels["kp1"] = 0.9
        progress.qualitative_mastery["kp1"] = True
        migrate_legacy_projection(progress)
        proj = policy.rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.review_state == ReviewState.SCHEDULED
        assert proj.next_review_at is not None
        assert proj.stable_since is None
