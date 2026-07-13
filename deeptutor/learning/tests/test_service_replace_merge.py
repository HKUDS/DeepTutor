"""Tests for the unified LearningService pipeline.

Covers module replacement (replace_modules / init_modules both have replace
semantics and purge stale per-KP state), the recency-weighted mastery policy
with its low-confidence cap, and the fail-closed grade_and_record pipeline that
records an attempt, recomputes mastery, advances the spaced-repetition state,
rebuilds the review queue, and persists.
"""

from pathlib import Path

from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore


def _make_kp(kp_id: str, module_id: str = "m1") -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id, name=f"KP {kp_id}", type=KnowledgeType.CONCEPT, module_id=module_id
    )


def _make_module(mod_id: str, kp_ids: list[str]) -> LearningModule:
    return LearningModule(
        id=mod_id,
        name=f"Module {mod_id}",
        order=0,
        knowledge_points=[_make_kp(kid, mod_id) for kid in kp_ids],
    )


# ── replace_modules / init_modules (replace semantics) ────────────────────


class TestReplaceModules:
    def test_init_modules_replaces_existing_modules(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.init_modules(progress, [_make_module("m1", ["kp1"])])
        assert len(progress.modules) == 1
        service.init_modules(progress, [_make_module("m2", ["kp2"])])
        assert [m.id for m in progress.modules] == ["m2"]
        assert "kp1" not in progress.knowledge_types
        assert "kp2" in progress.knowledge_types

    def test_init_modules_matches_replace_semantics(self, tmp_path: Path):
        """init_modules is a thin alias for replace_modules."""
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.init_modules(progress, [_make_module("m1", ["kp1"]), _make_module("m2", ["kp2"])])
        progress.mastery_levels["kp1"] = 0.8

        service.init_modules(progress, [_make_module("m3", ["kp3"])])
        assert [m.id for m in progress.modules] == ["m3"]
        assert "kp1" not in progress.mastery_levels
        assert "kp3" in progress.knowledge_types

    def test_replace_removes_old_modules(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(
            progress, [_make_module("m1", ["kp1"]), _make_module("m2", ["kp2"])]
        )
        assert len(progress.modules) == 2

        service.replace_modules(progress, [_make_module("m3", ["kp3"])])
        assert len(progress.modules) == 1
        assert progress.modules[0].id == "m3"

    def test_replace_cleans_stale_mastery(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.mastery_levels["kp1"] = 0.8

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert "kp1" not in progress.mastery_levels

    def test_replace_cleans_stale_knowledge_types(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        assert "kp1" in progress.knowledge_types

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert "kp1" not in progress.knowledge_types
        assert "kp2" in progress.knowledge_types

    def test_replace_cleans_stale_repetition_states(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.repetition_states["kp1"] = RepetitionState(
            interval_index=0, consecutive_correct=0, consecutive_wrong=0, next_review_at=0
        )

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert "kp1" not in progress.repetition_states

    def test_replace_cleans_stale_error_records(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.error_records.append(
            ErrorRecord(
                id="er1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
            )
        )

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert len(progress.error_records) == 0

    def test_replace_cleans_stale_feynman_retries(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.feynman_retries["kp1"] = 2

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert "kp1" not in progress.feynman_retries

    def test_replace_cleans_stale_feynman_explanations(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.feynman_explanations["kp1"] = "user explanation text"

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert "kp1" not in progress.feynman_explanations

    def test_replace_cleans_stale_review_queue(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.review_queue.append(
            ReviewTask(
                id="rt1",
                knowledge_point_id="kp1",
                knowledge_type=KnowledgeType.CONCEPT,
                due_at=0,
                priority=1,
                state=RepetitionState(
                    interval_index=0, consecutive_correct=0, consecutive_wrong=0, next_review_at=0
                ),
            )
        )

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert len(progress.review_queue) == 0

    def test_replace_clears_stage_failure_records(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        progress.stage_failure_counts["explain"] = 4
        progress.stage_failure_notes["explain"] = "timeout"

        service.replace_modules(progress, [_make_module("m2", ["kp2"])])
        assert progress.stage_failure_counts == {}
        assert progress.stage_failure_notes == {}

    def test_replace_preserves_new_module_kps(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        assert "kp1" in progress.knowledge_types
        assert progress.modules[0].knowledge_points[0].id == "kp1"

    def test_replace_keeps_state_for_surviving_kps(self, tmp_path: Path):
        """A KP that exists in both the old and new module set keeps its state."""
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")

        service.replace_modules(progress, [_make_module("m1", ["kp1", "kp2"])])
        progress.mastery_levels["kp1"] = 0.8
        progress.mastery_levels["kp2"] = 0.3

        # kp1 survives into the new module set, kp2 is dropped.
        service.replace_modules(progress, [_make_module("m2", ["kp1"])])
        assert progress.mastery_levels["kp1"] == 0.8
        assert "kp2" not in progress.mastery_levels


# ── mastery policy (recency-weighted with low-confidence cap) ─────────────


class TestMasteryPolicy:
    def _service_with_attempts(self, tmp_path: Path, kp_id: str, outcomes: list[bool]):
        from deeptutor.learning.models import QuizAttempt

        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="test")
        for correct in outcomes:
            progress.quiz_attempts.append(
                QuizAttempt(question_id="q", knowledge_point_id=kp_id, is_correct=correct)
            )
        return service, progress

    def test_no_attempts_is_zero(self, tmp_path: Path):
        service, progress = self._service_with_attempts(tmp_path, "kp1", [])
        assert service.calculate_mastery(progress, "kp1") == 0.0

    def test_single_correct_attempt_is_capped_at_half(self, tmp_path: Path):
        """One lucky correct answer cannot declare a point mastered."""
        service, progress = self._service_with_attempts(tmp_path, "kp1", [True])
        assert service.calculate_mastery(progress, "kp1") == 0.5

    def test_single_wrong_attempt_is_zero(self, tmp_path: Path):
        service, progress = self._service_with_attempts(tmp_path, "kp1", [False])
        assert service.calculate_mastery(progress, "kp1") == 0.0

    def test_two_correct_attempts_capped_at_point_eight(self, tmp_path: Path):
        service, progress = self._service_with_attempts(tmp_path, "kp1", [True, True])
        assert service.calculate_mastery(progress, "kp1") == 0.8

    def test_three_plus_correct_can_reach_one(self, tmp_path: Path):
        service, progress = self._service_with_attempts(tmp_path, "kp1", [True, True, True])
        assert service.calculate_mastery(progress, "kp1") == 1.0

    def test_more_correct_attempts_score_higher_once_uncapped(self, tmp_path: Path):
        """With enough evidence (3+ attempts) the cap lifts, so a mostly-correct
        history scores strictly higher than a mostly-wrong one."""
        mostly_right, p_right = self._service_with_attempts(tmp_path, "kp1", [True, True, False])
        mostly_wrong, p_wrong = self._service_with_attempts(tmp_path, "kp2", [False, False, True])

        right_score = mostly_right.calculate_mastery(p_right, "kp1")
        wrong_score = mostly_wrong.calculate_mastery(p_wrong, "kp2")

        # Three attempts with two correct clears the single-attempt cap of 0.5.
        assert right_score > 0.5
        assert right_score > wrong_score


# ── grade_and_record (unified fail-closed pipeline) ───────────────────────


class TestGradeAndRecord:
    def _progress(self, tmp_path: Path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = LearningProgress(book_id="book1")
        service.replace_modules(progress, [_make_module("m1", ["kp1"])])
        return store, service, progress

    def test_correct_answer_records_and_updates_mastery(self, tmp_path: Path):
        store, service, progress = self._progress(tmp_path)

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="paris",
            expected_answer="paris",
        )

        assert result is True
        assert len(progress.quiz_attempts) == 1
        assert progress.quiz_attempts[0].is_correct is True
        # A single correct attempt is capped at 0.5 by the mastery policy.
        assert progress.mastery_levels["kp1"] == 0.5
        # Pipeline persists.
        loaded = store.load("book1")
        assert loaded is not None
        assert len(loaded.quiz_attempts) == 1

    def test_wrong_answer_records_error_with_application_type(self, tmp_path: Path):
        store, service, progress = self._progress(tmp_path)

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="london",
            expected_answer="paris",
        )

        assert result is False
        assert len(progress.error_records) == 1
        assert progress.error_records[0].error_type == ErrorType.APPLICATION_ERROR
        assert progress.error_records[0].status == "active"

    def test_blank_wrong_answer_is_metacognitive(self, tmp_path: Path):
        store, service, progress = self._progress(tmp_path)

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="   ",
            expected_answer="paris",
        )

        assert result is False
        assert progress.error_records[0].error_type == ErrorType.METACOGNITIVE

    def test_fail_closed_when_no_expected_answer(self, tmp_path: Path):
        """With no stored expected answer, grading must record wrong, never right."""
        store, service, progress = self._progress(tmp_path)

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="anything",
            expected_answer="",
        )

        assert result is False
        assert progress.quiz_attempts[0].is_correct is False

    def test_correct_answer_graduates_active_error_record(self, tmp_path: Path):
        store, service, progress = self._progress(tmp_path)

        # First answer is wrong -> opens an active error record.
        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="london",
            expected_answer="paris",
        )
        assert progress.error_records[0].status == "active"

        # Second answer is correct -> graduates the record.
        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="paris",
            expected_answer="paris",
        )
        assert progress.error_records[0].status == "graduated"

    def test_scheduler_advances_state_and_rebuilds_review_queue(self, tmp_path: Path):
        store, service, progress = self._progress(tmp_path)
        scheduler = SpacedRepetitionScheduler()

        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="paris",
            expected_answer="paris",
            scheduler=scheduler,
        )

        # A repetition state was created and the review queue rebuilt for it.
        assert "kp1" in progress.repetition_states
        assert progress.repetition_states["kp1"].consecutive_correct == 1
        assert [t.knowledge_point_id for t in progress.review_queue] == ["kp1"]

    def test_no_scheduler_leaves_review_state_untouched(self, tmp_path: Path):
        store, service, progress = self._progress(tmp_path)

        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="paris",
            expected_answer="paris",
        )

        assert progress.repetition_states == {}
        assert progress.review_queue == []
