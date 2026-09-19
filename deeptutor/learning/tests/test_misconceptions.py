"""Repeated-error misconception tracking: weak on one miss, active on repeats."""

from __future__ import annotations

import time

from deeptutor.learning.misconceptions import (
    REASON_ACTIVE_MISCONCEPTION,
    REPEATED_FAILURE,
    has_active_misconception,
    misconception_key,
    record_from_evidence,
    record_outcome,
)
from deeptutor.learning.models import (
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningEvidence,
    LearningModule,
    LearningProgress,
    MisconceptionState,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore


def _progress() -> LearningProgress:
    progress = LearningProgress(book_id="b1")
    progress.modules = [
        LearningModule(
            id="m1",
            name="M1",
            order=0,
            knowledge_points=[
                KnowledgePoint(id="kp1", name="KP1", type=KnowledgeType.MEMORY, module_id="m1")
            ],
        )
    ]
    progress.knowledge_types["kp1"] = KnowledgeType.MEMORY
    return progress


def test_one_failure_is_only_a_weak_signal():
    progress = _progress()
    state = record_outcome(progress, "kp1", failed=True, signature="application")
    assert state is not None
    assert state.status == "weak"
    assert state.occurrence_count == 1
    assert state.confidence == 0.3
    assert has_active_misconception(progress, "kp1") is False

    scheduler = SpacedRepetitionScheduler()
    progress.repetition_states["kp1"] = scheduler.get_initial_state(KnowledgeType.MEMORY)
    tasks = scheduler.build_review_queue(progress)
    assert tasks[0].reason_codes == []
    assert REASON_ACTIVE_MISCONCEPTION not in tasks[0].reason


def test_repeated_equivalent_failure_becomes_active():
    progress = _progress()
    first = record_outcome(progress, "kp1", failed=True, signature="application")
    assert first is not None and first.status == "weak"
    first_confidence = first.confidence
    first_severity = first.severity
    second = record_outcome(progress, "kp1", failed=True, signature="application")
    assert second is not None
    assert second.status == "active"
    assert second.occurrence_count == 2
    assert second.confidence > first_confidence
    assert second.severity > first_severity
    assert has_active_misconception(progress, "kp1") is True

    scheduler = SpacedRepetitionScheduler()
    now = time.time()
    progress.repetition_states["kp1"] = scheduler.get_initial_state(KnowledgeType.MEMORY, now=now)
    tasks = scheduler.build_review_queue(progress, now=now)
    assert REASON_ACTIVE_MISCONCEPTION in tasks[0].reason_codes
    assert "active misconception" in tasks[0].reason
    # Type/error priority numbers stay as they were; ranking uses risk.
    assert tasks[0].priority == 2


def test_unequal_signatures_do_not_activate_each_other():
    progress = _progress()
    record_outcome(progress, "kp1", failed=True, signature="application")
    record_outcome(progress, "kp1", failed=True, signature="metacognitive")
    assert has_active_misconception(progress, "kp1") is False
    assert progress.misconceptions[misconception_key("kp1", "application")].status == "weak"
    assert progress.misconceptions[misconception_key("kp1", "metacognitive")].status == "weak"


def test_later_successes_decay_then_resolve_active_misconception():
    progress = _progress()
    record_outcome(progress, "kp1", failed=True, signature="application")
    record_outcome(progress, "kp1", failed=True, signature="application")
    key = misconception_key("kp1", "application")
    active = progress.misconceptions[key]
    assert active.status == "active"
    before = active.confidence

    record_outcome(progress, "kp1", failed=False, signature="application")
    weakened = progress.misconceptions[key]
    assert weakened.status == "active"
    assert weakened.confidence < before
    assert weakened.consecutive_successes == 1

    record_outcome(progress, "kp1", failed=False, signature="application")
    resolved = progress.misconceptions[key]
    assert resolved.status == "resolved"
    assert resolved.confidence == 0.0
    assert has_active_misconception(progress, "kp1") is False


def test_resolved_misconception_reopens_weak_on_one_later_failure():
    progress = _progress()
    record_outcome(progress, "kp1", failed=True, signature="application")
    record_outcome(progress, "kp1", failed=True, signature="application")
    record_outcome(progress, "kp1", failed=False)
    record_outcome(progress, "kp1", failed=False)
    key = misconception_key("kp1", "application")
    assert progress.misconceptions[key].status == "resolved"

    reopened = record_outcome(progress, "kp1", failed=True, signature="application")
    assert reopened is not None
    assert reopened.status == "weak"
    assert reopened.occurrence_count == 1
    assert has_active_misconception(progress, "kp1") is False


def test_learning_evidence_without_error_type_uses_repeated_failure():
    progress = _progress()
    evidence = LearningEvidence(
        knowledge_point_id="kp1", result="incorrect", assessment_type="quiz"
    )
    state = record_from_evidence(progress, evidence)
    assert state is not None
    assert state.signature == REPEATED_FAILURE
    assert state.status == "weak"


def test_grade_and_record_writes_misconception_before_queue(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    scheduler = SpacedRepetitionScheduler()
    progress = _progress()
    service.save(progress)

    service.grade_and_record(
        progress,
        question_id="q1",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="wrong",
        expected_answer="right",
        scheduler=scheduler,
    )
    key = misconception_key("kp1", ErrorType.APPLICATION_ERROR.value)
    assert progress.misconceptions[key].status == "weak"
    assert REASON_ACTIVE_MISCONCEPTION not in progress.review_queue[0].reason_codes

    service.grade_and_record(
        progress,
        question_id="q2",
        knowledge_point_id="kp1",
        module_id="m1",
        user_answer="still wrong",
        expected_answer="right",
        scheduler=scheduler,
    )
    assert progress.misconceptions[key].status == "active"
    assert REASON_ACTIVE_MISCONCEPTION in progress.review_queue[0].reason_codes


def test_active_misconception_raises_forgetting_risk_over_sibling():
    progress = _progress()
    progress.modules[0].knowledge_points.append(
        KnowledgePoint(id="kp2", name="KP2", type=KnowledgeType.MEMORY, module_id="m1")
    )
    progress.knowledge_types["kp2"] = KnowledgeType.MEMORY
    record_outcome(progress, "kp1", failed=True, signature="application")
    record_outcome(progress, "kp1", failed=True, signature="application")

    scheduler = SpacedRepetitionScheduler()
    now = time.time()
    for kp_id in ("kp1", "kp2"):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY, now=now)
        state.last_review_at = now
        state.next_review_at = now - 10
        state.stability = 10.0
        state.lapse_count = 0
        progress.repetition_states[kp_id] = state

    tasks = scheduler.build_review_queue(progress, now=now)
    by_id = {task.knowledge_point_id: task for task in tasks}
    assert by_id["kp1"].forgetting_risk > by_id["kp2"].forgetting_risk
    assert tasks[0].knowledge_point_id == "kp1"


def test_legacy_progress_without_misconceptions_loads():
    loaded = LearningProgress.model_validate({"book_id": "old"})
    assert loaded.misconceptions == {}
    state = MisconceptionState(knowledge_point_id="kp1")
    assert state.signature == REPEATED_FAILURE
    assert state.status == "weak"
    assert state.evidence_refs == []
