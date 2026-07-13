from __future__ import annotations

import os
import time

from deeptutor.learning.models import (
    KnowledgeType,
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


class SpacedRepetitionScheduler:
    def __init__(self) -> None:
        # When True, intervals are in seconds instead of days (for testing)
        self.DEBUG_MODE: bool = os.environ.get("LEARNING_DEBUG", "").lower() in ("1", "true", "yes")

    def _seconds_per_unit(self) -> float:
        return 1.0 if self.DEBUG_MODE else 86400.0

    def get_initial_state(self, knowledge_type: KnowledgeType) -> RepetitionState:
        intervals = INTERVAL_SEQUENCES[knowledge_type]
        return RepetitionState(
            interval_index=0,
            consecutive_correct=0,
            consecutive_wrong=0,
            next_review_at=time.time() + intervals[0] * self._seconds_per_unit(),
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
            time.time() + intervals[state.interval_index] * self._seconds_per_unit()
        )
        return state

    def get_due_tasks(self, progress: LearningProgress, max_tasks: int = 5) -> list[ReviewTask]:
        now = time.time()
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


__all__ = ["SpacedRepetitionScheduler", "INTERVAL_SEQUENCES"]
