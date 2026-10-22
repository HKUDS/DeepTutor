"""The mastery review plan must not advertise objectives below the mastery gate."""

import time

from deeptutor.api.routers.mastery_path import _review_queue
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    RepetitionState,
    ReviewTask,
)


def test_review_queue_only_exposes_mastered_objectives():
    progress = LearningProgress(book_id="path")
    mastered = KnowledgePoint(
        id="mastered", name="Mastered objective", type=KnowledgeType.MEMORY, module_id="m1"
    )
    learning = KnowledgePoint(
        id="learning", name="Learning objective", type=KnowledgeType.MEMORY, module_id="m1"
    )
    progress.modules = [
        LearningModule(id="m1", name="Module", order=0, knowledge_points=[mastered, learning])
    ]
    progress.mastery_levels[mastered.id] = 0.95
    now = time.time()
    progress.review_queue = [
        ReviewTask(
            id=f"review_{kp.id}",
            knowledge_point_id=kp.id,
            knowledge_type=kp.type,
            due_at=now - 10,
            priority=1,
            state=RepetitionState(next_review_at=now - 10),
        )
        for kp in (learning, mastered)
    ]

    result = _review_queue(progress, now=now)

    assert [item["knowledge_point_id"] for item in result] == [mastered.id]
