"""Tests for the Mastery Path policy — the per-type gate and the gate-driven
"what's next" decision that replaced the old linear stage march.

These assert the two Alpha-style principles the old engine violated:

* a HARD gate — an objective is not mastered (and never advanced past) until
  its evidence clears the threshold;
* compression — an already-proven objective is skipped, never re-taught.
"""

from __future__ import annotations

import time

from deeptutor.learning import policy
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    PendingQuestion,
    RepetitionState,
    ReviewTask,
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
