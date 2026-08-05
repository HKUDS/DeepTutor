"""Property-style tests for the Feynman learning aggregates (LRN-01).

Plain pytest invariants rather than a hypothesis dependency: every generated
progress must round-trip losslessly, history seqs must stay strictly
monotonic across save/load, and an invalidated attempt must stay invalidated
with its evidence read-only after reload.
"""

from pathlib import Path
import time

import pytest

from deeptutor.learning.grading import (
    compute_server_gate,
    rotate_chain_for_full_explanation,
)
from deeptutor.learning.models import (
    AttemptCycleType,
    AttemptStatus,
    EvaluatorSnapshot,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    HistoryEvent,
    KnowledgeMapVersion,
    KnowledgeStateProjection,
    KnowledgeType,
    LearningProgress,
    MasteryState,
    ReviewState,
    RubricAssessment,
    RubricScores,
    ServerGateResult,
    SourceSnapshot,
)
from deeptutor.learning.policy import rebuild_projection
from deeptutor.learning.storage import (
    LearningStore,
    append_history,
    apply_map_version,
    is_evidence_read_only,
    migrate_legacy_projection,
    register_source_snapshot,
)
from deeptutor.learning.tests.feynman_builders import (
    START,
    add_attempt,
    append_complete_chain,
    chain_evidence_ids,
    kp_progress,
    passing_assessment,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _build_progress(book_id: str, n_attempts: int = 3) -> LearningProgress:
    """Build a non-trivial progress exercising every new aggregate."""
    lp = LearningProgress(book_id=book_id)
    now = time.time()
    lp.mastery_levels["kp1"] = 0.9
    lp.qualitative_mastery["kp2"] = True
    lp.source_snapshots.extend(
        [
            SourceSnapshot(id="s1", content_hash="h1"),
            SourceSnapshot(id="s2", content_hash="h2"),
        ]
    )
    for i in range(n_attempts):
        attempt_id = f"a{i + 1}"
        kp_id = f"kp{(i % 2) + 1}"
        lp.attempts.append(
            FeynmanAttempt(
                id=attempt_id,
                knowledge_point_id=kp_id,
                cycle_type=AttemptCycleType.INITIAL,
                status=AttemptStatus.COLLECTING,
                knowledge_point_version=1,
                map_version_id="mv1",
                source_snapshot_ids=["s1", "s2"],
                evaluator_snapshot=EvaluatorSnapshot(profile_id="p1", resolved_model="gpt-4o"),
            )
        )
        lp.evidence_items.append(
            EvidenceItem(
                id=f"ev{i + 1}",
                attempt_id=attempt_id,
                kind=EvidenceKind.EXPLANATION,
                content_snapshot=f"content {i}",
            )
        )
        lp.rubric_assessments.append(
            RubricAssessment(
                id=f"ra{i + 1}",
                attempt_id=attempt_id,
                assessment_sequence=i + 1,
                rubric=RubricScores(correctness=0.8, completeness=0.7),
                server_gate_result=ServerGateResult(passed=True),
            )
        )
    lp.projections["kp1"] = KnowledgeStateProjection(
        knowledge_point_id="kp1",
        mastery_state=MasteryState.PROVISIONAL_MASTERY,
        next_review_at=now + 3600,
    )
    lp.projections["kp2"] = KnowledgeStateProjection(knowledge_point_id="kp2")
    lp.history.append(
        HistoryEvent(
            seq=1,
            event_type="map_version_confirmed",
            aggregate="map",
            aggregate_version=1,
        )
    )
    return lp


class TestRoundTripProperties:
    def test_generated_progress_roundtrips_losslessly_in_memory(self):
        original = _build_progress("b1")
        dump1 = original.model_dump(mode="json")
        # A pure model round-trip is byte-identical (no store mutation).
        reloaded = LearningProgress.model_validate(dump1)
        assert reloaded.model_dump(mode="json") == dump1

    def test_generated_progress_roundtrips_through_store(self, tmp_path):
        store = LearningStore(root=tmp_path)
        original = _build_progress("b1")
        store.save(original)
        loaded = store.load("b1")
        dump_loaded = loaded.model_dump(mode="json")
        dump_original = original.model_dump(mode="json")
        # The store bumps the document version and touches updated_at; all
        # other fields — including every new aggregate — survive losslessly.
        dump_original.pop("version")
        dump_original.pop("updated_at")
        dump_loaded.pop("version")
        dump_loaded.pop("updated_at")
        assert dump_loaded == dump_original

    def test_legacy_migration_roundtrip_preserves_json_fields(self, tmp_path):
        store = LearningStore(root=tmp_path)
        original = _build_progress("b2")
        before = original.model_dump(mode="json")
        migrate_legacy_projection(original)
        after = original.model_dump(mode="json")
        # Migration only *adds* aggregates; pre-existing JSON must be preserved.
        for key in (
            "mastery_levels",
            "qualitative_mastery",
            "modules",
            "quiz_attempts",
            "error_records",
            "feynman_explanations",
        ):
            assert after[key] == before[key]


class TestHistoryMonotonicity:
    def test_history_seqs_strictly_increase_across_reload(self, tmp_path):
        store = LearningStore(root=tmp_path)
        lp = _build_progress("b3")
        store.save(lp)
        for i in range(5):
            loaded = store.load("b3")
            append_history(loaded, f"event-{i}", aggregate="attempt", summary=str(i))
            store.save(loaded)
        final = store.load("b3")
        seqs = [e.seq for e in final.history]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs))
        assert seqs[0] == 1
        # All prior events are intact and in order.
        assert [e.summary for e in final.history] == ["", "0", "1", "2", "3", "4"]


