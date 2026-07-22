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
    KnowledgePoint,
    KnowledgeType,
    LearningProgress,
    ReviewTask,
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

    * MEMORY / PROCEDURE: recency-weighted accuracy ≥ the type's threshold.
    * CONCEPT / DESIGN: a recorded qualitative pass (``mastery_assess``).
    """
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
]
