import time

from deeptutor.learning.models import (
    DiagnosticResult,
    ErrorRecord,
    ErrorType,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    LearningStage,
    QuizAttempt,
    RepetitionState,
    RetryAttempt,
    ReviewTask,
)

# ── Enums ────────────────────────────────────────────────────────────────


class TestKnowledgeType:
    def test_values(self):
        assert KnowledgeType.MEMORY.value == "memory"
        assert KnowledgeType.CONCEPT.value == "concept"
        assert KnowledgeType.PROCEDURE.value == "procedure"
        assert KnowledgeType.DESIGN.value == "design"

    def test_str_subclass(self):
        assert isinstance(KnowledgeType.MEMORY, str)

    def test_legacy_values(self):
        assert KnowledgeType("记忆型") is KnowledgeType.MEMORY
        assert KnowledgeType("概念型") is KnowledgeType.CONCEPT
        assert KnowledgeType("程序型") is KnowledgeType.PROCEDURE
        assert KnowledgeType("设计型") is KnowledgeType.DESIGN


class TestErrorType:
    def test_values(self):
        assert ErrorType.KNOWLEDGE_STRUCTURAL.value == "structural"
        assert ErrorType.UNDERSTANDING_DEVIATION.value == "deviation"
        assert ErrorType.APPLICATION_ERROR.value == "application"
        assert ErrorType.METACOGNITIVE.value == "metacognitive"

    def test_legacy_values(self):
        assert ErrorType("知识结构性") is ErrorType.KNOWLEDGE_STRUCTURAL
        assert ErrorType("理解偏差型") is ErrorType.UNDERSTANDING_DEVIATION
        assert ErrorType("应用错误") is ErrorType.APPLICATION_ERROR
        assert ErrorType("元认知型") is ErrorType.METACOGNITIVE


class TestLearningStage:
    def test_values(self):
        assert LearningStage.DIAGNOSTIC.value == "diagnostic"
        assert LearningStage.EXPLAIN.value == "explain"
        assert LearningStage.FEYNMAN_CHECK.value == "feynman_check"
        assert LearningStage.PRACTICE.value == "practice"
        assert LearningStage.ERROR_DIAGNOSIS.value == "error_diagnosis"
        assert LearningStage.REVIEW.value == "review"
        assert LearningStage.COMPLETED.value == "completed"

    def test_str_subclass(self):
        assert isinstance(LearningStage.DIAGNOSTIC, str)

    def test_exact_membership(self):
        # The simplified Mastery Path graph has exactly these seven stages;
        # the removed members (phases, pretest, plan, module_test, ...) must
        # no longer exist as enum members.
        assert {s.value for s in LearningStage} == {
            "diagnostic",
            "explain",
            "feynman_check",
            "practice",
            "error_diagnosis",
            "review",
            "completed",
        }
        for removed in (
            "DIAGNOSTIC_PHASE1",
            "DIAGNOSTIC_PHASE2",
            "METACOGNITIVE_INTRO",
            "PLAN",
            "PRETEST",
            "PRACTICE_QUIZ",
            "MODULE_TEST",
        ):
            assert not hasattr(LearningStage, removed)

    def test_legacy_string_values_load(self):
        # Progress persisted by the older engine still deserializes by mapping
        # retired stage strings onto the nearest surviving stage.
        assert LearningStage("diagnostic_phase1") is LearningStage.DIAGNOSTIC
        assert LearningStage("diagnostic_phase2") is LearningStage.DIAGNOSTIC
        assert LearningStage("metacognitive_intro") is LearningStage.EXPLAIN
        assert LearningStage("plan") is LearningStage.EXPLAIN
        assert LearningStage("pretest") is LearningStage.EXPLAIN
        assert LearningStage("practice_quiz") is LearningStage.PRACTICE
        assert LearningStage("module_test") is LearningStage.REVIEW


# ── Models ───────────────────────────────────────────────────────────────


class TestKnowledgePoint:
    def test_instantiation(self):
        kp = KnowledgePoint(id="kp1", name="Ohm's Law", type=KnowledgeType.CONCEPT, module_id="m1")
        assert kp.id == "kp1"
        assert kp.type == KnowledgeType.CONCEPT

    def test_extra_ignored(self):
        kp = KnowledgePoint(
            id="kp1", name="x", type=KnowledgeType.MEMORY, module_id="m1", unknown=99
        )
        assert not hasattr(kp, "unknown") or kp.model_extra == {}


class TestLearningModule:
    def test_defaults(self):
        mod = LearningModule(id="m1", name="Circuits", order=1)
        assert mod.pass_threshold == 0.7
        assert mod.knowledge_points == []

    def test_with_knowledge_points(self):
        kp = KnowledgePoint(id="kp1", name="R", type=KnowledgeType.MEMORY, module_id="m1")
        mod = LearningModule(id="m1", name="C", order=1, knowledge_points=[kp])
        assert len(mod.knowledge_points) == 1
        assert mod.knowledge_points[0].name == "R"


