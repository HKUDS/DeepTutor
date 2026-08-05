"""Tests for the grading module and the unified post-answer pipeline.

``grade_answer`` is the pure correctness check. ``classify_error`` is the
coarse wrong-answer tagger. ``LearningService.grade_and_record`` folds both of
those through the full record -> mastery -> spaced-repetition pipeline and is
fail-closed: with no stored expected answer the attempt is recorded wrong.

The second half (LRN-02) tests the deterministic Feynman evidence-chain
validator and the server-side rubric hard gate: the caller/model can never set
``passed``; the server computes it from the persisted evidence.
"""

from deeptutor.learning.grading import (
    classify_error,
    compute_server_gate,
    grade_answer,
    record_server_gate,
    rotate_chain_for_full_explanation,
    validate_evidence_chain,
)
from deeptutor.learning.models import (
    ConflictStatus,
    ErrorType,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    RubricScores,
    ServerGateResult,
    SourceCitation,
    SourceConflict,
    SourceSnapshot,
)
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.feynman_builders import (
    START,
    add_evidence,
    append_complete_chain,
    chain_evidence_ids,
    kp_progress,
    passing_assessment,
)


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


# ── Feynman evidence-chain validator (spec §6.1, §7.2) ─────────────────────


class TestEvidenceChainValidation:
    def test_complete_chain_is_valid(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is True
        assert len(result.probe_pairs) == 2
        assert len(result.transfer_pairs) == 1
        assert result.missing_evidence_kinds == ()

    def test_missing_explanation_fails(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        # Drop the explanation (the first item).
        progress.evidence_items = [
            e for e in progress.evidence_items if e.kind != EvidenceKind.EXPLANATION
        ]
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert "explanation" in result.missing_evidence_kinds

    def test_only_one_probe_pair_fails(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        # Remove the second probe question and its answer.
        q2 = [e for e in items if e.kind == EvidenceKind.PROBE_QUESTION][1]
        progress.evidence_items = [
            e for e in progress.evidence_items if e.id != q2.id and e.question_evidence_id != q2.id
        ]
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert "probe_answer" in result.missing_evidence_kinds

    def test_duplicate_answers_to_same_question_do_not_double_count(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        # Only one probe question actually gets an answer pair: rebind every
        # probe answer to the first probe question (duplicate binding).
        q1 = [e for e in items if e.kind == EvidenceKind.PROBE_QUESTION][0]
        for e in progress.evidence_items:
            if e.kind == EvidenceKind.PROBE_ANSWER:
                e.question_evidence_id = q1.id
        result = validate_evidence_chain(progress, attempt)
        assert len(result.probe_pairs) == 1
        assert result.valid is False
        assert "probe_answer" in result.missing_evidence_kinds

    def test_misbound_answer_does_not_count(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        # Break one probe binding: point an answer at a non-question id.
        answers = [e for e in progress.evidence_items if e.kind == EvidenceKind.PROBE_ANSWER]
        answers[0].question_evidence_id = "not-a-question"
        result = validate_evidence_chain(progress, attempt)
        assert len(result.probe_pairs) == 1
        assert result.valid is False
        assert "probe_answer" in result.missing_evidence_kinds

    def test_missing_transfer_fails(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt, transfer=False)
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert "transfer_question" in result.missing_evidence_kinds
        assert "transfer_answer" in result.missing_evidence_kinds

    def test_duplicate_evidence_ids_in_chain_do_not_double_count(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        # Duplicate one probe question id in the append-only list.
        duplicate = next(
            e for e in progress.evidence_items if e.kind == EvidenceKind.PROBE_QUESTION
        )
        progress.evidence_items.append(
            EvidenceItem(
                id=duplicate.id,
                attempt_id=attempt.id,
                chain_id=attempt.active_chain_id,
                kind=EvidenceKind.PROBE_QUESTION,
                event_seq=duplicate.event_seq,
                created_at=duplicate.created_at,
            )
        )
        result = validate_evidence_chain(progress, attempt)
        # The deduplicated chain still has exactly two probe questions.
        assert result.valid is True

    def test_evidence_from_other_attempt_is_ignored(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        other = FeynmanAttempt(id="a2", knowledge_point_id="kp1", active_chain_id="chain-other")
        # A transfer answer from another attempt cannot satisfy this chain.
        add_evidence(
            progress,
            other,
            EvidenceKind.TRANSFER_ANSWER,
            question_evidence_id="whatever",
            chain_id="chain-other",
        )
        assert validate_evidence_chain(progress, attempt).valid is True

    def test_no_active_chain_is_invalid(self):
        progress, attempt = kp_progress()
        attempt.active_chain_id = ""
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert result.reasons == ("attempt has no active chain",)

    def test_empty_active_chain_is_invalid(self):
        progress, attempt = kp_progress()
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert result.reasons == ("active chain has no evidence",)


class TestVoiceTranscriptConfirmation:
    def test_unconfirmed_voice_answer_does_not_count(self):
        progress, attempt = kp_progress()
        append_complete_chain(
            progress,
            attempt,
            answer_voice=True,
            answer_confirmed=False,
        )
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert "probe_answer" in result.missing_evidence_kinds

    def test_confirmed_voice_answers_count(self):
        progress, attempt = kp_progress()
        append_complete_chain(
            progress,
            attempt,
            answer_voice=True,
            answer_confirmed=True,
        )
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is True

    def test_unconfirmed_voice_explanation_does_not_count(self):
        progress, attempt = kp_progress()
        append_complete_chain(
            progress,
            attempt,
            explanation_voice=True,
            explanation_confirmed=False,
        )
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert "explanation" in result.missing_evidence_kinds

    def test_confirmed_voice_explanation_counts(self):
        progress, attempt = kp_progress()
        append_complete_chain(
            progress,
            attempt,
            explanation_voice=True,
            explanation_confirmed=True,
        )
        assert validate_evidence_chain(progress, attempt).valid is True


class TestFullExplanationChainReset:
    def test_old_chain_evidence_does_not_count_after_reset(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)  # old chain is complete…
        assert validate_evidence_chain(progress, attempt).valid is True
        # …but a full explanation closes it for finalize.
        new_chain = rotate_chain_for_full_explanation(progress, attempt, now=START + 100)
        assert new_chain != "chain-1"
        # Old evidence stays readable but no longer contributes.
        assert len(chain_evidence_ids(progress, attempt)) == 0
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert result.used_full_explanation is True

    def test_new_complete_reteach_chain_passes_after_reset(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        rotate_chain_for_full_explanation(progress, attempt, now=START + 100)
        append_complete_chain(progress, attempt)  # fresh, complete reteach chain
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is True
        assert result.used_full_explanation is True

    def test_mixing_old_and_new_evidence_cannot_satisfy_chain(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        rotate_chain_for_full_explanation(progress, attempt, now=START + 100)
        # Only a partial new chain — the old chain is gone for finalize.
        add_evidence(progress, attempt, EvidenceKind.EXPLANATION, created_at=START + 101)
        result = validate_evidence_chain(progress, attempt)
        assert result.valid is False
        assert "probe_question" in result.missing_evidence_kinds

    def test_chain_rotation_collision_free_with_holes(self):
        """Rotation must not reuse an existing chain id when the suffix
        history has holes or is non-contiguous (1 and 3 exist, 2 is missing)."""
        progress, attempt = kp_progress(chain_id="a1:chain:1")
        add_evidence(
            progress,
            attempt,
            EvidenceKind.EXPLANATION,
            chain_id="a1:chain:1",
            event_seq=1,
        )
        attempt.active_chain_id = "a1:chain:3"
        add_evidence(
            progress,
            attempt,
            EvidenceKind.EXPLANATION,
            chain_id="a1:chain:3",
            event_seq=1,
        )
        new_chain = rotate_chain_for_full_explanation(progress, attempt, now=START + 100)
        # len(existing)+1 would have been 3 — a collision with the live chain.
        assert new_chain == "a1:chain:4"
        assert new_chain not in {e.chain_id for e in progress.evidence_items}
        assert attempt.active_chain_id == new_chain


# ── server-side rubric hard gate (spec §6.4) ───────────────────────────────


def _gate(progress, attempt, assessment, *, now=None):
    return compute_server_gate(progress, attempt, assessment, now=now)


class TestServerGate:
    def test_complete_assessment_passes(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        result = _gate(progress, attempt, assessment)
        assert result.passed is True
        assert result.missing_evidence_kinds == []
        assert result.blocked_by_conflict == []
        assert result.reasons == []

    def test_caller_cannot_set_passed(self):
        """A model-supplied ``passed`` is ignored; the server recomputes it."""
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in progress.evidence_items])
        assessment.server_gate_result = ServerGateResult(passed=True)
        result = _gate(progress, attempt, assessment)
        assert result.passed is True
        # Now strip required evidence and the forged flag must not survive.
        progress.evidence_items = [
            e for e in progress.evidence_items if e.kind != EvidenceKind.EXPLANATION
        ]
        forged = passing_assessment(evidence_ids=["ev1"])
        forged.server_gate_result = ServerGateResult(passed=True)
        blocked = _gate(progress, attempt, forged)
        assert blocked.passed is False
        assert "explanation" in blocked.missing_evidence_kinds

    def test_record_server_gate_overwrites_caller_value(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in progress.evidence_items])
        assessment.server_gate_result = ServerGateResult(passed=True)
        record_server_gate(progress, attempt, assessment)
        assert assessment.server_gate_result.passed is True
        progress.evidence_items = []
        failing = passing_assessment(evidence_ids=[])
        failing.server_gate_result = ServerGateResult(passed=True)
        record_server_gate(progress, attempt, failing)
        assert failing.server_gate_result.passed is False

    def test_invalid_rubric_domain_fails(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        for bad in (0.5, 1.5, 3.0, -1, 2.5):
            assessment = passing_assessment(
                evidence_ids=[e.id for e in items],
                rubric=RubricScores(correctness=bad, completeness=1, causal_clarity=1, transfer=2),
            )
            result = _gate(progress, attempt, assessment)
            assert result.passed is False
            assert any("0|1|2 domain" in reason for reason in result.reasons)

    def test_rubric_thresholds_are_hard(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        cases = [
            (
                RubricScores(correctness=1, completeness=1, causal_clarity=1, transfer=2),
                "correctness",
            ),
            (RubricScores(correctness=2, completeness=1, causal_clarity=1, transfer=1), "transfer"),
            (
                RubricScores(correctness=2, completeness=0, causal_clarity=1, transfer=2),
                "completeness",
            ),
            (
                RubricScores(correctness=2, completeness=1, causal_clarity=0, transfer=2),
                "causal_clarity",
            ),
        ]
        for rubric, needle in cases:
            assessment = passing_assessment(evidence_ids=[e.id for e in items], rubric=rubric)
            result = _gate(progress, attempt, assessment)
            assert result.passed is False
            assert any(needle in reason for reason in result.reasons)

    def test_critical_errors_block(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(
            evidence_ids=[e.id for e in items],
            critical_errors=["said a resistor stores charge"],
        )
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("critical errors" in reason for reason in result.reasons)

    def test_assessment_evidence_must_resolve_to_active_chain(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in items] + ["ghost-evidence"])
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("ghost-evidence" in reason for reason in result.reasons)

    def test_assessment_with_no_evidence_fails(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[])
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert "assessment_evidence" in result.missing_evidence_kinds

    def test_assessment_evidence_from_old_chain_does_not_resolve(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        rotate_chain_for_full_explanation(progress, attempt, now=START + 100)
        # Assessment cites the old chain's evidence — must not resolve.
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("not in the active chain" in reason for reason in result.reasons)


class TestGateCitations:
    def test_citation_to_unknown_snapshot_fails(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        assessment.source_citations = [SourceCitation(source_snapshot_id="s9", anchor="p.1")]
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("s9" in reason for reason in result.reasons)

    def test_citation_to_non_allowed_snapshot_fails(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        # The attempt is pinned to s1/s2; s3 is a registered snapshot but not allowed.
        progress.source_snapshots.append(SourceSnapshot(id="s3", citation_anchors=["p.9"]))
        assessment = passing_assessment(
            evidence_ids=[e.id for e in items],
        )
        assessment.source_citations = [SourceCitation(source_snapshot_id="s3", anchor="p.9")]
        result = _gate(progress, attempt, assessment)
        assert result.passed is False

    def test_citation_anchor_must_exist_on_snapshot(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        assessment.source_citations = [SourceCitation(source_snapshot_id="s1", anchor="not-listed")]
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("anchor" in reason for reason in result.reasons)

    def test_valid_anchor_resolves(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        assessment.source_citations = [SourceCitation(source_snapshot_id="s1", anchor="p.4")]
        assert _gate(progress, attempt, assessment).passed is True

    def test_evidence_citations_are_checked(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        # Break the explanation's citation anchor.
        explanation = next(e for e in items if e.kind == EvidenceKind.EXPLANATION)
        explanation.source_citations = [SourceCitation(source_snapshot_id="s1", anchor="wrong")]
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        result = _gate(progress, attempt, assessment)
        assert result.passed is False

    def test_empty_anchor_list_rejects_non_empty_assessment_anchor(self):
        """A supplied anchor must match a materialized anchor exactly; a
        snapshot with an empty ``citation_anchors`` list cannot satisfy it."""
        progress, attempt = kp_progress(with_sources=True)
        progress.source_snapshots[0].citation_anchors = []  # s1 has no anchors
        items = append_complete_chain(progress, attempt)
        for e in progress.evidence_items:
            e.source_citations = []  # isolate the assessment citation
        assessment = passing_assessment(evidence_ids=[e.id for e in items], source_citation=False)
        assessment.source_citations = [SourceCitation(source_snapshot_id="s1", anchor="p.3")]
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("anchor" in reason for reason in result.reasons)

    def test_empty_anchor_allowed_when_snapshot_has_no_anchors(self):
        """Snapshot-level citation (empty anchor) stays allowed even when the
        snapshot materializes no anchors; only a supplied anchor must match."""
        progress, attempt = kp_progress(with_sources=True)
        progress.source_snapshots[0].citation_anchors = []
        items = append_complete_chain(progress, attempt)
        for e in progress.evidence_items:
            e.source_citations = []
        assessment = passing_assessment(evidence_ids=[e.id for e in items], source_citation=False)
        assessment.source_citations = [SourceCitation(source_snapshot_id="s1", anchor="")]
        assert _gate(progress, attempt, assessment).passed is True


class TestGateConflicts:
    def test_open_conflict_blocks(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        progress.source_conflicts.append(
            SourceConflict(
                id="c1",
                knowledge_point_ids=["kp1"],
                claim="sources disagree",
                status=ConflictStatus.OPEN,
            )
        )
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        result = _gate(progress, attempt, assessment)
        assert result.passed is False
        assert result.blocked_by_conflict == ["c1"]

    def test_resolved_conflict_does_not_block(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        progress.source_conflicts.append(
            SourceConflict(
                id="c1",
                knowledge_point_ids=["kp1"],
                claim="resolved",
                status=ConflictStatus.RESOLVED,
                accepted_snapshot_id="s1",
            )
        )
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        assert _gate(progress, attempt, assessment).passed is True

    def test_conflict_for_other_kp_does_not_block(self):
        progress, attempt = kp_progress()
        items = append_complete_chain(progress, attempt)
        progress.source_conflicts.append(
            SourceConflict(id="c1", knowledge_point_ids=["kp-other"], status=ConflictStatus.OPEN)
        )
        assessment = passing_assessment(evidence_ids=[e.id for e in items])
        assert _gate(progress, attempt, assessment).passed is True
