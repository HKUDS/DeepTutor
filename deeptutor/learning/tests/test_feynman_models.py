"""Unit tests for the Feynman learning v2 aggregate models (LRN-01)."""

from deeptutor.learning.models import (
    AggregateVersions,
    AttemptCycleType,
    AttemptStatus,
    ChallengeMode,
    ChallengeRecord,
    ChallengeStatus,
    ConflictStatus,
    ErrorType,
    EvaluatorSnapshot,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    GapRecord,
    GapStatus,
    HelpLevel,
    HistoryEvent,
    InputMode,
    KnowledgeMapVersion,
    KnowledgeStateProjection,
    LearningProgress,
    MasteryState,
    ReviewState,
    RubricAssessment,
    RubricScores,
    ServerGateResult,
    SourceCitation,
    SourceConflict,
    SourceSnapshot,
    SourceType,
)


class TestEnums:
    def test_attempt_cycle_types(self):
        assert AttemptCycleType.INITIAL.value == "initial"
        assert AttemptCycleType.DELAYED_RETEACH.value == "delayed_reteach"
        assert AttemptCycleType.REEVALUATION.value == "reevaluation"
        assert AttemptCycleType.TEST_OUT.value == "test_out"
        assert AttemptCycleType.LEGACY_IMPORT.value == "legacy_import"

    def test_attempt_statuses(self):
        assert AttemptStatus.DRAFT.value == "draft"
        assert AttemptStatus.COLLECTING.value == "collecting"
        assert AttemptStatus.READY_TO_ASSESS.value == "ready_to_assess"
        assert AttemptStatus.ASSESSED.value == "assessed"
        assert AttemptStatus.CLOSED.value == "closed"
        assert AttemptStatus.INVALIDATED.value == "invalidated"

    def test_evidence_kinds(self):
        assert EvidenceKind.EXPLANATION.value == "explanation"
        assert EvidenceKind.PROBE_QUESTION.value == "probe_question"
        assert EvidenceKind.PROBE_ANSWER.value == "probe_answer"
        assert EvidenceKind.TRANSFER_QUESTION.value == "transfer_question"
        assert EvidenceKind.TRANSFER_ANSWER.value == "transfer_answer"
        assert EvidenceKind.RETEACH.value == "reteach"
        assert EvidenceKind.SOURCE_REFERENCE.value == "source_reference"

    def test_mastery_states(self):
        assert MasteryState.NEW.value == "new"
        assert MasteryState.IN_PROGRESS.value == "in_progress"
        assert MasteryState.NEEDS_REVISION.value == "needs_revision"
        assert MasteryState.PROVISIONAL_MASTERY.value == "provisional_mastery"
        assert MasteryState.STABLE_MASTERY.value == "stable_mastery"

    def test_review_states(self):
        assert ReviewState.UNSCHEDULED.value == "unscheduled"
        assert ReviewState.SCHEDULED.value == "scheduled"
        assert ReviewState.DUE.value == "due"
        assert ReviewState.IN_PROGRESS.value == "in_progress"

    def test_help_levels(self):
        assert HelpLevel.QUESTION.value == "question"
        assert HelpLevel.HINT.value == "hint"
        assert HelpLevel.SOURCE_LOCATOR.value == "source_locator"
        assert HelpLevel.FULL_EXPLANATION.value == "full_explanation"

    def test_conflict_and_challenge_and_gap(self):
        assert ConflictStatus.OPEN.value == "open"
        assert ConflictStatus.RESOLVED.value == "resolved"
        assert ChallengeMode.REASSESS_EXISTING.value == "reassess_existing"
        assert ChallengeMode.COLLECT_NEW_EVIDENCE.value == "collect_new_evidence"
        assert ChallengeStatus.PENDING.value == "pending"
        assert ChallengeStatus.COMPLETED.value == "completed"
        assert ChallengeStatus.FAILED.value == "failed"
        assert ChallengeStatus.CANCELLED.value == "cancelled"
        assert GapStatus.ACTIVE.value == "active"
        assert GapStatus.IMPROVING.value == "improving"
        assert GapStatus.RESOLVED.value == "resolved"
        assert GapStatus.REOPENED.value == "reopened"