class TestInvalidationInvariants:
    def test_invalidated_attempt_stays_invalidated_after_reload(self, tmp_path):
        store = LearningStore(root=tmp_path)
        lp = _build_progress("b4")
        lp.attempts[0].map_version_id = "mv1"
        lp.attempts[1].map_version_id = "mv1"
        lp.attempts[2].map_version_id = "mv1"
        # A source change invalidates any attempt referencing the changed source.
        invalidated = register_source_snapshot(lp, SourceSnapshot(id="s1", content_hash="CHANGED"))
        assert set(invalidated) == {"a1", "a2", "a3"}
        store.save(lp)

        reloaded = store.load("b4")
        for attempt in reloaded.attempts:
            assert attempt.status == AttemptStatus.INVALIDATED
        # Evidence for invalidated attempts is read-only after reload.
        for i in range(3):
            assert is_evidence_read_only(reloaded, f"ev{i + 1}") is True

    def test_map_update_invalidated_attempts_never_revive_on_resave(self, tmp_path):
        store = LearningStore(root=tmp_path)
        lp = _build_progress("b5")
        for a in lp.attempts:
            a.map_version_id = "mv1"
        apply_map_version(
            lp,
            KnowledgeMapVersion(
                id="mv2", path_id="p1", version=2, source_snapshot_ids=["s1", "s2"]
            ),
        )
        store.save(lp)
        # Simulate a later unrelated save on the reloaded object.
        again = store.load("b5")
        append_history(again, "nothing_changed", summary="touch")
        store.save(again)
        final = store.load("b5")
        for attempt in final.attempts:
            assert attempt.status == AttemptStatus.INVALIDATED

    def test_history_aggregate_versions_are_monotonic(self, tmp_path):
        store = LearningStore(root=tmp_path)
        lp = _build_progress("b6")
        store.save(lp)
        for _ in range(3):
            loaded = store.load("b6")
            append_history(loaded, "attempt_touch", aggregate="attempt")
            store.save(loaded)
        final = store.load("b6")
        attempt_versions = [e.aggregate_version for e in final.history if e.aggregate == "attempt"]
        assert attempt_versions == sorted(attempt_versions)
        assert len(attempt_versions) == len(set(attempt_versions))