class TestDiagnosticResult:
    def test_defaults(self):
        dr = DiagnosticResult()
        assert dr.module_mastery == {}
        assert dr.total_questions == 0
        assert dr.correct_count == 0

    def test_no_legacy_phase2_field(self):
        # phase2_results was removed with the multi-phase diagnostic; extra keys
        # are ignored rather than retained.
        dr = DiagnosticResult(total_questions=5, correct_count=3, phase2_results={"x": 1})
        assert dr.total_questions == 5
        assert dr.correct_count == 3
        assert not hasattr(dr, "phase2_results")


class TestQuizAttempt:
    def test_defaults(self):
        qa = QuizAttempt(question_id="q1", knowledge_point_id="kp1", is_correct=True)
        assert qa.module_id == ""
        assert qa.error_type is None
        assert qa.mastery_estimate == 0.0
        assert qa.self_attribution == ""
        assert isinstance(qa.timestamp, float)

    def test_with_error_type(self):
        qa = QuizAttempt(
            question_id="q1",
            knowledge_point_id="kp1",
            is_correct=False,
            error_type=ErrorType.APPLICATION_ERROR,
        )
        assert qa.error_type == ErrorType.APPLICATION_ERROR


class TestRetryAttempt:
    def test_instantiation(self):
        ra = RetryAttempt(timestamp=time.time(), is_correct=True, attempt_number=2)
        assert ra.attempt_number == 2


class TestErrorRecord:
    def test_defaults(self):
        er = ErrorRecord(
            id="e1",
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            error_type=ErrorType.METACOGNITIVE,
        )
        assert er.status == "active"
        assert er.ai_confirmation == ""
        assert er.retry_history == []
        assert isinstance(er.created_at, float)


class TestRepetitionState:
    def test_defaults(self):
        rs = RepetitionState(next_review_at=time.time())
        assert rs.interval_index == 0
        assert rs.consecutive_correct == 0
        assert rs.consecutive_wrong == 0


class TestReviewTask:
    def test_instantiation(self):
        rs = RepetitionState(next_review_at=time.time())
        rt = ReviewTask(
            id="r1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=time.time(),
            priority=1,
            state=rs,
        )
        assert rt.priority == 1


class TestLearningProgress:
    def test_defaults(self):
        lp = LearningProgress(book_id="b1")
        assert lp.current_stage == LearningStage.DIAGNOSTIC
        assert lp.current_kp_index == 0
        assert lp.current_module_id == ""
        assert lp.diagnostic is None
        assert lp.modules == []
        assert lp.mastery_levels == {}
        assert lp.error_records == []
        assert lp.review_queue == []
        assert lp.feynman_retries == {}
        assert lp.feynman_explanations == {}
        assert lp.stage_failure_counts == {}
        assert lp.stage_failure_notes == {}
        assert lp.version == 0
        assert isinstance(lp.created_at, float)

    def test_no_removed_fields(self):
        # module_stage and learning_mode were removed; supplying them is ignored.
        lp = LearningProgress(book_id="b1", learning_mode="mastery", module_stage="pretest")
        assert not hasattr(lp, "learning_mode")
        assert not hasattr(lp, "module_stage")
        assert lp.book_id == "b1"

    def test_extra_ignored(self):
        lp = LearningProgress(book_id="b1", custom_field="hello")
        assert not hasattr(lp, "custom_field")
        assert lp.book_id == "b1"


# ── Serialization roundtrip ─────────────────────────────────────────────


class TestSerializationRoundtrip:
    def test_learning_progress_roundtrip(self):
        lp = LearningProgress(book_id="b1")
        lp.mastery_levels["kp1"] = 0.8
        lp.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        lp.feynman_retries["kp1"] = 2
        lp.stage_failure_counts["explain"] = 1
        data = lp.model_dump(mode="json")
        lp2 = LearningProgress.model_validate(data)
        assert lp2.book_id == "b1"
        assert lp2.mastery_levels["kp1"] == 0.8
        assert lp2.knowledge_types["kp1"] == KnowledgeType.CONCEPT
        assert lp2.feynman_retries["kp1"] == 2
        assert lp2.stage_failure_counts["explain"] == 1
        assert lp2.current_stage == LearningStage.DIAGNOSTIC

    def test_legacy_progress_roundtrip(self):
        # A payload persisted by the old engine (retired stage + dropped fields)
        # must still deserialize, mapping the stage and ignoring removed keys.
        data = {
            "book_id": "b1",
            "current_stage": "pretest",
            "learning_mode": "mastery",
            "module_stage": "phase1",
        }
        lp = LearningProgress.model_validate(data)
        assert lp.book_id == "b1"
        assert lp.current_stage == LearningStage.EXPLAIN
        assert not hasattr(lp, "learning_mode")

    def test_error_record_roundtrip(self):
        er = ErrorRecord(
            id="e1",
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            error_type=ErrorType.APPLICATION_ERROR,
        )
        data = er.model_dump(mode="json")
        er2 = ErrorRecord.model_validate(data)
        assert er2.error_type == ErrorType.APPLICATION_ERROR
        assert er2.status == "active"