class TestFeynmanAttempt:
    def test_defaults(self):
        a = FeynmanAttempt(id="a1", knowledge_point_id="kp1")
        assert a.cycle_type == AttemptCycleType.INITIAL
        assert a.status == AttemptStatus.DRAFT
        assert a.invalidated_reason == ""
        assert a.knowledge_point_version == 0
        assert a.map_version_id == ""
        assert a.source_snapshot_ids == []
        assert a.max_help_level == HelpLevel.QUESTION
        assert a.evaluator_snapshot is None
        assert a.closed_at is None
        assert isinstance(a.created_at, float)

    def test_extra_ignored(self):
        a = FeynmanAttempt(id="a1", knowledge_point_id="kp1", unknown="x")
        assert a.model_extra is None or a.model_extra == {}


class TestEvidenceItem:
    def test_defaults(self):
        e = EvidenceItem(id="ev1", kind=EvidenceKind.EXPLANATION)
        assert e.attempt_id == ""
        assert e.input_mode == InputMode.TEXT
        assert e.transcript_confirmed is False
        assert e.content_snapshot == ""
        assert e.content_hash == ""
        assert e.source_citations == []
        assert e.help_level is None

    def test_voice_transcript(self):
        e = EvidenceItem(
            id="ev2",
            kind=EvidenceKind.TRANSFER_ANSWER,
            input_mode=InputMode.VOICE_TRANSCRIPT,
            transcript_confirmed=True,
            source_citations=[SourceCitation(source_snapshot_id="s1", anchor="p.3")],
        )
        assert e.input_mode == InputMode.VOICE_TRANSCRIPT
        assert e.transcript_confirmed is True
        assert e.source_citations[0].anchor == "p.3"


class TestRubricAssessment:
    def test_defaults(self):
        ra = RubricAssessment(id="ra1", attempt_id="a1")
        assert ra.revision == 1
        assert ra.assessment_sequence == 1
        assert ra.rubric.correctness == 0.0
        assert ra.server_gate_result.passed is False
        assert ra.model_invocation_id == ""

    def test_with_gate_result(self):
        ra = RubricAssessment(
            id="ra1",
            attempt_id="a1",
            rubric=RubricScores(correctness=0.9, completeness=0.8),
            server_gate_result=ServerGateResult(
                passed=True,
                required_evidence_kinds=["explanation"],
                missing_evidence_kinds=[],
            ),
        )
        assert ra.rubric.correctness == 0.9
        assert ra.server_gate_result.passed is True


class TestEvaluatorSnapshot:
    def test_roundtrip_with_none_fields(self):
        snap = EvaluatorSnapshot(profile_id="p1")
        assert snap.requested_api_protocol == ""
        assert snap.resolved_model == ""
        assert isinstance(snap.created_at, float)


class TestChallengeRecord:
    def test_defaults(self):
        ch = ChallengeRecord(id="ch1", knowledge_point_id="kp1")
        assert ch.mode == ChallengeMode.REASSESS_EXISTING
        assert ch.status == ChallengeStatus.PENDING
        assert ch.completed_at is None
        assert ch.result_attempt_id == ""


class TestGapRecord:
    def test_defaults(self):
        g = GapRecord(id="g1", knowledge_point_id="kp1")
        assert g.status == GapStatus.ACTIVE
        assert g.priority == 0
        assert g.resolved_at is None


class TestKnowledgeStateProjection:
    def test_defaults(self):
        p = KnowledgeStateProjection(knowledge_point_id="kp1")
        assert p.mastery_state == MasteryState.NEW
        assert p.review_state == ReviewState.UNSCHEDULED
        assert p.provisional_since is None
        assert p.stable_since is None


class TestSourceSnapshot:
    def test_defaults(self):
        s = SourceSnapshot(id="s1")
        assert s.source_type == SourceType.USER_MATERIAL
        assert s.content_hash == ""


class TestKnowledgeMapVersion:
    def test_defaults(self):
        v = KnowledgeMapVersion(id="mv1", path_id="path1")
        assert v.version == 1
        assert v.nodes == []
        assert v.priorities == {}
        assert v.source_snapshot_ids == []


