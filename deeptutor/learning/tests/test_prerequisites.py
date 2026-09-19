"""Explicit prerequisite links: weakness boosts review, cycles do not hang."""

from __future__ import annotations

import time

from deeptutor.learning.misconceptions import record_outcome
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    QuizAttempt,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.policy import next_objective
from deeptutor.learning.prerequisites import (
    REASON_WEAK_PREREQUISITE,
    has_prerequisite_cycle,
    is_prerequisite_weak,
    iter_prerequisites,
    remap_prerequisite_ids,
    resolve_prerequisite_ids,
    unique_id_aliases,
    weak_prerequisite_ids,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler


def _kp(
    kp_id: str,
    *,
    name: str = "",
    prereqs: list[str] | None = None,
    kp_type: KnowledgeType = KnowledgeType.MEMORY,
) -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id,
        name=name or kp_id,
        type=kp_type,
        module_id="m1",
        prerequisite_ids=list(prereqs or []),
    )


def _progress(*kps: KnowledgePoint) -> LearningProgress:
    progress = LearningProgress(book_id="b1")
    progress.modules = [LearningModule(id="m1", name="M1", order=0, knowledge_points=list(kps))]
    for kp in kps:
        progress.knowledge_types[kp.id] = kp.type
    return progress


def _due_state(scheduler: SpacedRepetitionScheduler, now: float) -> RepetitionState:
    state = scheduler.get_initial_state(KnowledgeType.MEMORY, now=now)
    state.last_review_at = now
    state.next_review_at = now - 10
    state.stability = 10.0
    state.lapse_count = 0
    return state


def test_weak_prerequisite_raises_downstream_review_priority():
    prereq = _kp("kp_a")
    downstream = _kp("kp_b", prereqs=["kp_a"])
    sibling = _kp("kp_c")
    progress = _progress(prereq, downstream, sibling)
    progress.quiz_attempts.append(
        QuizAttempt(question_id="q1", knowledge_point_id="kp_a", is_correct=False)
    )
    progress.mastery_levels["kp_a"] = 0.2

    scheduler = SpacedRepetitionScheduler()
    now = time.time()
    for kp_id in ("kp_b", "kp_c"):
        progress.repetition_states[kp_id] = _due_state(scheduler, now)

    assert is_prerequisite_weak(progress, "kp_a") is True
    assert weak_prerequisite_ids(progress, "kp_b") == ["kp_a"]
    assert weak_prerequisite_ids(progress, "kp_c") == []

    tasks = scheduler.build_review_queue(progress, now=now)
    by_id = {task.knowledge_point_id: task for task in tasks}
    assert by_id["kp_b"].forgetting_risk > by_id["kp_c"].forgetting_risk
    assert REASON_WEAK_PREREQUISITE in by_id["kp_b"].reason_codes
    assert REASON_WEAK_PREREQUISITE not in by_id["kp_c"].reason_codes
    assert "weak prerequisite" in by_id["kp_b"].reason
    assert tasks[0].knowledge_point_id == "kp_b"


def test_healthy_prerequisite_does_not_boost_or_block_learning():
    prereq = _kp("kp_a")
    downstream = _kp("kp_b", prereqs=["kp_a"])
    sibling = _kp("kp_c")
    progress = _progress(prereq, downstream, sibling)
    progress.mastery_levels["kp_a"] = 0.95

    assert is_prerequisite_weak(progress, "kp_a") is False
    assert weak_prerequisite_ids(progress, "kp_b") == []

    scheduler = SpacedRepetitionScheduler()
    now = time.time()
    for kp_id in ("kp_b", "kp_c"):
        progress.repetition_states[kp_id] = _due_state(scheduler, now)
    tasks = scheduler.build_review_queue(progress, now=now)
    by_id = {task.knowledge_point_id: task for task in tasks}
    assert by_id["kp_b"].forgetting_risk == by_id["kp_c"].forgetting_risk
    assert by_id["kp_b"].reason_codes == []

    # Unmastered downstream is still the next thing to learn — prereqs do not gate.
    fresh = _progress(_kp("kp_b", prereqs=["kp_a"]), _kp("kp_a"))
    step = next_objective(fresh)
    assert step.action == "probe"
    assert step.knowledge_point_id == "kp_b"


def test_untouched_prerequisite_is_not_weak():
    progress = _progress(_kp("kp_a"), _kp("kp_b", prereqs=["kp_a"]))
    assert is_prerequisite_weak(progress, "kp_a") is False
    assert weak_prerequisite_ids(progress, "kp_b") == []


