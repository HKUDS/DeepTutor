"""Failed reviews repair the decay model without demoting passed objectives (#2458)."""

import time

from deeptutor.learning.models import KnowledgeType, LearningProgress
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore

SEVEN_DAYS_AGO = time.time() - 7 * 86400


def _progress_with_knowledge(kinds: dict[str, KnowledgeType]) -> LearningProgress:
    progress = LearningProgress(book_id="synthetic")
    progress.knowledge_types.update(kinds)
    return progress


def _grade(service, progress, kp, correct, verdict=None):
    return service._apply_grade(
        progress,
        question_id=f"{kp}-q-{progress.updated_at}",
        knowledge_point_id=kp,
        module_id="m",
        user_answer="expected" if correct else "wrong",
        expected_answer="expected" if correct else "different",
        question_type="short",
        scheduler=SpacedRepetitionScheduler(),
        verdict=verdict,
    )


def test_failed_review_does_not_demote_mastered_objective(tmp_path):
    progress = _progress_with_knowledge({"kp": KnowledgeType.MEMORY})
    service = LearningService(LearningStore(tmp_path))
    for _ in range(5):
        assert _grade(service, progress, "kp", True)
    assert progress.mastery_levels["kp"] >= 0.9
    state = progress.repetition_states["kp"]
    state.last_review_at = SEVEN_DAYS_AGO
    review_count = state.review_count

    assert not _grade(service, progress, "kp", False)
    assert progress.mastery_levels["kp"] >= 0.9
    assert progress.repetition_states["kp"].review_count > review_count


def test_failed_quiz_attempt_on_not_yet_mastered_objective_still_drops_mastery(tmp_path):
    progress = _progress_with_knowledge({"kp": KnowledgeType.MEMORY})
    service = LearningService(LearningStore(tmp_path))
    _grade(service, progress, "kp", True)
    assert progress.mastery_levels["kp"] < 0.9
    _grade(service, progress, "kp", False)
    assert progress.mastery_levels["kp"] < 0.5


def test_failed_qualitative_review_keeps_passed_state(tmp_path):
    progress = _progress_with_knowledge({"kp": KnowledgeType.CONCEPT})
    progress.qualitative_mastery["kp"] = True
    progress.mastery_levels["kp"] = 1.0
    service = LearningService(LearningStore(tmp_path))
    scheduler = SpacedRepetitionScheduler()

    assert service.record_qualitative_in_memory(
        progress, "kp", passed=False, scheduler=scheduler, session_id="s"
    )
    assert progress.qualitative_mastery["kp"] is True
    assert progress.mastery_levels["kp"] == 1.0


def test_failed_qualitative_only_assessment_still_demotes(tmp_path):
    progress = _progress_with_knowledge({"kp": KnowledgeType.CONCEPT})
    progress.mastery_levels["kp"] = 0.9
    service = LearningService(LearningStore(tmp_path))

    assert service.record_qualitative_in_memory(
        progress, "kp", passed=False, scheduler=SpacedRepetitionScheduler(), session_id="s"
    )
    assert progress.qualitative_mastery["kp"] is False
    assert progress.mastery_levels["kp"] == 0.4