class TestSourceConflict:
    def test_defaults(self):
        c = SourceConflict(id="c1", claim="contradiction")
        assert c.status == ConflictStatus.OPEN
        assert c.version == 1
        assert c.resolved_at is None
        assert c.accepted_snapshot_id == ""


class TestHistoryEvent:
    def test_roundtrip(self):
        h = HistoryEvent(
            seq=1,
            event_type="attempt_invalidated",
            aggregate="attempt",
            aggregate_version=2,
            summary="invalidated a1",
            payload={"attempt_ids": ["a1"], "reason": "source_version_changed"},
        )
        assert h.seq == 1
        assert h.payload["attempt_ids"] == ["a1"]
        data = h.model_dump(mode="json")
        h2 = HistoryEvent.model_validate(data)
        assert h2.model_dump(mode="json") == data


class TestAggregateVersions:
    def test_defaults(self):
        v = AggregateVersions()
        assert v.attempt == 0
        assert v.map == 0
        assert v.conflict == 0
        assert v.gap == 0


class TestLearningProgressNewFields:
    def test_defaults(self):
        lp = LearningProgress(book_id="b1")
        assert lp.attempts == []
        assert lp.evidence_items == []
        assert lp.rubric_assessments == []
        assert lp.challenge_records == []
        assert lp.gaps == []
        assert lp.projections == {}
        assert lp.source_snapshots == []
        assert lp.map_versions == []
        assert lp.source_conflicts == []
        assert lp.history == []
        assert lp.aggregate_versions.attempt == 0

    def test_legacy_fields_still_present(self):
        lp = LearningProgress(book_id="b1")
        lp.mastery_levels["kp1"] = 0.8
        lp.qualitative_mastery["kp2"] = True
        assert lp.mastery_levels["kp1"] == 0.8
        assert lp.qualitative_mastery["kp2"] is True

    def test_error_type_still_resolves_legacy(self):
        assert ErrorType("应用错误") is ErrorType.APPLICATION_ERROR


class TestFeynmanRoundtrip:
    def test_attempt_roundtrip(self):
        a = FeynmanAttempt(
            id="a1",
            knowledge_point_id="kp1",
            cycle_type=AttemptCycleType.DELAYED_RETEACH,
            status=AttemptStatus.ASSESSED,
            knowledge_point_version=2,
            map_version_id="mv1",
            source_snapshot_ids=["s1"],
        )
        data = a.model_dump(mode="json")
        a2 = FeynmanAttempt.model_validate(data)
        assert a2.cycle_type == AttemptCycleType.DELAYED_RETEACH
        assert a2.status == AttemptStatus.ASSESSED
        assert a2.map_version_id == "mv1"
        assert a2.model_dump(mode="json") == data

    def test_evidence_roundtrip(self):
        e = EvidenceItem(
            id="ev1",
            attempt_id="a1",
            kind=EvidenceKind.PROBE_ANSWER,
            session_id="s1",
            turn_id="t1",
            event_seq=2,
            input_mode=InputMode.VOICE_TRANSCRIPT,
            transcript_confirmed=True,
            source_citations=[SourceCitation(source_snapshot_id="s1")],
        )
        data = e.model_dump(mode="json")
        e2 = EvidenceItem.model_validate(data)
        assert e2.kind == EvidenceKind.PROBE_ANSWER
        assert e2.input_mode == InputMode.VOICE_TRANSCRIPT
        assert e2.model_dump(mode="json") == data

    def test_assessment_roundtrip(self):
        ra = RubricAssessment(
            id="ra1",
            attempt_id="a1",
            rubric=RubricScores(
                correctness=0.9, completeness=0.7, causal_clarity=0.8, transfer=0.6
            ),
            evidence_ids=["ev1", "ev2"],
            server_gate_result=ServerGateResult(passed=True, used_full_explanation=False),
            evaluator_snapshot=EvaluatorSnapshot(profile_id="p1", resolved_model="gpt-4o"),
        )
        data = ra.model_dump(mode="json")
        ra2 = RubricAssessment.model_validate(data)
        assert ra2.rubric.correctness == 0.9
        assert ra2.server_gate_result.passed is True
        assert ra2.evaluator_snapshot.resolved_model == "gpt-4o"
        assert ra2.model_dump(mode="json") == data
