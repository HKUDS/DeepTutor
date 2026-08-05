"""Mastery Path policy — pure decisions over a :class:`LearningProgress`.

No LLM calls, no I/O. This is the engine the chat-loop tutor consults each
turn. It answers three questions:

* **is this objective mastered?** (:func:`is_mastered` — a HARD, per-type gate)
* **what should the learner work on next?** (:func:`next_objective`)
* **what does the whole map look like?** (:func:`map_summary`)

The gate is the heart of mastery-based learning. An objective only counts as
mastered when the evidence clears its threshold, and :func:`next_objective`
keeps returning the same objective until it does — advancement is *computed
from what is mastered*, never tracked by a stage counter. Objective ordering
follows module order then knowledge-point order; an objective the learner has
already proven is skipped (the "test out" / compression path) because the gate
reads proven mastery, not a fixed sequence of stages.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from deeptutor.learning.models import (
    AttemptCycleType,
    AttemptStatus,
    KnowledgePoint,
    KnowledgeStateProjection,
    KnowledgeType,
    LearningProgress,
    MasteryState,
    ReviewState,
    ReviewTask,
)
from deeptutor.learning.scheduler import (
    FAILED_REVIEW_RETRY_DELAY_DAYS,
    PROVISIONAL_RETEACH_DELAY_DAYS,
    STABLE_MAINTENANCE_DELAY_DAYS,
)

# Quantitative gate for objective knowledge types: the learner must reach this
# mastery (recency-weighted accuracy; see ``mastery.compute_mastery``) before
# the objective unlocks. ~0.9 mirrors Alpha School's "90% before you advance".
QUANTITATIVE_GATE: dict[KnowledgeType, float] = {
    KnowledgeType.MEMORY: 0.9,
    KnowledgeType.PROCEDURE: 0.9,
}

# CONCEPT / DESIGN are gated qualitatively — a Feynman-style explanation judged
# by the tutor via ``mastery_assess`` — rather than by string-graded accuracy,
# because there is rarely a single canonical right answer to match against.
QUALITATIVE_TYPES: frozenset[KnowledgeType] = frozenset(
    {KnowledgeType.CONCEPT, KnowledgeType.DESIGN}
)

# Display mastery a qualitative pass maps to, so the map's colours agree with
# the gate even though qualitative mastery is a boolean, not a score. (The
# fail-side display is handled in ``LearningService.record_qualitative``.)
_QUALITATIVE_PASS_DISPLAY = 1.0


def gate_threshold(kp_type: KnowledgeType) -> float:
    """The quantitative mastery bar for *kp_type* (qualitative types report
    their pass-display value so callers have a single number to show)."""
    if kp_type in QUALITATIVE_TYPES:
        return _QUALITATIVE_PASS_DISPLAY
    return QUANTITATIVE_GATE.get(kp_type, 0.9)


def is_mastered(progress: LearningProgress, kp: KnowledgePoint) -> bool:
    """Whether ``kp`` clears its mastery gate.

    * Feynman projection (LRN-02): when a per-KP projection exists it is
      authoritative — ``provisional_mastery`` / ``stable_mastery`` count as
      mastered so the map cursor never re-teaches a mastered point.
    * MEMORY / PROCEDURE: recency-weighted accuracy ≥ the type's threshold.
    * CONCEPT / DESIGN (no projection yet): a recorded qualitative pass
      (``mastery_assess``).
    """
    projection = progress.projections.get(kp.id)
    if projection is not None:
        return projection.mastery_state in (
            MasteryState.PROVISIONAL_MASTERY,
            MasteryState.STABLE_MASTERY,
        )
    if kp.type in QUALITATIVE_TYPES:
        return bool(progress.qualitative_mastery.get(kp.id, False))
    return progress.mastery_levels.get(kp.id, 0.0) >= gate_threshold(kp.type)


def display_mastery(progress: LearningProgress, kp: KnowledgePoint) -> float:
    """A 0..1 number for the map UI. Qualitatively-mastered points show full;
    otherwise the recency-weighted accuracy stands in."""
    if kp.type in QUALITATIVE_TYPES and progress.qualitative_mastery.get(kp.id):
        return _QUALITATIVE_PASS_DISPLAY
    return float(progress.mastery_levels.get(kp.id, 0.0))


def objective_status(progress: LearningProgress, kp: KnowledgePoint) -> str:
    """``"mastered"`` | ``"learning"`` | ``"new"`` for one knowledge point."""
    if is_mastered(progress, kp):
        return "mastered"
    seen = any(a.knowledge_point_id == kp.id for a in progress.quiz_attempts) or (
        kp.id in progress.qualitative_mastery
    )
    return "learning" if seen else "new"


def due_reviews(progress: LearningProgress, *, now: float | None = None) -> list[ReviewTask]:
    """Spaced-repetition tasks whose ``due_at`` has passed, highest priority
    first. Pure read over ``progress.review_queue`` (built by the scheduler)."""
    moment = time.time() if now is None else now
    due = [task for task in progress.review_queue if task.due_at <= moment]
    due.sort(key=lambda task: task.priority)
    return due


@dataclass(frozen=True)
class NextStep:
    """What the tutor should do next, decided by the gate — not a stage cursor.

    ``action`` is advisory for the model's pedagogy; the binding fact is the
    objective and whether it is mastered. Values:

    * ``answer_pending`` — a posed question awaits the learner's answer.
    * ``review`` — a spaced-repetition item is due.
    * ``probe`` — an untouched objective; test out before teaching.
    * ``practice`` — a quantitative objective below its gate.
    * ``assess`` — a qualitative objective awaiting a Feynman-style check.
    * ``complete`` — every objective mastered, nothing due.
    """

    action: str
    module_id: str = ""
    module_name: str = ""
    knowledge_point_id: str = ""
    knowledge_point_name: str = ""
    knowledge_point_type: str = ""
    status: str = ""
    gate: str = ""
    mastery: float = 0.0
    threshold: float = 0.0
    reason: str = ""
    pending_prompt: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "module_id": self.module_id,
            "module_name": self.module_name,
            "knowledge_point_id": self.knowledge_point_id,
            "knowledge_point_name": self.knowledge_point_name,
            "knowledge_point_type": self.knowledge_point_type,
            "status": self.status,
            "gate": self.gate,
            "mastery": round(self.mastery, 3),
            "threshold": round(self.threshold, 3),
            "reason": self.reason,
            "pending_prompt": self.pending_prompt,
        }


def find_knowledge_point(
    progress: LearningProgress, kp_id: str
) -> tuple[KnowledgePoint | None, str, str]:
    """Return ``(kp, module_id, module_name)`` for *kp_id*, or ``(None, "", "")``."""
    for module in progress.modules:
        for kp in module.knowledge_points:
            if kp.id == kp_id:
                return kp, module.id, module.name
    return None, "", ""


def _gate_kind(kp: KnowledgePoint) -> str:
    return "qualitative" if kp.type in QUALITATIVE_TYPES else "quantitative"


def next_objective(progress: LearningProgress, *, now: float | None = None) -> NextStep:
    """Decide the next thing to work on. Order of precedence:

    1. an outstanding posed question (grade it before moving on);
    2. a due spaced-repetition review (don't let mastered ground decay);
    3. the first not-yet-mastered objective in module/KP order (the gate IS
       the cursor — mastered objectives are skipped);
    4. otherwise the path is complete.
    """
    pending = progress.pending_question
    if pending is not None:
        kp, module_id, module_name = find_knowledge_point(progress, pending.knowledge_point_id)
        return NextStep(
            action="answer_pending",
            module_id=module_id or pending.module_id,
            module_name=module_name,
            knowledge_point_id=pending.knowledge_point_id,
            knowledge_point_name=kp.name if kp else "",
            knowledge_point_type=kp.type.value if kp else "",
            status=objective_status(progress, kp) if kp else "learning",
            gate=_gate_kind(kp) if kp else "",
            mastery=display_mastery(progress, kp) if kp else 0.0,
            threshold=gate_threshold(kp.type) if kp else 0.0,
            reason="A posed question is awaiting the learner's answer; grade it with mastery_grade.",
            pending_prompt=pending.prompt,
        )

    due = due_reviews(progress, now=now)
    if due:
        kp, module_id, module_name = find_knowledge_point(progress, due[0].knowledge_point_id)
        if kp is not None:
            return NextStep(
                action="review",
                module_id=module_id,
                module_name=module_name,
                knowledge_point_id=kp.id,
                knowledge_point_name=kp.name,
                knowledge_point_type=kp.type.value,
                status=objective_status(progress, kp),
                gate=_gate_kind(kp),
                mastery=display_mastery(progress, kp),
                threshold=gate_threshold(kp.type),
                reason="This objective is due for spaced-repetition review.",
            )

    for module in sorted(progress.modules, key=lambda m: m.order):
        for kp in module.knowledge_points:
            if is_mastered(progress, kp):
                continue
            status = objective_status(progress, kp)
            gate = _gate_kind(kp)
            if status == "new":
                action = "probe"
            elif gate == "qualitative":
                action = "assess"
            else:
                action = "practice"
            return NextStep(
                action=action,
                module_id=module.id,
                module_name=module.name,
                knowledge_point_id=kp.id,
                knowledge_point_name=kp.name,
                knowledge_point_type=kp.type.value,
                status=status,
                gate=gate,
                mastery=display_mastery(progress, kp),
                threshold=gate_threshold(kp.type),
                reason=(
                    "Untouched objective — probe first to let the learner test out."
                    if status == "new"
                    else "Objective is below its mastery gate; keep working it until it clears."
                ),
            )

    return NextStep(action="complete", reason="All objectives are mastered and no reviews are due.")


def map_summary(progress: LearningProgress, *, now: float | None = None) -> dict:
    """A compact, render-ready snapshot of the whole path for the tutor's
    ``mastery_status`` tool and the dashboard."""
    counts = {"mastered": 0, "learning": 0, "new": 0, "total": 0}
    modules_out: list[dict] = []
    for module in sorted(progress.modules, key=lambda m: m.order):
        kps_out: list[dict] = []
        mastered = 0
        for kp in module.knowledge_points:
            status = objective_status(progress, kp)
            counts[status] += 1
            counts["total"] += 1
            if status == "mastered":
                mastered += 1
            kps_out.append(
                {
                    "id": kp.id,
                    "name": kp.name,
                    "type": kp.type.value,
                    "status": status,
                    "mastery": round(display_mastery(progress, kp), 3),
                }
            )
        modules_out.append(
            {
                "id": module.id,
                "name": module.name,
                "order": module.order,
                "mastered": mastered,
                "total": len(module.knowledge_points),
                "knowledge_points": kps_out,
            }
        )
    return {
        "counts": counts,
        "due_reviews": len(due_reviews(progress, now=now)),
        "complete": counts["total"] > 0 and counts["mastered"] == counts["total"],
        "modules": modules_out,
    }


# ── Feynman mastery/review projection (spec §6.2, §7.5; LRN-02) ──────────
#
# ``mastery_state`` and ``review_state`` are orthogonal projections rebuilt
# deterministically from the append-only attempts / assessments / review facts.
# A pass atomically projects mastery plus a scheduled review and next_review_at;
# due/start transitions change review only; a delayed-reteach pass promotes
# mastery to stable while scheduling the next maintenance review.

_SECONDS_PER_DAY = 86400.0

#: Attempt statuses that keep an attempt "live" (not yet assessed/closed).
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.DRAFT,
        AttemptStatus.COLLECTING,
        AttemptStatus.READY_TO_ASSESS,
    }
)

#: Attempt cycles that are review attempts (start flips review to in_progress).
_REVIEW_CYCLES = frozenset({AttemptCycleType.DELAYED_RETEACH, AttemptCycleType.REEVALUATION})

#: Cycles whose pass yields provisional mastery (stable always requires a
#: delayed-reteach pass, §6.5 / LRN-02 requirement 5).
_PROVISIONAL_CYCLES = frozenset(
    {
        AttemptCycleType.INITIAL,
        AttemptCycleType.TEST_OUT,
        AttemptCycleType.LEGACY_IMPORT,
    }
)


def _anchor_review(
    anchor: float, kp_type: KnowledgeType, delay_days: dict[KnowledgeType, int]
) -> float:
    """next_review_at anchored to the assessment time (deterministic rebuild)."""
    return anchor + delay_days.get(kp_type, 1) * _SECONDS_PER_DAY


def rebuild_projection(
    progress: LearningProgress, kp_id: str, *, now: float | None = None
) -> KnowledgeStateProjection:
    """Rebuild the per-KP projection deterministically from append-only facts.

    The projection is a pure function of the persisted attempts, assessments
    and review facts — it never mutates ``progress``, so it is idempotent and
    insensitive to the in-memory ordering of the append-only lists.
    """
    moment = now if now is not None else time.time()
    kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)

    attempts = sorted(
        (attempt for attempt in progress.attempts if attempt.knowledge_point_id == kp_id),
        key=lambda attempt: (attempt.created_at, attempt.id),
    )
    attempts_by_id = {attempt.id: attempt for attempt in attempts}
    assessments = sorted(
        (
            assessment
            for assessment in progress.rubric_assessments
            if assessment.attempt_id in attempts_by_id
        ),
        key=lambda assessment: (
            assessment.assessment_sequence,
            assessment.created_at,
            assessment.id,
        ),
    )

    mastery = MasteryState.NEW
    review_state = ReviewState.UNSCHEDULED
    active_attempt_id = ""
    latest_assessment_id = ""
    provisional_since: float | None = None
    stable_since: float | None = None
    next_review_at: float | None = None

    # 1. Mastery from server gate results, in assessment-sequence order.
    # Invalidated attempts (§7.7) contribute no gate facts: their assessments
    # stay in the append-only history but never become projection input.
    valid_assessment_seen = False
    for assessment in assessments:
        attempt = attempts_by_id[assessment.attempt_id]
        if attempt.status == AttemptStatus.INVALIDATED:
            continue
        valid_assessment_seen = True
        anchor = assessment.created_at
        active_attempt_id = attempt.id
        latest_assessment_id = assessment.id

        if assessment.server_gate_result.passed:
            if attempt.cycle_type == AttemptCycleType.DELAYED_RETEACH:
                mastery = MasteryState.STABLE_MASTERY
                stable_since = anchor
                review_state = ReviewState.SCHEDULED
                next_review_at = _anchor_review(anchor, kp_type, STABLE_MAINTENANCE_DELAY_DAYS)
            elif attempt.cycle_type in _PROVISIONAL_CYCLES:
                mastery = MasteryState.PROVISIONAL_MASTERY
                provisional_since = anchor
                review_state = ReviewState.SCHEDULED
                next_review_at = _anchor_review(anchor, kp_type, PROVISIONAL_RETEACH_DELAY_DAYS)
            else:  # REEVALUATION pass: confirms learning, never grants stable.
                if mastery == MasteryState.STABLE_MASTERY:
                    # A stable learner stays on stable maintenance policy; the
                    # review is not shortened to the provisional reteach delay.
                    review_state = ReviewState.SCHEDULED
                    next_review_at = _anchor_review(anchor, kp_type, STABLE_MAINTENANCE_DELAY_DAYS)
                else:
                    if mastery != MasteryState.PROVISIONAL_MASTERY:
                        mastery = MasteryState.PROVISIONAL_MASTERY
                        provisional_since = anchor
                    review_state = ReviewState.SCHEDULED
                    next_review_at = _anchor_review(anchor, kp_type, PROVISIONAL_RETEACH_DELAY_DAYS)
        else:
            mastery = MasteryState.NEEDS_REVISION
            review_state = ReviewState.SCHEDULED
            next_review_at = _anchor_review(anchor, kp_type, FAILED_REVIEW_RETRY_DELAY_DAYS)

    # 2. A live review attempt flips review to in_progress (mastery untouched).
    open_attempts = [attempt for attempt in attempts if attempt.status in _ACTIVE_ATTEMPT_STATUSES]
    if open_attempts:
        active_attempt_id = open_attempts[-1].id
        if any(attempt.cycle_type in _REVIEW_CYCLES for attempt in open_attempts):
            review_state = ReviewState.IN_PROGRESS

    # 3. No valid gate facts yet (no assessments, or only invalidated-attempt
    # ones): an open attempt marks in_progress, otherwise the point is new.
    if not valid_assessment_seen:
        if open_attempts:
            mastery = MasteryState.IN_PROGRESS
            review_state = (
                ReviewState.IN_PROGRESS
                if any(attempt.cycle_type in _REVIEW_CYCLES for attempt in open_attempts)
                else ReviewState.UNSCHEDULED
            )
        else:
            mastery = MasteryState.NEW
            review_state = ReviewState.UNSCHEDULED
        next_review_at = None

    # 4. Time-based view: a scheduled review whose time has come is due.
    if (
        review_state == ReviewState.SCHEDULED
        and next_review_at is not None
        and next_review_at <= moment
    ):
        review_state = ReviewState.DUE

    return KnowledgeStateProjection(
        knowledge_point_id=kp_id,
        mastery_state=mastery,
        review_state=review_state,
        active_attempt_id=active_attempt_id,
        latest_assessment_id=latest_assessment_id,
        provisional_since=provisional_since,
        stable_since=stable_since,
        next_review_at=next_review_at,
        updated_at=moment,
    )


def project_all(
    progress: LearningProgress, *, now: float | None = None
) -> dict[str, KnowledgeStateProjection]:
    """Rebuild every knowledge point's projection (module KPs included)."""
    kp_ids = set(progress.projections)
    kp_ids.update(attempt.knowledge_point_id for attempt in progress.attempts)
    for module in progress.modules:
        kp_ids.update(kp.id for kp in module.knowledge_points)
    return {kp_id: rebuild_projection(progress, kp_id, now=now) for kp_id in sorted(kp_ids)}


__all__ = [
    "QUANTITATIVE_GATE",
    "QUALITATIVE_TYPES",
    "NextStep",
    "gate_threshold",
    "is_mastered",
    "display_mastery",
    "objective_status",
    "due_reviews",
    "find_knowledge_point",
    "next_objective",
    "map_summary",
    "rebuild_projection",
    "project_all",
]