class TestLegacyFixtureProperties:
    def test_fixture_legacy_roundtrip_through_store(self, tmp_path):
        store = LearningStore(root=tmp_path)
        import json

        data = json.loads((FIXTURES / "legacy_progress_v1.json").read_text(encoding="utf-8"))
        (store._root / "legacy-book.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        loaded = store.load_with_migration("legacy-book")
        # Re-dump preserves the legacy payload plus appended aggregates.
        dumped = loaded.model_dump(mode="json")
        for key in (
            "mastery_levels",
            "qualitative_mastery",
            "quiz_attempts",
            "feynman_explanations",
        ):
            assert dumped[key] == data[key]
        # And the new aggregates were added, not overwritten.
        assert dumped["attempts"]
        assert dumped["history"]
        assert dumped["projections"]


# ── LRN-02 Feynman policy properties ───────────────────────────────────────


def _record(progress, attempt, *, assessment_id="ra1", passed=True, created_at=None):
    assessment = passing_assessment(
        attempt_id=attempt.id,
        assessment_id=assessment_id,
        evidence_ids=chain_evidence_ids(progress, attempt),
        created_at=created_at if created_at is not None else START + 50,
    )
    assessment.server_gate_result = ServerGateResult(passed=passed, reasons=["server gate (test)"])
    progress.rubric_assessments.append(assessment)
    return assessment


class TestMasteryStableProperties:
    """Without a delayed-reteach pass, no path may produce stable mastery."""

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    @pytest.mark.parametrize("cycle", ["initial", "test_out", "reevaluation", "legacy_import"])
    def test_non_delayed_reteach_pass_never_stable(self, kp_type, cycle):
        progress, attempt = kp_progress(kp_type, attempt_cycle=cycle)
        append_complete_chain(progress, attempt)
        _record(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        proj = rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert proj.stable_since is None
        assert proj.review_state == ReviewState.SCHEDULED

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_delayed_reteach_pass_alone_grants_stable(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        append_complete_chain(progress, attempt)
        _record(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        proj = rebuild_projection(progress, "kp1", now=START + 550)
        assert proj.mastery_state == MasteryState.STABLE_MASTERY

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_failed_review_after_stable_returns_needs_revision(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        append_complete_chain(progress, attempt)
        _record(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        review = add_attempt(
            progress, attempt_id="a3", cycle_type="delayed_reteach", chain_id="chain-3"
        )
        append_complete_chain(progress, review, start=START + 900)
        _record(progress, review, assessment_id="ra3", passed=False, created_at=START + 950)
        review.status = AttemptStatus.ASSESSED
        proj = rebuild_projection(progress, "kp1", now=START + 950)
        assert proj.mastery_state == MasteryState.NEEDS_REVISION
        assert proj.review_state == ReviewState.SCHEDULED


class TestGateBlockingProperties:
    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_missing_required_evidence_fails_all_types(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        append_complete_chain(progress, attempt, transfer=False)
        assessment = passing_assessment(evidence_ids=chain_evidence_ids(progress, attempt))
        result = compute_server_gate(progress, attempt, assessment)
        assert result.passed is False
        assert "transfer_question" in result.missing_evidence_kinds

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_duplicate_probe_binding_fails_all_types(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        items = append_complete_chain(progress, attempt)
        q1 = next(e for e in items if e.kind == EvidenceKind.PROBE_QUESTION)
        for e in progress.evidence_items:
            if e.kind == EvidenceKind.PROBE_ANSWER:
                e.question_evidence_id = q1.id
        assessment = passing_assessment(evidence_ids=chain_evidence_ids(progress, attempt))
        result = compute_server_gate(progress, attempt, assessment)
        assert result.passed is False
        assert "probe_answer" in result.missing_evidence_kinds

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_misbound_transfer_fails_all_types(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        items = append_complete_chain(progress, attempt)
        transfer_answer = next(e for e in items if e.kind == EvidenceKind.TRANSFER_ANSWER)
        transfer_answer.question_evidence_id = "no-such-question"
        assessment = passing_assessment(evidence_ids=chain_evidence_ids(progress, attempt))
        result = compute_server_gate(progress, attempt, assessment)
        assert result.passed is False
        assert "transfer_answer" in result.missing_evidence_kinds

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_invalid_rubric_fails_all_types(self, kp_type):
        progress, attempt = kp_progress(kp_type)
        items = append_complete_chain(progress, attempt)
        assessment = passing_assessment(
            evidence_ids=[e.id for e in items],
            rubric=RubricScores(correctness=2, completeness=1, causal_clarity=1, transfer=3),
        )
        result = compute_server_gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("0|1|2 domain" in reason for reason in result.reasons)


class TestFullExplanationResetProperty:
    def test_old_chain_never_passes_after_full_explanation(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        # Confirmed complete before the reset.
        old = passing_assessment(evidence_ids=chain_evidence_ids(progress, attempt))
        assert compute_server_gate(progress, attempt, old).passed is True
        rotate_chain_for_full_explanation(progress, attempt, now=START + 100)
        # The same evidence (now in the old chain) cannot pass any later gate.
        later = passing_assessment(
            evidence_ids=chain_evidence_ids(progress, attempt),
            created_at=START + 101,
        )
        result = compute_server_gate(progress, attempt, later)
        assert result.passed is False
        assert result.used_full_explanation is True


class TestProjectionRebuildProperties:
    def test_rebuild_matches_recorded_projection_and_is_idempotent(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record(progress, attempt, created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        proj = rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.mastery_state == MasteryState.PROVISIONAL_MASTERY
        again = rebuild_projection(progress, "kp1", now=START + 50)
        assert proj.model_dump() == again.model_dump()
        # The stored projection dict matches the rebuild when kept fresh.
        progress.projections["kp1"] = proj
        assert progress.projections["kp1"].model_dump() == proj.model_dump()

    def test_rebuild_is_deterministic_under_list_reordering(self):
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        baseline = rebuild_projection(progress, "kp1", now=START + 550)
        progress.rubric_assessments.reverse()
        progress.attempts.reverse()
        reordered = rebuild_projection(progress, "kp1", now=START + 550)
        assert baseline.model_dump() == reordered.model_dump()

    def test_rebuild_is_order_insensitive_with_equal_timestamps(self):
        """Equal ``created_at`` attempts tie-break by id: reversing the
        append-only list must not change the projected active attempt."""
        progress, attempt = kp_progress()
        progress.attempts = []
        add_attempt(
            progress,
            attempt_id="a1",
            cycle_type="initial",
            status=AttemptStatus.COLLECTING,
            created_at=START,
        )
        add_attempt(
            progress,
            attempt_id="a2",
            cycle_type="initial",
            status=AttemptStatus.COLLECTING,
            created_at=START,
        )
        baseline = rebuild_projection(progress, "kp1", now=START)
        assert baseline.active_attempt_id == "a2"
        progress.attempts.reverse()
        reordered = rebuild_projection(progress, "kp1", now=START)
        assert reordered.model_dump() == baseline.model_dump()
        assert reordered.active_attempt_id == "a2"

    def test_invalidated_attempt_gate_never_overwrites_valid_projection(self):
        """An assessment attached to an ``invalidated`` attempt is preserved in
        history but never becomes projection input (§7.3.1, §7.7)."""
        progress, attempt = kp_progress()
        append_complete_chain(progress, attempt)
        _record(progress, attempt, assessment_id="ra1", created_at=START + 50)
        attempt.status = AttemptStatus.ASSESSED
        reteach = add_attempt(progress, attempt_id="a2", cycle_type="delayed_reteach")
        append_complete_chain(progress, reteach, start=START + 500)
        _record(progress, reteach, assessment_id="ra2", created_at=START + 550)
        reteach.status = AttemptStatus.ASSESSED
        invalid = add_attempt(
            progress,
            attempt_id="a3",
            cycle_type="reevaluation",
            status=AttemptStatus.INVALIDATED,
            chain_id="chain-3",
            created_at=START + 800,
        )
        append_complete_chain(progress, invalid, start=START + 900)
        _record(progress, invalid, assessment_id="ra3", passed=False, created_at=START + 950)
        proj = rebuild_projection(progress, "kp1", now=START + 950)
        # The invalidated failing gate cannot overwrite the latest valid state.
        assert proj.mastery_state == MasteryState.STABLE_MASTERY
        assert proj.latest_assessment_id == "ra2"
