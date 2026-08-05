from __future__ import annotations

import os
import time

from deeptutor.learning.models import (
    KnowledgeType,
    LearningProgress,
    MasteryState,
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

# ── Feynman scheduling policy (spec §6.1, §6.5; LRN-02 requirement 7) ──────
# Delays are in days and deterministic: the projection anchors them to the
# assessment timestamp, so rebuilds never depend on wall-clock races.

#: Days between a provisional pass (initial or test-out) and the first
#: delayed-reteach review. Test-out still requires this reteach — it can never
#: jump straight to stable mastery (§6.5).
PROVISIONAL_RETEACH_DELAY_DAYS: dict[KnowledgeType, int] = {
    KnowledgeType.MEMORY: 1,
    KnowledgeType.CONCEPT: 3,
    KnowledgeType.PROCEDURE: 3,
    KnowledgeType.DESIGN: 7,
}

#: Days between a delayed-reteach pass (stable mastery) and the next
#: maintenance review (§6.2).
STABLE_MAINTENANCE_DELAY_DAYS: dict[KnowledgeType, int] = {
    KnowledgeType.MEMORY: 7,
    KnowledgeType.CONCEPT: 14,
    KnowledgeType.PROCEDURE: 14,
    KnowledgeType.DESIGN: 28,
}

#: Days before retrying a review/reevaluation that failed, at which point the
#: projection returns to ``needs_revision`` and re-schedules (§6.2).
FAILED_REVIEW_RETRY_DELAY_DAYS: dict[KnowledgeType, int] = {
    KnowledgeType.MEMORY: 1,
    KnowledgeType.CONCEPT: 1,
    KnowledgeType.PROCEDURE: 1,
    KnowledgeType.DESIGN: 1,
}


class SpacedRepetitionScheduler:
    def __init__(self, *, now: float | None = None) -> None:
        # When True, intervals are in seconds instead of days (for testing).
        self.DEBUG_MODE: bool = os.environ.get("LEARNING_DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
        )
        # Optional deterministic clock so tests never race wall time.
        self._now: float | None = now

    def _resolve_now(self, now: float | None) -> float:
        if now is not None:
            return now
        if self._now is not None:
            return self._now
        return time.time()

    def _seconds_per_unit(self) -> float:
        return 1.0 if self.DEBUG_MODE else 86400.0

    def get_initial_state(self, knowledge_type: KnowledgeType) -> RepetitionState:
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=self._resolve_now(None) + intervals[0] * self._seconds_per_unit(),
        )

    def schedule_next(
        self, state: RepetitionState, knowledge_type: KnowledgeType, is_correct: bool
    ) -> RepetitionState:
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        max_index = len(intervals) - 1

        if is_correct:
            state.consecutive_wrong = 0
            state.consecutive_correct += 1
            if state.consecutive_correct >= 2:
                state.interval_index += 2
                state.consecutive_correct = 0
            else:
                state.interval_index += 1
        else:
            state.consecutive_wrong += 1
            state.consecutive_correct = 0
            state.interval_index = max(0, state.interval_index - 1)
            if state.consecutive_wrong >= 2:
                state.consecutive_wrong = 0

        state.interval_index = max(0, min(state.interval_index, max_index))
        state.next_review_at = (
            self._resolve_now(None) + intervals[state.interval_index] * self._seconds_per_unit()
        )
        return state

    # ── Feynman scheduling helpers (deterministic, ``now``-injected) ─────

    def schedule_provisional_reteach(
        self, knowledge_type: KnowledgeType, *, now: float | None = None
    ) -> RepetitionState:
        """Schedule the first delayed-reteach after a provisional pass."""
        moment = self._resolve_now(now)
        days = PROVISIONAL_RETEACH_DELAY_DAYS.get(knowledge_type, 1)
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=moment + days * self._seconds_per_unit(),
        )

    def schedule_stable_maintenance(
        self, knowledge_type: KnowledgeType, *, now: float | None = None
    ) -> RepetitionState:
        """Schedule the next maintenance review after a delayed-reteach pass."""
        moment = self._resolve_now(now)
        days = STABLE_MAINTENANCE_DELAY_DAYS.get(knowledge_type, 1)
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=moment + days * self._seconds_per_unit(),
        )

    def schedule_failed_review(
        self, knowledge_type: KnowledgeType, *, now: float | None = None
    ) -> RepetitionState:
        """Re-schedule a review that failed, projecting back to needs_revision."""
        moment = self._resolve_now(now)
        days = FAILED_REVIEW_RETRY_DELAY_DAYS.get(knowledge_type, 1)
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=moment + days * self._seconds_per_unit(),
        )

    def build_feynman_review_queue(
        self, progress: LearningProgress, *, now: float | None = None
    ) -> list[ReviewTask]:
        """Rebuild the review queue from the per-KP projections.

        ``needs_revision`` points get the highest priority (1); otherwise the
        knowledge type's base priority applies. Tasks are ordered by priority
        then due time.
        """
        moment = self._resolve_now(now)
        tasks: list[ReviewTask] = []
        for kp_id, projection in progress.projections.items():
            if projection.next_review_at is None:
                continue
            kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
            if projection.mastery_state == MasteryState.NEEDS_REVISION:
                priority = 1
            else:
                priority = _TYPE_PRIORITY.get(kp_type, 2)
            tasks.append(
                ReviewTask(
                    id=f"review_{kp_id}",
                    knowledge_point_id=kp_id,
                    knowledge_type=kp_type,
                    due_at=projection.next_review_at,
                    priority=priority,
                    state=RepetitionState(
                        interval_index=0,
                        consecutive_correct=0,
                        consecutive_wrong=0,
                        next_review_at=projection.next_review_at,
                    ),
                )
            )
        tasks.sort(key=lambda task: (task.priority, task.due_at))
        return tasks

    def get_due_tasks(self, progress: LearningProgress, max_tasks: int = 5) -> list[ReviewTask]:
        now = self._resolve_now(None)
        due = [t for t in progress.review_queue if t.due_at <= now]
        due.sort(key=lambda t: t.priority)
        return due[:max_tasks]

    def build_review_queue(self, progress: LearningProgress) -> list[ReviewTask]:
        tasks: list[ReviewTask] = []
        error_kps: set[str] = set()
        for rec in progress.error_records:
            if rec.status in ("active", "retrying"):
                error_kps.add(rec.knowledge_point_id)

        for kp_id, state in progress.repetition_states.items():
            kp_type = progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
            priority = 1 if kp_id in error_kps else _TYPE_PRIORITY[kp_type]
            tasks.append(
                ReviewTask(
                    id=f"review_{kp_id}",
                    knowledge_point_id=kp_id,
                    knowledge_type=kp_type,
                    due_at=state.next_review_at,
                    priority=priority,
                    state=state,
                )
            )
        return tasks


__all__ = [
    "SpacedRepetitionScheduler",
    "INTERVAL_SEQUENCES",
    "PROVISIONAL_RETEACH_DELAY_DAYS",
    "STABLE_MAINTENANCE_DELAY_DAYS",
    "FAILED_REVIEW_RETRY_DELAY_DAYS",
]
