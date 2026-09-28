from __future__ import annotations

import math
import os
import time
from typing import Protocol

from deeptutor.learning.models import (
    KnowledgeType,
    LearningEvidence,
    LearningProgress,
    RepetitionState,
    ReviewTask,
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
MIN_DESIRED_RETENTION = 0.7
MAX_DESIRED_RETENTION = 0.99
_MIN_STABILITY_DAYS = 0.5
_FAIL_QUALITY = 0.5
_EPS = 1e-6
# Short-interval practice is not another durable retrieval (#1541). The
# threshold uses a fixed baseline interval, not the learner's configurable
# recall target, so changing that target cannot alter replayed transitions.
_SAME_SESSION_DAYS = 0.25
_EVIDENCE_SOURCE_LABELS = {
    "deep_question": "Question Bank",
    "immersive_reading": "Reading",
    "book": "Book",
    "partner_chat": "Study Partner",
    "import": "Imported",
}


def validate_desired_retention(value: float) -> float:
    desired = float(value)
    if not math.isfinite(desired) or not MIN_DESIRED_RETENTION <= desired <= MAX_DESIRED_RETENTION:
        raise ValueError(
            f"desired_retention must be between {MIN_DESIRED_RETENTION} and {MAX_DESIRED_RETENTION}"
        )
    return desired


class RetentionScheduler(Protocol):
    """Pluggable retention model. The default baseline is exponential forgetting
    with type-specific cold-start priors — not a calibrated FSRS fit.
    """

    def get_initial_state(
        self,
        knowledge_type: KnowledgeType,
        *,
        now: float | None = None,
        desired_retention: float | None = None,
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
        desired_retention: float | None = None,
        initial_state: RepetitionState | None = None,
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
    def __init__(self, *, desired_retention: float = DEFAULT_DESIRED_RETENTION) -> None:
        # When True, intervals are in seconds instead of days (for testing)
        self.DEBUG_MODE: bool = os.environ.get("LEARNING_DEBUG", "").lower() in ("1", "true", "yes")
        self.desired_retention = validate_desired_retention(desired_retention)

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

    def _scheduled_interval_days(
        self, state: RepetitionState, knowledge_type: KnowledgeType
    ) -> float:
        if state.review_count == 0 and INTERVAL_SEQUENCES[knowledge_type][0] == 0:
            return 0.0
        interval_days = self._interval_from_stability(state.stability, state.desired_retention)
        if state.scheduled_after_failure:
            interval_days = min(
                interval_days,
                max(interval_days * 0.5, _MIN_STABILITY_DAYS * 0.2),
            )
        return interval_days

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
        self,
        knowledge_type: KnowledgeType,
        *,
        now: float | None = None,
        desired_retention: float | None = None,
    ) -> RepetitionState:
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        first_interval = float(intervals[0])
        moment = time.time() if now is None else now
        desired = (
            self.desired_retention
            if desired_retention is None
            else validate_desired_retention(desired_retention)
        )
        stability = self._stability_from_interval(first_interval, DEFAULT_DESIRED_RETENTION)
        initial_interval = (
            first_interval
            if first_interval == 0
            else self._interval_from_stability(stability, desired)
        )
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=moment + initial_interval * self._seconds_per_unit(),
            difficulty=_TYPE_DIFFICULTY[knowledge_type],
            stability=stability,
            retrievability=1.0,
            desired_retention=desired,
            review_count=0,
            lapse_count=0,
            last_review_at=None,
            last_scheduled_at=moment,
            scheduled_after_failure=False,
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
        event_moment = evidence.timestamp if now is None else now
        # A delayed cross-surface write keeps its source timestamp for audit,
        # but cannot move the learner's last review backwards in time.
        moment = (
            max(event_moment, state.last_review_at)
            if state.last_review_at is not None
            else event_moment
        )
        quality = _resolved_quality(evidence)
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        max_index = len(intervals) - 1

        # A successful delayed retrieval is stronger evidence than an
        # immediate repetition. Measure the state before applying the review;
        # replay uses the event timestamp and therefore follows this exact
        # transition deterministically.
        previous_stability = max(state.stability, _EPS)
        previous_retrievability = self.retrievability(state, now=moment)
        elapsed_days = (
            max(0.0, moment - state.last_review_at) / self._seconds_per_unit()
            if state.last_review_at is not None
            else 0.0
        )
        same_session_days = min(
            _SAME_SESSION_DAYS,
            self._interval_from_stability(previous_stability, DEFAULT_DESIRED_RETENTION) * 0.5,
        )
        if (
            quality >= _FAIL_QUALITY
            and state.last_review_at is not None
            and elapsed_days < same_session_days
        ):
            # Repeated practice refreshes recall, but must not repeatedly
            # multiply stability or postpone the original review deadline.
            state.review_count += 1
            state.last_review_at = moment
            state.retrievability = 1.0
            state.consecutive_wrong = 0
            return state
        spacing_ratio = min(elapsed_days / previous_stability, 4.0)

        # Difficulty is an item/learner estimate, not the knowledge-type
        # category. Surprising failures raise it; strong retrieval lowers it.
        outcome_error = (1.0 - quality) - state.difficulty
        surprise = previous_retrievability - quality
        state.difficulty = float(
            min(0.95, max(0.05, state.difficulty + 0.12 * outcome_error + 0.08 * surprise))
        )

        if quality < _FAIL_QUALITY:
            state.consecutive_wrong += 1
            state.consecutive_correct = 0
            state.lapse_count += 1
            # Forgetting something that was predicted to be retrievable is a
            # stronger negative update. A hard item also recovers less of its
            # prior stability after a lapse.
            retention_factor = 0.55 - 0.25 * previous_retrievability
            difficulty_factor = 1.0 - 0.25 * state.difficulty
            state.stability = max(
                _MIN_STABILITY_DAYS * 0.1,
                previous_stability * retention_factor * difficulty_factor,
            )
            state.retrievability = max(quality, 0.2)
            if state.consecutive_wrong >= 2:
                state.consecutive_wrong = 0
        else:
            state.consecutive_wrong = 0
            state.consecutive_correct += 1
            retrieval_effort = 1.0 + (1.0 - previous_retrievability) * 1.5
            spacing_bonus = 1.0 + spacing_ratio * 0.15
            learnability = 1.35 - 0.6 * state.difficulty
            quality_strength = max(0.0, (quality - _FAIL_QUALITY) / (1.0 - _FAIL_QUALITY))
            growth = 1.0 + quality_strength * learnability * retrieval_effort * spacing_bonus
            if quality >= 0.8 and state.consecutive_correct >= 2:
                growth *= 1.15
            state.stability = max(_MIN_STABILITY_DAYS, previous_stability * growth)
            state.retrievability = 1.0
            if state.consecutive_correct >= 2:
                state.consecutive_correct = 0

        state.review_count += 1
        state.last_review_at = moment
        state.last_scheduled_at = moment
        state.scheduled_after_failure = quality < _FAIL_QUALITY
        interval_days = self._scheduled_interval_days(state, knowledge_type)
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
        return float(min(1.0, max(0.0, risk)))

    def review_reason(
        self,
        state: RepetitionState,
        progress: LearningProgress,
        kp_id: str,
        *,
        now: float | None = None,
        latest_evidence: LearningEvidence | None = None,
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
        if latest_evidence is not None:
            source = _EVIDENCE_SOURCE_LABELS.get(latest_evidence.source)
            if source is not None:
                parts.append(f"latest {source} assessment: {latest_evidence.result}")
        return "; ".join(parts) + "."

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
        latest_evidence: dict[str, LearningEvidence] = {}
        for event in progress.learning_evidence:
            # The newest applied event is the last durable append, even if a
            # cross-surface assessment carried an earlier source timestamp.
            latest_evidence[event.knowledge_point_id] = event
        tasks: list[ReviewTask] = []
        for kp_id, state in progress.repetition_states.items():
            kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
            self.hydrate(state, kp_type)
            priority = 1 if kp_id in error_kps else _TYPE_PRIORITY[kp_type]
            risk = self.forgetting_risk(state, progress, kp_id, now=moment)
            evidence = latest_evidence.get(kp_id)
            tasks.append(
                ReviewTask(
                    id=f"review_{kp_id}",
                    knowledge_point_id=kp_id,
                    knowledge_type=kp_type,
                    due_at=state.next_review_at,
                    priority=priority,
                    state=state,
                    forgetting_risk=round(risk, 4),
                    reason=self.review_reason(
                        state, progress, kp_id, now=moment, latest_evidence=evidence
                    ),
                    evidence_source=evidence.source if evidence is not None else "",
                    evidence_id=evidence.evidence_id if evidence is not None else "",
                )
            )
        tasks.sort(key=lambda t: review_sort_key(t, now=moment))
        return tasks

    def set_desired_retention(
        self,
        progress: LearningProgress,
        desired_retention: float,
        *,
        now: float | None = None,
    ) -> None:
        """Change one path's target without rewriting its evidence history.

        Rescale the already scheduled interval, including a shorter failure
        retry. Do not count a settings edit as an assessment (#1541).
        """
        desired = validate_desired_retention(desired_retention)
        moment = time.time() if now is None else now
        for kp_id, state in progress.repetition_states.items():
            kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
            self.hydrate(state, kp_type)
            old_desired = validate_desired_retention(state.desired_retention)
            anchor = state.last_scheduled_at
            state.desired_retention = desired
            if anchor is not None:
                interval = self._scheduled_interval_days(state, kp_type)
                state.next_review_at = anchor + interval * self._seconds_per_unit()
                interval = (state.next_review_at - anchor) / self._seconds_per_unit()
                intervals = INTERVAL_SEQUENCES[kp_type]
                state.interval_index = _snap_interval_index(intervals, interval, len(intervals) - 1)
            elif state.last_review_at is not None:
                # Pre-#1541 states have no schedule anchor. Preserve their
                # existing interval until the next actual review establishes it.
                ratio = -math.log(desired) / -math.log(old_desired)
                state.next_review_at = (
                    state.last_review_at + (state.next_review_at - state.last_review_at) * ratio
                )
            elif state.next_review_at > moment:
                # Legacy snapshots may lack a review anchor; preserve their
                # overdue position and only scale remaining future time.
                ratio = -math.log(desired) / -math.log(old_desired)
                state.next_review_at = moment + (state.next_review_at - moment) * ratio
        progress.desired_retention = desired
        progress.review_queue = self.build_review_queue(progress, now=moment)

    def replay(
        self,
        knowledge_type: KnowledgeType,
        evidence: list[LearningEvidence],
        *,
        now: float | None = None,
        desired_retention: float | None = None,
        initial_state: RepetitionState | None = None,
    ) -> RepetitionState:
        if initial_state is not None:
            if desired_retention is not None:
                raise ValueError("initial_state already contains desired_retention")
            state = initial_state.model_copy(deep=True)
            for event in evidence:
                self.schedule_review(state, knowledge_type, event, now=event.timestamp)
            return state
        if not evidence:
            return self.get_initial_state(
                knowledge_type, now=now, desired_retention=desired_retention
            )
        state = self.get_initial_state(
            knowledge_type,
            now=evidence[0].timestamp,
            desired_retention=desired_retention,
        )
        for event in evidence:
            self.schedule_review(state, knowledge_type, event, now=event.timestamp)
        return state


def _resolved_quality(evidence: LearningEvidence) -> float:
    if evidence.quality is not None:
        quality = float(evidence.quality)
    elif evidence.result == "correct":
        quality = 1.0
    elif evidence.result == "partial":
        quality = 0.4
    else:
        quality = 0.0
    if evidence.quality is None:
        quality -= min(0.25, evidence.hints_used * 0.08)
        quality -= min(0.2, max(0, evidence.attempt_count - 1) * 0.05)
    return max(0.0, min(1.0, quality))


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
    "RetentionScheduler",
    "SpacedRepetitionScheduler",
    "review_sort_key",
]