def test_prerequisite_cycle_does_not_hang():
    progress = _progress(_kp("kp_a", prereqs=["kp_b"]), _kp("kp_b", prereqs=["kp_a"]))
    reached = list(iter_prerequisites(progress, "kp_a"))
    assert reached == ["kp_b"]
    assert has_prerequisite_cycle(progress) is True
    assert weak_prerequisite_ids(progress, "kp_a") == []

    longer = _progress(
        _kp("a", prereqs=["b"]),
        _kp("b", prereqs=["c"]),
        _kp("c", prereqs=["a"]),
    )
    assert set(iter_prerequisites(longer, "a")) == {"b", "c"}
    assert has_prerequisite_cycle(longer) is True
    # Demonstrated weakness on a cyclic node still reports once, not forever.
    longer.quiz_attempts.append(
        QuizAttempt(question_id="q", knowledge_point_id="b", is_correct=False)
    )
    longer.mastery_levels["b"] = 0.1
    assert weak_prerequisite_ids(longer, "a") == ["b"]


def test_resolve_prerequisite_ids_maps_names_and_drops_unknowns():
    modules = [
        LearningModule(
            id="m1",
            name="M1",
            order=0,
            knowledge_points=[
                _kp("id-a", name="Alpha"),
                _kp("id-b", name="Beta", prereqs=["Alpha", "missing", "id-b"]),
            ],
        )
    ]
    resolve_prerequisite_ids(modules)
    assert modules[0].knowledge_points[1].prerequisite_ids == ["id-a"]


def test_resolve_prerequisite_ids_maps_unique_aliases():
    modules = [
        LearningModule(
            id="m1",
            name="M1",
            order=0,
            knowledge_points=[
                _kp("gen-a", name="Alpha"),
                _kp("gen-b", name="Beta", prereqs=["a", "missing"]),
            ],
        )
    ]
    resolve_prerequisite_ids(modules, aliases={"a": "gen-a", "b": "gen-b"})
    assert modules[0].knowledge_points[1].prerequisite_ids == ["gen-a"]


def test_unique_id_aliases_drop_ambiguous_sources():
    assert unique_id_aliases([("a", "gen-1"), ("a", "gen-2"), ("b", "gen-3")]) == {"b": "gen-3"}


def test_remap_prerequisite_ids_rewrites_and_drops_unknowns():
    points = [
        _kp("new-a", name="Alpha"),
        _kp("new-b", name="Beta", prereqs=["old-a", "missing", "kept"]),
    ]
    remap_prerequisite_ids(
        points,
        {"old-a": "new-a", "old-b": "new-b"},
        known_ids={"new-a", "new-b", "kept"},
    )
    assert points[1].prerequisite_ids == ["new-a", "kept"]


def test_active_misconception_on_prerequisite_counts_as_weak():
    progress = _progress(_kp("kp_a"), _kp("kp_b", prereqs=["kp_a"]))
    progress.quiz_attempts.append(
        QuizAttempt(question_id="q1", knowledge_point_id="kp_a", is_correct=False)
    )
    progress.mastery_levels["kp_a"] = 0.7
    assert is_prerequisite_weak(progress, "kp_a") is False
    record_outcome(progress, "kp_a", failed=True, signature="application")
    record_outcome(progress, "kp_a", failed=True, signature="application")
    assert is_prerequisite_weak(progress, "kp_a") is True
    assert weak_prerequisite_ids(progress, "kp_b") == ["kp_a"]


def test_next_objective_review_carries_weak_prerequisite_reason_codes():
    progress = _progress(_kp("kp_a"), _kp("kp_b", prereqs=["kp_a"]))
    progress.quiz_attempts.append(
        QuizAttempt(question_id="q1", knowledge_point_id="kp_a", is_correct=False)
    )
    progress.mastery_levels["kp_a"] = 0.2
    progress.mastery_levels["kp_b"] = 0.95
    now = time.time()
    progress.review_queue = [
        ReviewTask(
            id="r_b",
            knowledge_point_id="kp_b",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=now - 10,
            priority=2,
            state=RepetitionState(next_review_at=now - 10),
            forgetting_risk=0.4,
            reason="due now; weak prerequisite KP A.",
            reason_codes=[REASON_WEAK_PREREQUISITE],
        )
    ]
    step = next_objective(progress, now=now)
    assert step.action == "review"
    assert step.knowledge_point_id == "kp_b"
    assert REASON_WEAK_PREREQUISITE in step.reason_codes
    assert "weak prerequisite" in step.reason
