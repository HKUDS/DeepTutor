"""Tests for the grading module and the unified post-answer pipeline.

``grade_answer`` is the pure correctness check. ``classify_error`` is the
coarse wrong-answer tagger. ``LearningService.grade_and_record`` folds both of
those through the full record -> mastery -> spaced-repetition pipeline and is
fail-closed: with no stored expected answer the attempt is recorded wrong.
"""

import json
from pathlib import Path

import pytest

from deeptutor.learning.grading import classify_error, grade_answer, numeric_equivalent
from deeptutor.learning.models import (
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore


class TestChoiceGrading:
    def test_choice_exact_match(self):
        assert grade_answer("A", "A", "choice") is True

    def test_choice_case_insensitive(self):
        assert grade_answer("b", "B", "choice") is True

    def test_choice_with_spaces(self):
        assert grade_answer("A ", " A", "choice") is True

    def test_choice_wrong(self):
        assert grade_answer("C", "A", "choice") is False


class TestShortGrading:
    def test_short_exact_match(self):
        assert grade_answer("photosynthesis", "photosynthesis", "short") is True

    def test_short_fuzzy_pass(self):
        # "photosynthesi" vs "photosynthesis" — high similarity
        assert grade_answer("photosynthesi", "photosynthesis", "short") is True

    def test_short_fuzzy_fail(self):
        assert grade_answer("completely different", "photosynthesis", "short") is False

    @pytest.mark.parametrize(
        ("user", "expected"),
        [("1250.60", "1250.50"), ("-200", "200"), ("x=3, y=4", "x=3, y=5"), ("125000", "125.000")],
    )
    def test_numeric_key_is_never_fuzzy_matched(self, user, expected):
        assert grade_answer(user, expected, "short") is False

    @pytest.mark.parametrize(
        ("user", "expected"),
        [("1.250,50", "1250.50"), ("1250,50 €", "1250.50"), ("1/8", "0.125"), ("12.5%", "0.125")],
    )
    def test_numeric_formats_are_accepted(self, user, expected):
        assert grade_answer(user, expected, "short") is True

    def test_short_long_expected_no_fuzzy(self):
        long_expected = "a" * 31  # >30 chars, no fuzzy
        assert grade_answer(long_expected, long_expected, "short") is True
        assert grade_answer("something else entirely", long_expected, "short") is False


class TestOpenGrading:
    def test_open_keywords_pass(self):
        expected = "cell membrane, nucleus, mitochondria"
        user = "The cell has a cell membrane and nucleus, with mitochondria for energy"
        assert grade_answer(user, expected, "open") is True

    def test_open_keywords_fail(self):
        expected = "cell membrane, nucleus, mitochondria"
        user = "I don't know anything about cells"
        assert grade_answer(user, expected, "open") is False

    def test_open_chinese_separators(self):
        expected = "光合作用；叶绿体；二氧化碳"
        user = "光合作用发生在叶绿体中，需要二氧化碳"
        assert grade_answer(user, expected, "open") is True


class TestEdgeCases:
    def test_empty_expected_returns_false(self):
        assert grade_answer("anything", "", "short") is False
        assert grade_answer("anything", "  ", "short") is False

    def test_empty_user_answer(self):
        assert grade_answer("", "expected", "short") is False

    def test_substring_no_longer_matches(self):
        """Regression: 'expected in user' substring match must not cause false positive."""
        user = "I do not know electromagnetic induction but maybe something else"
        expected = "electromagnetic induction"
        assert grade_answer(user, expected, "short") is False

    def test_unknown_type_returns_false(self):
        assert grade_answer("a", "a", "unknown") is False


_VECTORS = json.loads(
    (Path(__file__).parents[3] / "tests/fixtures/numeric_answers.json").read_text("utf-8")
)["vectors"]


@pytest.mark.parametrize("vector", _VECTORS, ids=lambda v: f"{v['user']!r}~{v['expected']!r}")
def test_numeric_equivalent_shared_vectors(vector):
    """The web port consumes the same file, so both implementations agree."""
    result = numeric_equivalent(vector["user"], vector["expected"])
    assert result.comparable is vector["comparable"]
    assert result.correct is vector["correct"]
    assert result.ambiguous is vector.get("ambiguous", False)


class TestNumericEquivalent:
    def test_parts_report_each_comparison(self):
        result = numeric_equivalent("b) 3,6; a) 12", "a) 12; b) 3,5")
        assert [(p.label, p.correct) for p in result.parts] == [("a", True), ("b", False)]
        assert (result.comparable, result.correct) == (True, False)

    def test_explicit_tolerance_overrides_key_precision(self):
        assert numeric_equivalent("101", "100").correct is False
        assert numeric_equivalent("101", "100", rel_tol=0.01).correct is True
        assert numeric_equivalent("3.49", "3.48", abs_tol=0.02).correct is True
        assert numeric_equivalent("3.51", "3.48", abs_tol=0.02).correct is False


class TestClassifyError:
    """Coarse wrong-answer tagging used by the post-answer pipeline.

    Blank means "I didn't know" (metacognitive); anything else is treated as a
    wrong application. The richer taxonomy is assigned later by the LLM.
    """

    def test_blank_answer_is_metacognitive(self):
        assert classify_error("") is ErrorType.METACOGNITIVE

    def test_whitespace_only_answer_is_metacognitive(self):
        assert classify_error("   \n\t  ") is ErrorType.METACOGNITIVE

    def test_nonblank_answer_is_application_error(self):
        assert classify_error("the answer is 42") is ErrorType.APPLICATION_ERROR


def _progress_with_kp(kp_type: KnowledgeType = KnowledgeType.CONCEPT) -> LearningProgress:
    progress = LearningProgress(book_id="book1")
    progress.modules = [
        LearningModule(
            id="m1",
            name="Module 1",
            order=0,
            knowledge_points=[KnowledgePoint(id="kp1", name="KP1", type=kp_type, module_id="m1")],
        )
    ]
    progress.knowledge_types["kp1"] = kp_type
    return progress


class TestGradeAndRecordFailClosed:
    """``grade_and_record`` is the single post-answer pipeline. It must never
    grade an answer correct when there is no stored expected answer, and it must
    fold correctness through attempt history, mastery, and error records."""

    def test_no_expected_answer_is_wrong_and_records_error(self, tmp_path):
        service = LearningService(LearningStore(root=tmp_path))
        progress = _progress_with_kp()

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="anything plausible",
            expected_answer="",  # missing expected -> fail-closed
        )

        assert result is False
        assert len(progress.quiz_attempts) == 1
        attempt = progress.quiz_attempts[0]
        assert attempt.is_correct is False
        # Non-blank wrong answer is an application error and opens an error record.
        assert attempt.error_type is ErrorType.APPLICATION_ERROR
        assert len(progress.error_records) == 1
        assert progress.error_records[0].status == "active"
        assert progress.error_records[0].error_type is ErrorType.APPLICATION_ERROR

    def test_blank_wrong_answer_is_metacognitive(self, tmp_path):
        service = LearningService(LearningStore(root=tmp_path))
        progress = _progress_with_kp()

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="",
            expected_answer="photosynthesis",
        )

        assert result is False
        assert progress.quiz_attempts[0].error_type is ErrorType.METACOGNITIVE

    def test_correct_answer_records_and_caps_single_attempt_mastery(self, tmp_path):
        service = LearningService(LearningStore(root=tmp_path))
        progress = _progress_with_kp()

        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="photosynthesis",
            expected_answer="photosynthesis",
        )

        assert result is True
        assert progress.quiz_attempts[0].is_correct is True
        assert progress.quiz_attempts[0].error_type is None
        # A single correct attempt is capped at low confidence (0.5), never 1.0.
        assert progress.mastery_levels["kp1"] == 0.5
        assert progress.error_records == []

    def test_correct_answer_graduates_existing_error_record(self, tmp_path):
        service = LearningService(LearningStore(root=tmp_path))
        progress = _progress_with_kp()

        # First a wrong answer opens an error record...
        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="wrong guess",
            expected_answer="photosynthesis",
        )
        assert progress.error_records[0].status == "active"

        # ...then a correct retry graduates it.
        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="photosynthesis",
            expected_answer="photosynthesis",
        )

        assert progress.error_records[0].status == "graduated"

    def test_persists_through_store(self, tmp_path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        progress = _progress_with_kp()

        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="photosynthesis",
            expected_answer="photosynthesis",
        )

        loaded = store.load("book1")
        assert loaded is not None
        assert len(loaded.quiz_attempts) == 1
        assert loaded.mastery_levels["kp1"] == 0.5

    def test_scheduler_advances_repetition_and_builds_queue(self, tmp_path):
        store = LearningStore(root=tmp_path)
        service = LearningService(store)
        scheduler = SpacedRepetitionScheduler()
        progress = _progress_with_kp(KnowledgeType.CONCEPT)

        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="photosynthesis",
            expected_answer="photosynthesis",
            scheduler=scheduler,
        )

        # A repetition state was created and the review queue rebuilt from it.
        assert "kp1" in progress.repetition_states
        assert len(progress.review_queue) == 1
        assert progress.review_queue[0].knowledge_point_id == "kp1"
        assert len(progress.learning_evidence) == 1
        assert progress.learning_evidence[0].result == "correct"


