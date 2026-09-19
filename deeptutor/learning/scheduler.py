from __future__ import annotations

import math
import os
import time
from typing import Protocol

from deeptutor.learning.misconceptions import (
    REASON_ACTIVE_MISCONCEPTION,
    has_active_misconception,
)
from deeptutor.learning.models import (
    KnowledgeType,
    LearningEvidence,
    LearningProgress,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.prerequisites import (
    REASON_WEAK_PREREQUISITE,
    weak_prerequisite_ids,
    weak_prerequisite_names,
)

INTERVAL_SEQUENCES: dict[KnowledgeType, list[int]] = {
    KnowledgeType.MEMORY: [0, 1, 3, 7, 14, 30, 60],
    KnowledgeType.CONCEPT: [3, 7, 14, 30],
    KnowledgeType.PROCEDURE: [3, 7, 14],
    KnowledgeType.DESIGN: [14, 28],
}

_TYPE_PRIORITY: dict[KnowledgeType, int] = {
    KnowledgeType.MEMORY: 2,
    KnowledgeType.CONCEPT: 3,
    KnowledgeType.PROCEDURE: 4,
    KnowledgeType.DESIGN: 5,
}

_TYPE_DIFFICULTY: dict[KnowledgeType, float] = {
    KnowledgeType.MEMORY: 0.3,
    KnowledgeType.CONCEPT: 0.4,
    KnowledgeType.PROCEDURE: 0.5,
    KnowledgeType.DESIGN: 0.6,
}

DEFAULT_DESIRED_RETENTION = 0.9
_MIN_STABILITY_DAYS = 0.5
_FAIL_QUALITY = 0.5
_EPS = 1e-6
_ACTIVE_MISCONCEPTION_RISK = 0.2
_WEAK_PREREQUISITE_RISK = 0.15


class RetentionScheduler(Protocol):
    """Pluggable retention model. The default baseline is exponential forgetting
    with type-specific cold-start priors — not a calibrated FSRS fit.
    """

    def get_initial_state(
        self, knowledge_type: KnowledgeType, *, now: float | None = None
    ) -> RepetitionState: ...

    def schedule_review(
        self,
        state: RepetitionState,
        knowledge_type: KnowledgeType,
        evidence: LearningEvidence,
        *,
        now: float | None = None,
    ) -> RepetitionState: ...

    def retrievability(self, state: RepetitionState, *, now: float | None = None) -> float: ...

    def forgetting_risk(
        self,
        state: RepetitionState,
        progress: LearningProgress,
        kp_id: str,
        *,
        now: float | None = None,
    ) -> float: ...

    def build_review_queue(
        self, progress: LearningProgress, *, now: float | None = None
    ) -> list[ReviewTask]: ...

    def replay(
        self,
        knowledge_type: KnowledgeType,
        evidence: list[LearningEvidence],
        *,
        now: float | None = None,
    ) -> RepetitionState: ...


def _error_kp_ids(progress: LearningProgress) -> set[str]:
    return {
        rec.knowledge_point_id
        for rec in progress.error_records
        if rec.status in ("active", "retrying")
    }


def review_sort_key(task: ReviewTask, *, now: float) -> tuple[float, float, int]:
    """Higher forgetting risk, then more overdue, then lower type/error priority."""
    overdue = max(0.0, now - task.due_at)
    return (-task.forgetting_risk, -overdue, task.priority)


class SpacedRepetitionScheduler:
    def __init__(self) -> None:
        # When True, intervals are in seconds instead of days (for testing)
        self.DEBUG_MODE: bool = os.environ.get("LEARNING_DEBUG", "").lower() in ("1", "true", "yes")

    def _seconds_per_unit(self) -> float:
        return 1.0 if self.DEBUG_MODE else 86400.0

    @staticmethod
    def _stability_from_interval(interval_days: float, desired_retention: float) -> float:
        retention = min(max(desired_retention, _EPS), 1.0 - _EPS)
        if interval_days <= 0:
            return _MIN_STABILITY_DAYS
        return max(_MIN_STABILITY_DAYS, interval_days / -math.log(retention))

    @staticmethod
    def _interval_from_stability(stability: float, desired_retention: float) -> float:
        retention = min(max(desired_retention, _EPS), 1.0 - _EPS)
        return max(_EPS, max(stability, _EPS) * -math.log(retention))

    def hydrate(self, state: RepetitionState, knowledge_type: KnowledgeType) -> RepetitionState:
        """Fill retention fields from a legacy interval-index snapshot.

        Does not change ``next_review_at``: the stored due time remains the
        source of truth for already-scheduled items.
        """
        if state.stability > 0:
            if state.difficulty <= 0:
                state.difficulty = _TYPE_DIFFICULTY.get(knowledge_type, 0.3)
            return state
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        max_index = len(intervals) - 1
        state.interval_index = max(0, min(state.interval_index, max_index))
        state.desired_retention = state.desired_retention or DEFAULT_DESIRED_RETENTION
        state.stability = self._stability_from_interval(
            float(intervals[state.interval_index]), state.desired_retention
        )
        state.difficulty = _TYPE_DIFFICULTY.get(knowledge_type, 0.3)
        if state.retrievability <= 0:
            state.retrievability = 1.0
        return state

    def get_initial_state(
        self, knowledge_type: KnowledgeType, *, now: float | None = None
    ) -> RepetitionState:
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        first_interval = float(intervals[0])
        moment = time.time() if now is None else now
        desired = DEFAULT_DESIRED_RETENTION
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=moment + first_interval * self._seconds_per_unit(),
            difficulty=_TYPE_DIFFICULTY[knowledge_type],
            stability=self._stability_from_interval(first_interval, desired),
            retrievability=1.0,
            desired_retention=desired,
            review_count=0,
            lapse_count=0,
            last_review_at=None,
        )

    def schedule_next(
        self, state: RepetitionState, knowledge_type: KnowledgeType, is_correct: bool
    ) -> RepetitionState:
        evidence = LearningEvidence(
            knowledge_point_id="",
            assessment_type="review",
            result="correct" if is_correct else "incorrect",
            quality=1.0 if is_correct else 0.0,
        )
        return self.schedule_review(state, knowledge_type, evidence)

    def schedule_review(
        self,
        state: RepetitionState,
        knowledge_type: KnowledgeType,
        evidence: LearningEvidence,
        *,
        now: float | None = None,
    ) -> RepetitionState:
        self.hydrate(state, knowledge_type)
        moment = time.time() if now is None else now
        quality = _resolved_quality(evidence)
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        max_index = len(intervals) - 1

        if quality < _FAIL_QUALITY:
            state.consecutive_wrong += 1
            state.consecutive_correct = 0
            state.lapse_count += 1
            state.stability = max(_MIN_STABILITY_DAYS * 0.1, state.stability * 0.5)
            state.retrievability = max(quality, 0.2)
            if state.consecutive_wrong >= 2:
                state.consecutive_wrong = 0
        else:
            state.consecutive_wrong = 0
            state.consecutive_correct += 1
            growth = 1.2 + quality * 1.5
            if quality >= 0.8 and state.consecutive_correct >= 2:
                growth *= 1.15
            state.stability = max(_MIN_STABILITY_DAYS, state.stability * growth)
            state.retrievability = 1.0
            if state.consecutive_correct >= 2:
                state.consecutive_correct = 0

        state.review_count += 1
        state.last_review_at = moment
        interval_days = self._interval_from_stability(state.stability, state.desired_retention)
        if quality < _FAIL_QUALITY:
            # Failures must come back sooner than the success formula alone
            # would schedule after a halved stability.
            interval_days = min(interval_days, max(interval_days * 0.5, _MIN_STABILITY_DAYS * 0.2))
        state.next_review_at = moment + interval_days * self._seconds_per_unit()
        state.interval_index = _snap_interval_index(intervals, interval_days, max_index)
        return state

    def retrievability(self, state: RepetitionState, *, now: float | None = None) -> float:
        moment = time.time() if now is None else now
        stability = max(state.stability, _EPS)
        anchor = state.last_review_at if state.last_review_at is not None else state.next_review_at
        elapsed_days = max(0.0, (moment - anchor) / self._seconds_per_unit())
        return float(min(1.0, max(0.0, math.exp(-elapsed_days / stability))))

    def forgetting_risk(
        self,
        state: RepetitionState,
        progress: LearningProgress,
        kp_id: str,
        *,
        now: float | None = None,
    ) -> float:
        moment = time.time() if now is None else now
        recall = self.retrievability(state, now=moment)
        risk = 1.0 - recall
        if moment > state.next_review_at:
            overdue_days = (moment - state.next_review_at) / self._seconds_per_unit()
            risk += min(overdue_days / 7.0, 0.25)
        if kp_id in _error_kp_ids(progress):
            risk += 0.2
        if state.lapse_count:
            risk += min(0.1 * state.lapse_count, 0.2)
        if has_active_misconception(progress, kp_id):
            risk += _ACTIVE_MISCONCEPTION_RISK
        if weak_prerequisite_ids(progress, kp_id):
            risk += _WEAK_PREREQUISITE_RISK
        return float(min(1.0, max(0.0, risk)))

    def review_reason(
        self,
        state: RepetitionState,
        progress: LearningProgress,
        kp_id: str,
        *,
        now: float | None = None,
    ) -> str:
        moment = time.time() if now is None else now
        unit = self._seconds_per_unit()
        recall = self.retrievability(state, now=moment)
        parts: list[str] = []
        delta = moment - state.next_review_at
        if delta >= unit:
            parts.append(f"due {_format_span(delta / unit)} ago")
        elif delta >= 0:
            parts.append("due now")
        else:
            parts.append(f"due in {_format_span(-delta / unit)}")
        desired = state.desired_retention or DEFAULT_DESIRED_RETENTION
        if recall + 1e-9 < desired:
            parts.append(f"retrievability {recall:.0%} below {desired:.0%} target")
        else:
            parts.append(f"retrievability {recall:.0%}")
        failures = state.consecutive_wrong + (1 if kp_id in _error_kp_ids(progress) else 0)
        if state.lapse_count:
            parts.append(f"{state.lapse_count} lapse{'s' if state.lapse_count != 1 else ''}")
        elif failures:
            parts.append("recent failure")
        if has_active_misconception(progress, kp_id):
            parts.append("active misconception")
        weak_names = weak_prerequisite_names(progress, kp_id)
        if weak_names:
            joined = ", ".join(weak_names[:3])
            parts.append(f"weak prerequisite {joined}")
        return "; ".join(parts) + "."

    def review_reason_codes(self, progress: LearningProgress, kp_id: str) -> list[str]:
        codes: list[str] = []
        if has_active_misconception(progress, kp_id):
            codes.append(REASON_ACTIVE_MISCONCEPTION)
        if weak_prerequisite_ids(progress, kp_id):
            codes.append(REASON_WEAK_PREREQUISITE)
        return codes

    def get_due_tasks(self, progress: LearningProgress, max_tasks: int = 5) -> list[ReviewTask]:
        now = time.time()
        due = [t for t in progress.review_queue if t.due_at <= now]
        due.sort(key=lambda t: review_sort_key(t, now=now))
        return due[:max_tasks]

    def build_review_queue(
        self, progress: LearningProgress, *, now: float | None = None
    ) -> list[ReviewTask]:
        moment = time.time() if now is None else now
        error_kps = _error_kp_ids(progress)
        tasks: list[ReviewTask] = []
        for kp_id, state in progress.repetition_states.items():
            kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
            self.hydrate(state, kp_type)
            priority = 1 if kp_id in error_kps else _TYPE_PRIORITY[kp_type]
            risk = self.forgetting_risk(state, progress, kp_id, now=moment)
            tasks.append(
                ReviewTask(
                    id=f"review_{kp_id}",
                    knowledge_point_id=kp_id,
                    knowledge_type=kp_type,
                    due_at=state.next_review_at,
                    priority=priority,
                    state=state,
                    forgetting_risk=round(risk, 4),
                    reason=self.review_reason(state, progress, kp_id, now=moment),
                    reason_codes=self.review_reason_codes(progress, kp_id),
                )
            )
        tasks.sort(key=lambda t: review_sort_key(t, now=moment))
        return tasks

    def replay(
        self,
        knowledge_type: KnowledgeType,
        evidence: list[LearningEvidence],
        *,
        now: float | None = None,
    ) -> RepetitionState:
        if not evidence:
            return self.get_initial_state(knowledge_type, now=now)
        state = self.get_initial_state(knowledge_type, now=evidence[0].timestamp)
        for event in evidence:
            self.schedule_review(state, knowledge_type, event, now=event.timestamp)
        return state


def _resolved_quality(evidence: LearningEvidence) -> float:
    if evidence.quality is not None:
        return max(0.0, min(1.0, float(evidence.quality)))
    return 1.0 if evidence.result == "correct" else 0.0


def _snap_interval_index(intervals: list[int], interval_days: float, max_index: int) -> int:
    nearest = min(range(len(intervals)), key=lambda i: abs(float(intervals[i]) - interval_days))
    return max(0, min(nearest, max_index))


def _format_span(days: float) -> str:
    if days < 1.0 / 24.0:
        return "moments"
    if days < 1:
        hours = max(1, int(round(days * 24)))
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if days < 1.5:
        return "1 day"
    return f"{int(round(days))} days"


BaselineRetentionScheduler = SpacedRepetitionScheduler

__all__ = [
    "BaselineRetentionScheduler",
    "INTERVAL_SEQUENCES",
    "REASON_ACTIVE_MISCONCEPTION",
    "REASON_WEAK_PREREQUISITE",
    "RetentionScheduler",
    "SpacedRepetitionScheduler",
    "review_sort_key",
]
