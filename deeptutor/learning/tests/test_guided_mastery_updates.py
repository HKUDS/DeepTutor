"""Tests for Mastery Path mastery updates from graded answers.

The unified post-answer pipeline is ``LearningService.grade_and_record``: it
grades one answer, recomputes mastery (recency-weighted with a low-confidence
cap), advances the spaced-repetition state, rebuilds the review queue, and
persists. The mastery tools (``mastery_grade``) fold every answer through
exactly this pipeline, so mastery is updated deterministically with the
expected answer held server-side. These tests assert that contract end to end.
"""

import pytest

from deeptutor.learning.mastery import compute_mastery
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_progress(book_id="book1") -> LearningProgress:
    progress = LearningProgress(book_id=book_id)
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
    progress.current_module_id = "m1"
    progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
    return progress


# ── compute_mastery policy: low-confidence cap ─────────────────────────────


def test_compute_mastery_single_correct_is_capped_at_half():
    """A single lucky answer cannot 'master' a point: 1 attempt caps at 0.5."""
    assert compute_mastery([True]) == 0.5


def test_compute_mastery_cap_progression():
    """Cap relaxes as evidence accumulates: 1->0.5, 2->0.8, 3+->up to 1.0."""
    assert compute_mastery([True]) == 0.5
    assert compute_mastery([True, True]) == 0.8
    assert compute_mastery([True, True, True]) == pytest.approx(1.0)


def test_compute_mastery_empty_is_zero():
    assert compute_mastery([]) == 0.0


def test_compute_mastery_partial_correctness_scales():
    """More correct answers within the recency window yield a higher score
    (below the cap, where attempt count no longer clamps the result)."""
    one_of_five = compute_mastery([True, False, False, False, False])
    two_of_five = compute_mastery([True, True, False, False, False])
    three_of_five = compute_mastery([True, True, True, False, False])
    assert one_of_five < two_of_five < three_of_five


# ── grade_and_record: the unified post-answer pipeline ─────────────────────


def test_grade_and_record_correct_updates_capped_mastery_and_persists(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()
    service.save(progress)

    result = service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="paris",
        expected_answer="paris",
    )

    assert result is True
    # Single correct attempt -> capped at 0.5, NOT 1.0.
    assert progress.mastery_levels["kp1"] == 0.5
    assert len(progress.quiz_attempts) == 1
    assert progress.quiz_attempts[0].is_correct is True

    loaded = store.load("book1")
    assert loaded is not None
    assert len(loaded.quiz_attempts) == 1
    assert loaded.mastery_levels["kp1"] == 0.5


def test_grade_and_record_fail_closed_without_expected_answer(tmp_path):
    """Fail-closed: with no stored expected answer the attempt is recorded
    wrong, never right — even when the user answer matches an empty string."""
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()

    result = service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="",
        expected_answer="",
    )

    assert result is False
    assert progress.quiz_attempts[0].is_correct is False
    # Wrong answer creates an active error record.
    assert len(progress.error_records) == 1
    assert progress.error_records[0].status == "active"


def test_grade_and_record_advances_sr_state_and_builds_queue(tmp_path):
    """When a scheduler is supplied, a graded answer advances the spaced-
    repetition state and rebuilds the review queue."""
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    scheduler = SpacedRepetitionScheduler()
    progress = _make_progress()

    service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="paris",
        expected_answer="paris",
        scheduler=scheduler,
    )

    assert "kp1" in progress.repetition_states
    # A correct answer advanced the interval index past the initial 0.
    assert progress.repetition_states["kp1"].interval_index >= 1
    assert len(progress.review_queue) == 1
    assert progress.review_queue[0].knowledge_point_id == "kp1"


def test_grade_and_record_no_scheduler_skips_sr_state(tmp_path):
    """Without a scheduler, mastery still updates but no SR state/queue is built."""
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()

    service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="paris",
        expected_answer="paris",
    )

    assert progress.mastery_levels["kp1"] == 0.5
    assert progress.repetition_states == {}
    assert progress.review_queue == []


def test_grade_and_record_blank_wrong_is_metacognitive(tmp_path):
    """A blank wrong answer is classified metacognitive at record time."""
    from deeptutor.learning.models import ErrorType

    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()

    service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="   ",
        expected_answer="paris",
    )

    assert progress.quiz_attempts[0].is_correct is False
    assert progress.quiz_attempts[0].error_type == ErrorType.METACOGNITIVE


# ── Error-record graduation across attempts ────────────────────────────────


def test_error_record_graduates_on_later_correct_answer(tmp_path):
    """A wrong answer opens an active error record; a later correct answer for
    the same question + KP graduates it, and mastery climbs out of the cap."""
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()

    # First attempt wrong.
    service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="london",
        expected_answer="paris",
    )
    assert len(progress.error_records) == 1
    assert progress.error_records[0].status == "active"

    # Two correct attempts on the same question + KP.
    for _ in range(2):
        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="paris",
            expected_answer="paris",
        )

    # The error record graduated on the first correct answer.
    assert progress.error_records[0].status == "graduated"
    # 3 attempts total (1 wrong + 2 right) lifts mastery above the 1-attempt cap.
    assert len(progress.quiz_attempts) == 3
    assert progress.mastery_levels["kp1"] > 0.5


# ── Pending-question lifecycle + qualitative recording (loop-driven path) ──


def test_pending_question_set_and_clear_round_trip(tmp_path):
    from deeptutor.learning.models import PendingQuestion

    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()

    service.set_pending_question(
        progress,
        PendingQuestion(
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            prompt="Capital of France?",
            expected_answer="paris",
        ),
    )
    assert store.load("book1").pending_question.expected_answer == "paris"

    service.clear_pending_question(progress)
    assert progress.pending_question is None
    assert store.load("book1").pending_question is None


def test_record_qualitative_pass_and_fail_drive_display_mastery(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    progress = _make_progress()

    service.record_qualitative(progress, "kp1", passed=True, evidence="clear explanation")
    assert progress.qualitative_mastery["kp1"] is True
    assert progress.mastery_levels["kp1"] == 1.0
    assert progress.feynman_explanations["kp1"] == "clear explanation"

    service.record_qualitative(progress, "kp1", passed=False)
    assert progress.qualitative_mastery["kp1"] is False
    assert progress.mastery_levels["kp1"] <= 0.4