class TestExactVerdictNumeric:
    """Mastery's deterministic pre-check before any LLM verdict."""

    @staticmethod
    def _question(expected, question_type="short", accepted=()):
        from deeptutor.learning.models import PendingQuestion

        return PendingQuestion(
            question_id="q1",
            knowledge_point_id="kp1",
            prompt="Compute the expected cost.",
            question_type=question_type,
            expected_answer=expected,
            accepted_answers=list(accepted),
        )

    def _verdict(self, answer, expected, **kwargs):
        from deeptutor.learning.semantic_assessment import exact_verdict

        return exact_verdict(self._question(expected, **kwargs), answer)

    def test_numeric_match_is_correct_without_llm(self):
        assert self._verdict("1234,57 €", "1.234,57").result == "correct"
        assert self._verdict("0.125", "x", accepted=["1/8"]).result == "correct"
        assert self._verdict("3,48", "3.48", question_type="open").result == "correct"

    def test_numeric_mismatch_on_short_key_is_incorrect(self):
        verdict = self._verdict("1250.60", "1250.50")
        assert (verdict.result, verdict.confidence) == ("incorrect", 1)
        assert verdict.receipt()["final"] is True

    def test_uncertain_cases_still_reach_the_llm(self):
        # Open answers may explain a number; an ambiguous separator has two readings.
        assert self._verdict("200", "-200", question_type="open") is None
        assert self._verdict("125000", "125.000") is None
        assert self._verdict("about 1250", "1250.50") is None
        assert self._verdict("1300", "1250.50", accepted=["ca. 1300"]).result == "correct"
