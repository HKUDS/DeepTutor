"""LRN-03 Feynman cycle service tests.

Covers the attempt lifecycle (start / record / finalize), challenge/resume,
versioned map edit/confirm, and conflict resolve/reopen — both the happy paths
and the deterministic negative contract (spec §17.1, §17.2). No LLM, no
network.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.cycles import (
    ConflictResolutionError,
    EvidenceConflictError,
    EvidenceOrderError,
    FeynmanCycleService,
    FeynmanError,
    IdempotencyConflictError,
    InvalidAttemptStateError,
    OwnershipError,
    StaleVersionError,
    UnknownAttemptError,
    UnknownConflictError,
    _content_hash,
)
from deeptutor.learning.models import (
    AttemptCycleType,
    AttemptStatus,
    ConflictStatus,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    InputMode,
    KnowledgeMapVersion,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    MasteryState,
    ReviewState,
    RubricScores,
    SourceCitation,
    SourceConflict,
    SourceSnapshot,
)
from deeptutor.learning.storage import (
    LearningStore,
    append_history,
    apply_map_version,
    invalidate_attempts,
)

START = 1_000_000.0


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


@pytest.fixture
def service(store):
    return FeynmanCycleService(store)


def _progress(book_id: str = "p1") -> LearningProgress:
    progress = LearningProgress(book_id=book_id)
    progress.modules = [
        LearningModule(
            id="m1",
            name="Module 1",
            order=0,
            knowledge_points=[
                KnowledgePoint(id="kp1", name="KP1", type=KnowledgeType.CONCEPT, module_id="m1")
            ],
        )
    ]
    progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
    return progress


def _with_map_and_sources(progress: LearningProgress) -> LearningProgress:
    progress.source_snapshots.extend(
        [
            SourceSnapshot(id="s1", citation_anchors=["p.3"]),
            SourceSnapshot(id="s2", citation_anchors=["fig.2"]),
        ]
    )
    progress.map_versions.append(
        KnowledgeMapVersion(
            id="p1:map:1",
            path_id=progress.book_id,
            version=1,
            source_snapshot_ids=["s1", "s2"],
        )
    )
    return progress


def _identity(**overrides) -> dict[str, str]:
    identity = {
        "path_id": "p1",
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "message_id": "msg-1",
        "user_id": "owner",
    }
    identity.update(overrides)
    return identity


def _start(service: FeynmanCycleService, progress: LearningProgress, **kwargs):
    return service.start_cycle(
        progress,
        knowledge_point_id="kp1",
        cycle_type=kwargs.get("cycle_type", "initial"),
        session_id=kwargs.get("session_id", "sess-1"),
        turn_id=kwargs.get("turn_id", "turn-1"),
    )


def _record(service: FeynmanCycleService, progress: LearningProgress, attempt_id: str, **kwargs):
    return service.record_evidence(
        progress,
        attempt_id=attempt_id,
        kind=kwargs["kind"],
        event_id=kwargs["event_id"],
        content=kwargs.get("content", "content"),
        identity=kwargs.get("identity", _identity()),
        question_evidence_id=kwargs.get("question_evidence_id", ""),
        source_citations=kwargs.get("source_citations", []),
        input_mode=kwargs.get("input_mode", "text"),
        transcript_confirmed=kwargs.get("transcript_confirmed", False),
        help_level=kwargs.get("help_level"),
        # §8.3: the concurrency token is required; callers default to the
        # current attempt version and override it only to test staleness.
        expected_attempt_version=kwargs.get(
            "expected_attempt_version", progress.aggregate_versions.attempt
        ),
    )


def _chain_ids(progress: LearningProgress, attempt_id: str) -> list[str]:
    attempt = next(a for a in progress.attempts if a.id == attempt_id)
    return [
        e.id
        for e in progress.evidence_items
        if e.attempt_id == attempt_id and e.chain_id == attempt.active_chain_id
    ]


def _complete_chain(service: FeynmanCycleService, progress: LearningProgress, attempt_id: str):
    """Record a full, valid evidence chain and return the evidence ids."""
    _record(
        service,
        progress,
        attempt_id,
        kind="explanation",
        event_id="e-expl",
        content="My explanation",
    )
    q1 = _record(
        service, progress, attempt_id, kind="probe_question", event_id="e-q1", content="Q1?"
    )
    _record(
        service,
        progress,
        attempt_id,
        kind="probe_answer",
        event_id="e-a1",
        content="A1",
        question_evidence_id=q1["evidence_id"],
    )
    q2 = _record(
        service, progress, attempt_id, kind="probe_question", event_id="e-q2", content="Q2?"
    )
    _record(
        service,
        progress,
        attempt_id,
        kind="probe_answer",
        event_id="e-a2",
        content="A2",
        question_evidence_id=q2["evidence_id"],
    )
    qt = _record(
        service, progress, attempt_id, kind="transfer_question", event_id="e-qt", content="T?"
    )
    _record(
        service,
        progress,
        attempt_id,
        kind="transfer_answer",
        event_id="e-at",
        content="TA",
        question_evidence_id=qt["evidence_id"],
    )
    return _chain_ids(progress, attempt_id)


def _passing_rubric() -> RubricScores:
    return RubricScores(correctness=2, completeness=1, causal_clarity=1, transfer=2)


def _finalize(service: FeynmanCycleService, progress: LearningProgress, attempt_id: str, **kwargs):
    prior_assessments = len([a for a in progress.rubric_assessments if a.attempt_id == attempt_id])
    return service.finalize(
        progress,
        attempt_id=attempt_id,
        rubric=kwargs.get("rubric", _passing_rubric()),
        critical_errors=kwargs.get("critical_errors", []),
        strengths=kwargs.get("strengths", []),
        gap_candidates=kwargs.get("gap_candidates", []),
        evidence_ids=kwargs.get("evidence_ids", _chain_ids(progress, attempt_id)),
        source_citations=kwargs.get(
            "source_citations", [SourceCitation(source_snapshot_id="s1", anchor="p.3")]
        ),
        model_invocation_id=kwargs.get("model_invocation_id", ""),
        challenge_id=kwargs.get("challenge_id", ""),
        # §8.3: every finalize carries a distinct idempotency key + the current
        # concurrency token (overridable to exercise replay/staleness).
        event_id=kwargs.get("event_id", f"fin-{attempt_id}-{prior_assessments + 1}"),
        expected_attempt_version=kwargs.get(
            "expected_attempt_version", progress.aggregate_versions.attempt
        ),
        now=START + 100,
    )


# ── cycle start ───────────────────────────────────────────────────────────


class TestCycleStart:
    def test_creates_attempt_with_frozen_bindings(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        assert attempt.status == AttemptStatus.COLLECTING
        assert attempt.map_version_id == "p1:map:1"
        assert attempt.source_snapshot_ids == ["s1", "s2"]
        assert attempt.knowledge_point_version == 1
        assert attempt.active_chain_id == f"{attempt.id}:chain:1"
        assert attempt.cycle_type == AttemptCycleType.INITIAL
        assert attempt.evaluator_snapshot is not None

    def test_resumes_live_attempt_idempotently(self, service, store):
        progress = _with_map_and_sources(_progress())
        first = _start(service, progress)
        second = _start(service, progress)
        assert second.id == first.id
        assert len(progress.attempts) == 1

    def test_test_out_cycle(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress, cycle_type="test_out")
        assert attempt.cycle_type == AttemptCycleType.TEST_OUT

    def test_after_invalidated_creates_fresh_attempt(self, service, store):
        progress = _with_map_and_sources(_progress())
        first = _start(service, progress)
        invalidate_attempts(progress, attempt_ids=[first.id], reason="source_version_changed")
        second = _start(service, progress)
        assert second.id != first.id
        # No evidence is carried across.
        assert second.active_chain_id != first.active_chain_id


# ── record evidence ───────────────────────────────────────────────────────


class TestRecordEvidence:
    def test_binds_server_identity(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(
            service,
            progress,
            attempt.id,
            kind="explanation",
            event_id="e1",
            content="hello",
            identity=_identity(
                session_id="trusted-session", turn_id="trusted-turn", message_id="trusted-msg"
            ),
        )
        item = progress.evidence_items[0]
        assert item.session_id == "trusted-session"
        assert item.turn_id == "trusted-turn"
        assert item.message_id == "trusted-msg"
        assert item.content_hash  # stored for idempotent replay

    def test_same_event_key_same_payload_replays(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        first = _record(
            service, progress, attempt.id, kind="explanation", event_id="e1", content="same"
        )
        second = _record(
            service, progress, attempt.id, kind="explanation", event_id="e1", content="same"
        )
        assert second["replay"] is True
        assert second["evidence_id"] == first["evidence_id"]
        assert len(progress.evidence_items) == 1

    def test_same_event_key_different_payload_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(service, progress, attempt.id, kind="explanation", event_id="e1", content="same")
        with pytest.raises(EvidenceConflictError):
            _record(
                service,
                progress,
                attempt.id,
                kind="explanation",
                event_id="e1",
                content="different",
            )

    def test_stale_expected_version_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        # The attempt aggregate is at 1 after start; expect a stale guard at 0.
        with pytest.raises(StaleVersionError):
            _record(
                service,
                progress,
                attempt.id,
                kind="explanation",
                event_id="e1",
                content="x",
                expected_attempt_version=0,
            )

    def test_record_on_invalidated_attempt_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        invalidate_attempts(progress, attempt_ids=[attempt.id], reason="source_version_changed")
        with pytest.raises(InvalidAttemptStateError):
            _record(service, progress, attempt.id, kind="explanation", event_id="e1", content="x")

    def test_voice_transcript_requires_confirmation(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(InvalidAttemptStateError):
            _record(
                service,
                progress,
                attempt.id,
                kind="explanation",
                event_id="e1",
                content="voice",
                input_mode=InputMode.VOICE_TRANSCRIPT.value,
                transcript_confirmed=False,
            )
        # Confirmed voice transcript is accepted.
        _record(
            service,
            progress,
            attempt.id,
            kind="explanation",
            event_id="e1",
            content="voice",
            input_mode=InputMode.VOICE_TRANSCRIPT.value,
            transcript_confirmed=True,
        )
        assert progress.evidence_items[0].transcript_confirmed is True

    def test_probe_answer_without_binding_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(service, progress, attempt.id, kind="explanation", event_id="e1", content="expl")
        from deeptutor.learning.cycles import EvidenceOrderError

        with pytest.raises(EvidenceOrderError):
            _record(service, progress, attempt.id, kind="probe_answer", event_id="e2", content="a")


# ── finalize ──────────────────────────────────────────────────────────────


class TestFinalize:
    def test_full_chain_passing_finalize_is_provisional(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        result = _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        assert result["passed"] is True
        assert result["mastery_state"] == MasteryState.PROVISIONAL_MASTERY.value
        assert result["review_state"] == ReviewState.SCHEDULED.value
        assert result["next_review_at"] is not None
        assert progress.attempts[0].status == AttemptStatus.ASSESSED

    def test_citation_outside_frozen_snapshots_fails_gate(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        result = _finalize(
            service,
            progress,
            attempt.id,
            evidence_ids=evidence_ids,
            source_citations=[SourceCitation(source_snapshot_id="s99", anchor="p.1")],
        )
        assert result["passed"] is False
        assert any("does not resolve" in reason for reason in result["server_gate"]["reasons"])

    def test_invalid_rubric_fails_gate(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        result = _finalize(
            service,
            progress,
            attempt.id,
            evidence_ids=evidence_ids,
            rubric=RubricScores(correctness=1, completeness=1, causal_clarity=1, transfer=2),
        )
        assert result["passed"] is False

    def test_finalize_on_invalidated_attempt_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        invalidate_attempts(progress, attempt_ids=[attempt.id], reason="source_version_changed")
        with pytest.raises(InvalidAttemptStateError):
            _finalize(service, progress, attempt.id)

    def test_assessment_sequence_is_monotonic_per_kp(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        first = _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        assert first["assessment_sequence"] == 1
        # A new attempt for the same kp gets the next sequence number.
        attempt2 = _start(service, progress)
        evidence2 = _complete_chain(service, progress, attempt2.id)
        second = _finalize(service, progress, attempt2.id, evidence_ids=evidence2)
        assert second["assessment_sequence"] == 2

    def test_unknown_attempt_finalize_raises(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(UnknownAttemptError):
            service.finalize(
                progress,
                attempt_id="nope",
                rubric=_passing_rubric(),
                critical_errors=[],
                strengths=[],
                gap_candidates=[],
                evidence_ids=[],
                source_citations=[],
                event_id="fin-nope-1",
                expected_attempt_version=0,
            )

    def test_stale_expected_version_finalize_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        with pytest.raises(StaleVersionError):
            service.finalize(
                progress,
                attempt_id=attempt.id,
                rubric=_passing_rubric(),
                critical_errors=[],
                strengths=[],
                gap_candidates=[],
                evidence_ids=evidence_ids,
                source_citations=[],
                event_id="fin-stale-1",
                expected_attempt_version=0,
            )

    def test_full_explanation_rotates_chain_and_old_chain_fails(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        old_chain = attempt.active_chain_id
        old_ids = _complete_chain(service, progress, attempt.id)
        # A full_explanation closes the current chain.
        _record(
            service,
            progress,
            attempt.id,
            kind="reteach",
            event_id="e-full",
            content="full explanation",
            help_level="full_explanation",
        )
        assert attempt.active_chain_id != old_chain
        # The old complete chain can no longer pass the gate.
        result = _finalize(service, progress, attempt.id, evidence_ids=old_ids)
        assert result["passed"] is False
        assert result["server_gate"]["used_full_explanation"] is True


# ── challenge / resume ────────────────────────────────────────────────────


class TestChallenge:
    def test_reassess_appends_later_revision(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="reassess_existing",
            request_id="ch-reassess-1",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        assert challenge.status.value == "pending"
        result = _finalize(
            service,
            progress,
            attempt.id,
            evidence_ids=evidence_ids,
            challenge_id=challenge.id,
        )
        assert result["revision"] == 2
        challenge_after = next(c for c in progress.challenge_records if c.id == challenge.id)
        assert challenge_after.status.value == "completed"
        assert challenge_after.result_assessment_id == result["assessment_id"]

    def test_collect_new_evidence_creates_reevaluation_attempt(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-collect-1",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        new_attempt = next(a for a in progress.attempts if a.id == challenge.result_attempt_id)
        assert new_attempt.cycle_type == AttemptCycleType.REEVALUATION
        assert new_attempt.supersedes_attempt_id == attempt.id

    def test_challenge_cannot_shortcut_to_stable(self, service, store):
        """A collect-new-evidence pass (reevaluation) never grants stable."""
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-collect-shortcut",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        new_attempt = next(a for a in progress.attempts if a.id == challenge.result_attempt_id)
        evidence2 = _complete_chain(service, progress, new_attempt.id)
        result = _finalize(service, progress, new_attempt.id, evidence_ids=evidence2)
        assert result["passed"] is True
        assert result["mastery_state"] == MasteryState.PROVISIONAL_MASTERY.value


class TestResume:
    def test_invalidated_resume_returns_requires_restart(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        invalidate_attempts(progress, attempt_ids=[attempt.id], reason="source_version_changed")
        result = service.resume_attempt(progress, attempt_id=attempt.id)
        assert result["status"] == "requires_restart"
        assert result["map_version"] == 1
        assert result["invalidated_reason"] == "source_version_changed"

    def test_draft_resume_returns_attempt_state(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        result = service.resume_attempt(progress, attempt_id=attempt.id)
        assert result["status"] == "resumed"
        assert result["chain_id"] == attempt.active_chain_id

    def test_resume_unknown_raises(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(UnknownAttemptError):
            service.resume_attempt(progress, attempt_id="nope")


# ── map edit / confirm ────────────────────────────────────────────────────


class TestMapEdit:
    def test_edit_creates_new_version_and_invalidates(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        result = service.edit_map(
            progress,
            nodes=["kp1", "kp2"],
            edges=[{"from": "kp1", "to": "kp2"}],
            priorities={"kp2": 1},
            expected_map_version=1,
            request_id="edit-1",
            actor_id="owner",
        )
        assert result["map_version"] == 2
        assert progress.attempts[0].status == AttemptStatus.INVALIDATED

    def test_edit_stale_version_conflict(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(StaleVersionError):
            service.edit_map(
                progress,
                nodes=[],
                edges=[],
                priorities={},
                expected_map_version=5,
                request_id="edit-stale",
                actor_id="owner",
            )

    def test_edit_requires_owner(self, service, store):
        progress = _with_map_and_sources(_progress())
        service.edit_map(
            progress,
            nodes=[],
            edges=[],
            priorities={},
            expected_map_version=1,
            request_id="edit-owner-1",
            actor_id="owner",
        )
        with pytest.raises(OwnershipError):
            service.edit_map(
                progress,
                nodes=[],
                edges=[],
                priorities={},
                expected_map_version=2,
                request_id="edit-owner-2",
                actor_id="intruder",
            )

    def test_confirm_map_idempotent(self, service, store):
        progress = _with_map_and_sources(_progress())
        first = service.confirm_map(
            progress, expected_map_version=1, request_id="r1", actor_id="owner"
        )
        second = service.confirm_map(
            progress, expected_map_version=1, request_id="r1", actor_id="owner"
        )
        assert second["replayed"] is True
        assert first["map_version"] == 1


# ── conflict resolve / reopen ─────────────────────────────────────────────


def _with_conflict(progress: LearningProgress) -> LearningProgress:
    progress.source_conflicts.append(
        SourceConflict(
            id="c1",
            path_id=progress.book_id,
            knowledge_point_ids=["kp1"],
            claim="Two sources disagree on the definition.",
            source_snapshot_ids=["s1", "s2"],
            citation_anchors=["p.3", "fig.2"],
            version=1,
            status=ConflictStatus.OPEN,
        )
    )
    return progress


def _with_two_conflicts(progress: LearningProgress) -> LearningProgress:
    """Two distinct OPEN conflicts over the same materialized snapshots."""
    _with_conflict(progress)
    progress.source_conflicts.append(
        SourceConflict(
            id="c2",
            path_id=progress.book_id,
            knowledge_point_ids=["kp1"],
            claim="A second disagreement on the same definition.",
            source_snapshot_ids=["s1", "s2"],
            citation_anchors=["p.3", "fig.2"],
            version=1,
            status=ConflictStatus.OPEN,
        )
    )
    return progress


class TestConflictResolve:
    def test_resolve_creates_revision_and_invalidates(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        attempt = _start(service, progress)
        result = service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="s1 is authoritative here",
            actor_id="owner",
            request_id="res-1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        assert result["status"] == "resolved"
        current = max(progress.source_conflicts, key=lambda c: c.version)
        assert current.version == 2
        assert current.status == ConflictStatus.RESOLVED
        assert current.accepted_snapshot_id == "s1"
        assert current.resolved_by == "owner"
        assert result["map_version"] == 2
        assert progress.attempts[0].status == AttemptStatus.INVALIDATED

    def test_resolve_rejects_snapshot_not_listed(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(ConflictResolutionError):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s99",
                resolution_note="note",
                actor_id="owner",
                request_id="res-notlisted",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_resolve_requires_note(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(ConflictResolutionError):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="   ",
                actor_id="owner",
                request_id="res-note",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_resolve_requires_owner(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="res-owner-1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        with pytest.raises(OwnershipError):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="intruder",
                request_id="res-owner-2",
                expected_conflict_version=2,
                expected_map_version=2,
            )

    def test_unknown_conflict_raises(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(UnknownConflictError):
            service.resolve_conflict(
                progress,
                conflict_id="nope",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="res-unknown",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_reopen_restores_correctness_block(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="res-block-1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        result = service.reopen_conflict(
            progress,
            conflict_id="c1",
            actor_id="owner",
            request_id="reopen-1",
            expected_conflict_version=2,
            expected_map_version=2,
        )
        assert result["status"] == "open"
        assert result["blocking"] is True
        current = max(progress.source_conflicts, key=lambda c: c.version)
        assert current.status == ConflictStatus.OPEN

    def test_reopen_requires_owner(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        # Claim the path for "owner" first, then a non-owner cannot reopen.
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="res-owner-claim",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        with pytest.raises(OwnershipError):
            service.reopen_conflict(
                progress,
                conflict_id="c1",
                actor_id="intruder",
                request_id="reopen-intruder",
                expected_conflict_version=2,
                expected_map_version=2,
            )


# ── read helpers ──────────────────────────────────────────────────────────


class TestReadHelpers:
    def test_map_read_payload(self, service, store):
        progress = _with_map_and_sources(_progress())
        _start(service, progress)
        payload = service.map_read_payload(progress, now=START)
        assert payload["map_version"] == 1
        assert payload["active_attempts"]["kp1"]["attempt_id"]
        assert payload["evidence_summary"]["kp1"]["count"] == 0
        assert "projections" in payload

    def test_attempt_read_payload(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        payload = service.attempt_read_payload(progress, attempt_id=attempt.id)
        assert len(payload["evidence"]) == 7
        assert len(payload["assessments"]) == 1
        assert payload["projection"]["mastery_state"] == "provisional_mastery"

    def test_reviews_read_payload(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        payload = service.reviews_read_payload(progress, now=START)
        assert len(payload["reviews"]) == 1
        assert payload["reviews"][0]["knowledge_point_id"] == "kp1"

    def test_unified_review_queue_keeps_legacy_reviews(self, service, store):
        """Finalizing a Feynman concept must not drop a memory kp's legacy
        spaced-repetition review (§13.2 unified review queue)."""
        from deeptutor.learning.models import (
            RepetitionState,
            ReviewTask,
        )

        progress = _with_map_and_sources(_progress())
        # Add a legacy memory kp mastered via the quiz path.
        progress.modules[0].knowledge_points.append(
            KnowledgePoint(id="kp-mem", name="MEM", type=KnowledgeType.MEMORY, module_id="m1")
        )
        progress.knowledge_types["kp-mem"] = KnowledgeType.MEMORY
        progress.repetition_states["kp-mem"] = RepetitionState(
            interval_index=1, next_review_at=START + 86400
        )
        progress.review_queue = [
            ReviewTask(
                id="review_kp-mem",
                knowledge_point_id="kp-mem",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=START + 86400,
                priority=2,
                state=progress.repetition_states["kp-mem"],
            )
        ]

        # Run a Feynman finalize on kp1.
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)

        kp_ids = {task.knowledge_point_id for task in progress.review_queue}
        assert "kp-mem" in kp_ids
        assert "kp1" in kp_ids


# ── Finding 9: cycle start validates the path + frozen map basis ──────────


class TestCycleStartValidation:
    def test_unknown_kp_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(FeynmanError):
            service.start_cycle(
                progress,
                knowledge_point_id="nope",
                cycle_type="initial",
                session_id="s",
                turn_id="t",
            )

    def test_start_without_confirmed_map_rejected(self, service, store):
        progress = _progress()  # modules but no confirmed map/source basis
        with pytest.raises(FeynmanError, match="map/source basis"):
            service.start_cycle(
                progress,
                knowledge_point_id="kp1",
                cycle_type="initial",
                session_id="s",
                turn_id="t",
            )

    def test_test_out_still_requires_map_basis(self, service, store):
        progress = _progress()
        with pytest.raises(FeynmanError):
            service.start_cycle(
                progress,
                knowledge_point_id="kp1",
                cycle_type="test_out",
                session_id="s",
                turn_id="t",
            )


# ── Finding 2: canonical full-request fingerprint idempotency ─────────────


class TestEvidenceFingerprint:
    def test_same_event_key_different_kind_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(service, progress, attempt.id, kind="explanation", event_id="e1", content="same")
        with pytest.raises(EvidenceConflictError):
            _record(
                service, progress, attempt.id, kind="probe_question", event_id="e1", content="same"
            )

    def test_same_event_key_different_identity_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(
            service,
            progress,
            attempt.id,
            kind="explanation",
            event_id="e1",
            content="same",
            identity=_identity(),
        )
        with pytest.raises(EvidenceConflictError):
            _record(
                service,
                progress,
                attempt.id,
                kind="explanation",
                event_id="e1",
                content="same",
                identity=_identity(session_id="other-session"),
            )

    def test_same_event_key_different_binding_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(service, progress, attempt.id, kind="explanation", event_id="e1", content="same")
        _record(service, progress, attempt.id, kind="probe_question", event_id="e2", content="Q?")
        with pytest.raises(EvidenceConflictError):
            _record(
                service,
                progress,
                attempt.id,
                kind="probe_question",
                event_id="e1",
                content="same",
            )

    def test_replay_after_restart(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        first = _record(
            service, progress, attempt.id, kind="explanation", event_id="e1", content="same"
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = service.record_evidence(
            reloaded,
            attempt_id=attempt.id,
            kind="explanation",
            event_id="e1",
            content="same",
            identity=_identity(),
            expected_attempt_version=reloaded.aggregate_versions.attempt,
        )
        assert second["replay"] is True
        assert second["evidence_id"] == first["evidence_id"]
        assert len(reloaded.evidence_items) == 1

    def test_replay_with_stale_expected_version_returns_prior_result(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(
            service,
            progress,
            attempt.id,
            kind="explanation",
            event_id="e1",
            content="same",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        # A committed retry passes a stale expected version; idempotency is
        # checked before the version guard, so the prior result replays.
        second = _record(
            service,
            progress,
            attempt.id,
            kind="explanation",
            event_id="e1",
            content="same",
            expected_attempt_version=0,
        )
        assert second["replay"] is True
        assert len(progress.evidence_items) == 1


# ── Finding 7: meaningful content + strict chain order ────────────────────


class TestEvidenceContentAndOrder:
    def test_blank_content_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(FeynmanError, match="blank"):
            _record(service, progress, attempt.id, kind="explanation", event_id="e1", content="   ")

    def test_whitespace_probe_answer_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(
            service, progress, attempt.id, kind="explanation", event_id="e-expl", content="expl"
        )
        q1 = _record(
            service, progress, attempt.id, kind="probe_question", event_id="e-q1", content="Q1?"
        )
        with pytest.raises(FeynmanError, match="blank"):
            _record(
                service,
                progress,
                attempt.id,
                kind="probe_answer",
                event_id="e-a1",
                content="\n\t",
                question_evidence_id=q1["evidence_id"],
            )

    def test_transfer_requires_two_bound_probe_pairs(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _record(
            service, progress, attempt.id, kind="explanation", event_id="e-expl", content="expl"
        )
        q1 = _record(
            service, progress, attempt.id, kind="probe_question", event_id="e-q1", content="Q1?"
        )
        _record(
            service,
            progress,
            attempt.id,
            kind="probe_answer",
            event_id="e-a1",
            content="A1",
            question_evidence_id=q1["evidence_id"],
        )
        with pytest.raises(EvidenceOrderError, match="two bound probe pairs"):
            _record(
                service,
                progress,
                attempt.id,
                kind="transfer_question",
                event_id="e-qt",
                content="T?",
            )

    def test_late_probe_after_transfer_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _complete_chain(service, progress, attempt.id)
        with pytest.raises(EvidenceOrderError, match="already in transfer"):
            _record(
                service,
                progress,
                attempt.id,
                kind="probe_question",
                event_id="e-late",
                content="late?",
            )

    def test_late_explanation_after_transfer_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        _complete_chain(service, progress, attempt.id)
        with pytest.raises(EvidenceOrderError, match="already in transfer"):
            _record(
                service,
                progress,
                attempt.id,
                kind="explanation",
                event_id="e-late",
                content="again",
            )

    def test_source_reference_citation_outside_frozen_snapshots_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(EvidenceOrderError, match="not frozen"):
            _record(
                service,
                progress,
                attempt.id,
                kind="source_reference",
                event_id="e-src",
                content="ref",
                source_citations=[SourceCitation(source_snapshot_id="s99", anchor="p.1")],
            )

    def test_out_of_order_but_count_complete_chain_cannot_pass_gate(self, service, store):
        """Explanation -> transfer -> probes is count-complete but out of
        order; the server gate must reject it (finding 7)."""
        from deeptutor.learning.grading import compute_server_gate
        from deeptutor.learning.models import RubricAssessment

        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        seq = 0

        def ev(kind, **kw):
            nonlocal seq
            seq += 1
            item = EvidenceItem(
                id=f"{attempt.id}:out:{seq}",
                attempt_id=attempt.id,
                chain_id=attempt.active_chain_id,
                kind=kind,
                content_snapshot="x",
                content_hash="h",
                event_seq=seq,
                created_at=START + seq,
                **kw,
            )
            progress.evidence_items.append(item)
            return item

        ev(EvidenceKind.EXPLANATION)
        qt = ev(EvidenceKind.TRANSFER_QUESTION)
        ev(EvidenceKind.TRANSFER_ANSWER, question_evidence_id=qt.id)
        q1 = ev(EvidenceKind.PROBE_QUESTION)
        ev(EvidenceKind.PROBE_ANSWER, question_evidence_id=q1.id)
        q2 = ev(EvidenceKind.PROBE_QUESTION)
        ev(EvidenceKind.PROBE_ANSWER, question_evidence_id=q2.id)
        assessment = RubricAssessment(
            id="ra-out",
            attempt_id=attempt.id,
            rubric=_passing_rubric(),
            evidence_ids=[e.id for e in progress.evidence_items],
        )
        result = compute_server_gate(progress, attempt, assessment)
        assert result.passed is False
        assert any("out of order" in reason for reason in result.reasons)


# ── Finding 8: finalize idempotency (attempt_id + event_id) ───────────────


class TestFinalizeIdempotency:
    def _finalize(self, service, progress, attempt_id, **kwargs):
        return service.finalize(
            progress,
            attempt_id=attempt_id,
            rubric=kwargs.get("rubric", _passing_rubric()),
            critical_errors=kwargs.get("critical_errors", []),
            strengths=kwargs.get("strengths", []),
            gap_candidates=kwargs.get("gap_candidates", []),
            evidence_ids=kwargs.get("evidence_ids", _chain_ids(progress, attempt_id)),
            source_citations=kwargs.get(
                "source_citations", [SourceCitation(source_snapshot_id="s1", anchor="p.3")]
            ),
            model_invocation_id=kwargs.get("model_invocation_id", ""),
            challenge_id=kwargs.get("challenge_id", ""),
            expected_attempt_version=kwargs.get(
                "expected_attempt_version", progress.aggregate_versions.attempt
            ),
            event_id=kwargs.get("event_id", f"fin-{attempt_id}-1"),
            now=START + 100,
        )

    def test_replay_after_restart_never_creates_second_assessment(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        first = self._finalize(
            service, progress, attempt.id, evidence_ids=evidence_ids, event_id="fin-1"
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = self._finalize(
            service, reloaded, attempt.id, evidence_ids=evidence_ids, event_id="fin-1"
        )
        assert second["replayed"] is True
        assert second["assessment_id"] == first["assessment_id"]
        assert len(reloaded.rubric_assessments) == 1

    def test_same_key_different_payload_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        self._finalize(service, progress, attempt.id, evidence_ids=evidence_ids, event_id="fin-1")
        with pytest.raises(IdempotencyConflictError):
            self._finalize(
                service,
                progress,
                attempt.id,
                evidence_ids=evidence_ids,
                event_id="fin-1",
                rubric=RubricScores(correctness=1, completeness=1, causal_clarity=1, transfer=2),
            )
        assert len(progress.rubric_assessments) == 1

    def test_replay_with_stale_expected_version_returns_prior_result(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        self._finalize(
            service,
            progress,
            attempt.id,
            evidence_ids=evidence_ids,
            event_id="fin-1",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = self._finalize(
            service,
            reloaded,
            attempt.id,
            evidence_ids=evidence_ids,
            event_id="fin-1",
            expected_attempt_version=0,
        )
        assert second["replayed"] is True
        assert len(reloaded.rubric_assessments) == 1


# ── Finding 6: challenge linkage / idempotency ────────────────────────────


class TestChallengeLinkage:
    def test_reassess_requires_prior_assessment(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(InvalidAttemptStateError, match="prior assessment"):
            service.create_challenge(
                progress,
                attempt_id=attempt.id,
                mode="reassess_existing",
                request_id="ch-noprior",
                expected_attempt_version=progress.aggregate_versions.attempt,
            )

    def test_duplicate_pending_challenge_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="reassess_existing",
            request_id="ch-dup-1",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        with pytest.raises(IdempotencyConflictError):
            service.create_challenge(
                progress,
                attempt_id=attempt.id,
                mode="reassess_existing",
                request_id="ch-dup-2",
                expected_attempt_version=progress.aggregate_versions.attempt,
            )

    def test_reassess_challenge_mismatched_attempt_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        attempt2 = _start(service, progress)
        evidence2 = _complete_chain(service, progress, attempt2.id)
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="reassess_existing",
            request_id="ch-mismatch",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        with pytest.raises(InvalidAttemptStateError):
            _finalize(
                service,
                progress,
                attempt2.id,
                evidence_ids=evidence2,
                challenge_id=challenge.id,
            )

    def test_collect_new_evidence_challenge_on_wrong_attempt_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-wrong",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        # Finalizing the source attempt with the collect challenge id must fail.
        with pytest.raises(InvalidAttemptStateError):
            _finalize(
                service,
                progress,
                attempt.id,
                evidence_ids=evidence_ids,
                challenge_id=challenge.id,
            )

    def test_collect_new_evidence_assessment_stores_effective_challenge_id(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-effective",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        new_attempt = next(a for a in progress.attempts if a.id == challenge.result_attempt_id)
        evidence2 = _complete_chain(service, progress, new_attempt.id)
        result = _finalize(service, progress, new_attempt.id, evidence_ids=evidence2)
        assessment = next(a for a in progress.rubric_assessments if a.id == result["assessment_id"])
        assert assessment.challenge_id == challenge.id

    def test_challenge_creation_idempotent_under_request_id(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        version = progress.aggregate_versions.attempt
        first = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-1",
            expected_attempt_version=version,
        )
        second = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-1",
            expected_attempt_version=version,
        )
        assert second.id == first.id
        assert len(progress.challenge_records) == 1
        with pytest.raises(IdempotencyConflictError):
            service.create_challenge(
                progress,
                attempt_id=attempt.id,
                mode="reassess_existing",
                request_id="ch-1",
                expected_attempt_version=version,
            )


# ── Finding 4: map confirmation is append-only ────────────────────────────


class TestMapConfirmAppendOnly:
    def test_source_change_appends_new_version_and_invalidates(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        result = service.confirm_map(
            progress,
            expected_map_version=1,
            source_snapshot_ids=["s1"],
            actor_id="owner",
            request_id="confirm-1",
        )
        assert result["map_version"] == 2
        assert result["invalidated_attempt_ids"] == [attempt.id]
        assert len(progress.map_versions) == 2
        # The historical confirmed version is preserved byte-for-byte.
        assert progress.map_versions[0].version == 1
        assert progress.map_versions[0].source_snapshot_ids == ["s1", "s2"]

    def test_prior_version_unchanged_after_restart_round_trip(self, service, store):
        progress = _with_map_and_sources(_progress())
        _start(service, progress)
        before = progress.map_versions[0].model_dump()
        service.confirm_map(
            progress,
            expected_map_version=1,
            source_snapshot_ids=["s1"],
            actor_id="owner",
            request_id="confirm-rt",
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        assert reloaded.map_versions[0].model_dump() == before
        assert reloaded.map_versions[1].source_snapshot_ids == ["s1"]

    def test_invalid_snapshot_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(ConflictResolutionError, match="unknown source snapshots"):
            service.confirm_map(
                progress,
                expected_map_version=1,
                source_snapshot_ids=["s99"],
                actor_id="owner",
                request_id="confirm-bad",
            )
        # Nothing was mutated.
        assert len(progress.map_versions) == 1

    def test_confirm_same_sources_is_noop(self, service, store):
        progress = _with_map_and_sources(_progress())
        result = service.confirm_map(
            progress,
            expected_map_version=1,
            source_snapshot_ids=["s1", "s2"],
            actor_id="owner",
            request_id="confirm-noop",
        )
        assert result["map_version"] == 1
        assert result["invalidated_attempt_ids"] == []
        assert len(progress.map_versions) == 1


# ── Finding 3: map/conflict full-result idempotency + expected versions ───


class TestMapConflictIdempotency:
    def test_edit_map_replay_after_restart_returns_full_result(self, service, store):
        progress = _with_map_and_sources(_progress())
        first = service.edit_map(
            progress,
            nodes=["kp1", "kp2"],
            edges=[{"from": "kp1", "to": "kp2"}],
            priorities={"kp2": 1},
            expected_map_version=1,
            request_id="e1",
            actor_id="owner",
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = service.edit_map(
            reloaded,
            nodes=["kp1", "kp2"],
            edges=[{"from": "kp1", "to": "kp2"}],
            priorities={"kp2": 1},
            expected_map_version=1,
            request_id="e1",
            actor_id="owner",
        )
        assert second["replayed"] is True
        assert second["map_version"] == first["map_version"] == 2
        assert second["map_version_id"] == first["map_version_id"]
        assert second["nodes"] == first["nodes"]
        assert len(reloaded.map_versions) == 2  # no third version created

    def test_edit_map_same_key_different_payload_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        service.edit_map(
            progress,
            nodes=["kp1"],
            edges=[],
            priorities={},
            expected_map_version=1,
            request_id="e1",
            actor_id="owner",
        )
        with pytest.raises(IdempotencyConflictError):
            service.edit_map(
                progress,
                nodes=["kp2"],
                edges=[],
                priorities={},
                expected_map_version=1,
                request_id="e1",
                actor_id="owner",
            )

    def test_confirm_map_replay_after_restart_returns_full_result(self, service, store):
        progress = _with_map_and_sources(_progress())
        first = service.confirm_map(
            progress,
            expected_map_version=1,
            source_snapshot_ids=["s1"],
            actor_id="owner",
            request_id="c1",
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = service.confirm_map(
            reloaded,
            expected_map_version=1,
            source_snapshot_ids=["s1"],
            actor_id="owner",
            request_id="c1",
        )
        assert second["replayed"] is True
        assert second["map_version"] == first["map_version"] == 2

    def test_confirm_map_none_then_empty_sources_same_key_conflicts(self, service, store):
        # ``None`` preserves the current source set (no-op) while ``[]``
        # explicitly clears it (appending/invalidating): reusing one request_id
        # across those two payloads must conflict, never replay the None result.
        progress = _with_map_and_sources(_progress())
        _start(service, progress)
        first = service.confirm_map(
            progress,
            expected_map_version=1,
            source_snapshot_ids=None,
            actor_id="owner",
            request_id="c-none-empty",
        )
        assert first["map_version"] == 1  # None is a no-op, nothing appended
        with pytest.raises(IdempotencyConflictError):
            service.confirm_map(
                progress,
                expected_map_version=1,
                source_snapshot_ids=[],
                actor_id="owner",
                request_id="c-none-empty",
            )
        assert len(progress.map_versions) == 1  # nothing was mutated

    def test_confirm_map_empty_then_none_sources_same_key_conflicts(self, service, store):
        progress = _with_map_and_sources(_progress())
        first = service.confirm_map(
            progress,
            expected_map_version=1,
            source_snapshot_ids=[],
            actor_id="owner",
            request_id="c-empty-none",
        )
        assert first["map_version"] == 2  # [] cleared the source set
        assert first["source_snapshot_ids"] == []
        with pytest.raises(IdempotencyConflictError):
            service.confirm_map(
                progress,
                expected_map_version=1,
                source_snapshot_ids=None,
                actor_id="owner",
                request_id="c-empty-none",
            )

    def test_resolve_conflict_replay_after_restart_returns_full_result(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        first = service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="r1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = service.resolve_conflict(
            reloaded,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="r1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        assert second["replayed"] is True
        assert second["conflict_version"] == first["conflict_version"] == 2
        assert second["map_version_id"] == first["map_version_id"]
        assert len(reloaded.source_conflicts) == 2  # no third revision

    def test_resolve_conflict_same_key_different_payload_conflicts(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="r1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        with pytest.raises(IdempotencyConflictError):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s2",
                resolution_note="other",
                actor_id="owner",
                request_id="r1",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_resolve_conflict_same_key_different_conflict_conflicts(self, service, store):
        # The same accepted snapshot + note must not replay across two DIFFERENT
        # conflicts: conflict_id is a semantic discriminator of the payload.
        progress = _with_two_conflicts(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="r-conflict",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        with pytest.raises(IdempotencyConflictError):
            service.resolve_conflict(
                progress,
                conflict_id="c2",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="r-conflict",
                expected_conflict_version=1,
                expected_map_version=2,  # current map version after c1 resolved
            )
        # c2 is untouched: it is still the original OPEN v1 revision.
        c2 = max((c for c in progress.source_conflicts if c.id == "c2"), key=lambda c: c.version)
        assert c2.version == 1
        assert c2.status == ConflictStatus.OPEN

    def test_reopen_replay_after_restart(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="res-reopen",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        first = service.reopen_conflict(
            progress,
            conflict_id="c1",
            actor_id="owner",
            request_id="rr",
            expected_conflict_version=2,
            expected_map_version=2,
        )
        service.save(progress)
        reloaded = service.load(progress.book_id)
        second = service.reopen_conflict(
            reloaded,
            conflict_id="c1",
            actor_id="owner",
            request_id="rr",
            expected_conflict_version=2,
            expected_map_version=2,
        )
        assert second["replayed"] is True
        assert second["conflict_version"] == first["conflict_version"] == 3

    def test_resolve_stale_conflict_version_conflicts(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(StaleVersionError):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="res-stale-conflict",
                expected_conflict_version=5,
                expected_map_version=1,
            )

    def test_resolve_stale_map_version_conflicts(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(StaleVersionError):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="res-stale-map",
                expected_conflict_version=1,
                expected_map_version=9,
            )

    def test_resolve_requires_open(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="res-open-1",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        with pytest.raises(ConflictResolutionError, match="only an OPEN"):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note2",
                actor_id="owner",
                request_id="res-open-2",
                expected_conflict_version=2,
                expected_map_version=2,
            )

    def test_reopen_requires_resolved(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(ConflictResolutionError, match="only a RESOLVED"):
            service.reopen_conflict(
                progress,
                conflict_id="c1",
                actor_id="owner",
                request_id="reopen-resolved",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_resolve_accepted_snapshot_must_be_materialized(self, service, store):
        progress = _with_map_and_sources(_progress())
        # A conflict lists s1/s2 but only a snapshot that no longer exists.
        progress.source_conflicts.append(
            SourceConflict(
                id="c1",
                path_id=progress.book_id,
                knowledge_point_ids=["kp1"],
                claim="disagreement",
                source_snapshot_ids=["s1", "s2"],
                version=1,
                status=ConflictStatus.OPEN,
            )
        )
        # s2 exists; remove s1 so the *listed* ids no longer resolve.
        progress.source_snapshots = [s for s in progress.source_snapshots if s.id != "s1"]
        with pytest.raises(ConflictResolutionError, match="unknown source snapshots"):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s2",
                resolution_note="note",
                actor_id="owner",
                request_id="res-materialized",
                expected_conflict_version=1,
                expected_map_version=1,
            )


# ── Finding 5: the gate reads only the newest conflict revision ───────────


class TestConflictProjection:
    def test_gate_passes_after_resolve(self, service, store):
        from deeptutor.learning.grading import compute_server_gate
        from deeptutor.learning.models import RubricAssessment

        progress = _with_conflict(_with_map_and_sources(_progress()))
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="gate-pass-resolve",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        assessment = RubricAssessment(
            id="ra1", attempt_id=attempt.id, rubric=_passing_rubric(), evidence_ids=evidence_ids
        )
        assert compute_server_gate(progress, attempt, assessment).passed is True

    def test_gate_blocks_after_reopen(self, service, store):
        from deeptutor.learning.grading import compute_server_gate
        from deeptutor.learning.models import RubricAssessment

        progress = _with_conflict(_with_map_and_sources(_progress()))
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="gate-block-resolve",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        service.reopen_conflict(
            progress,
            conflict_id="c1",
            actor_id="owner",
            request_id="gate-block-reopen",
            expected_conflict_version=2,
            expected_map_version=2,
        )
        assessment = RubricAssessment(
            id="ra1", attempt_id=attempt.id, rubric=_passing_rubric(), evidence_ids=evidence_ids
        )
        result = compute_server_gate(progress, attempt, assessment)
        assert result.passed is False
        assert "c1" in result.blocked_by_conflict

    def test_all_conflict_revisions_preserved(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        service.resolve_conflict(
            progress,
            conflict_id="c1",
            accepted_snapshot_id="s1",
            resolution_note="note",
            actor_id="owner",
            request_id="preserve-resolve",
            expected_conflict_version=1,
            expected_map_version=1,
        )
        service.reopen_conflict(
            progress,
            conflict_id="c1",
            actor_id="owner",
            request_id="preserve-reopen",
            expected_conflict_version=2,
            expected_map_version=2,
        )
        assert len(progress.source_conflicts) == 3
        assert [c.version for c in progress.source_conflicts] == [1, 2, 3]
        assert [c.status for c in progress.source_conflicts] == [
            ConflictStatus.OPEN,
            ConflictStatus.RESOLVED,
            ConflictStatus.OPEN,
        ]


# ── Finding 4: a new map invalidates unbound live attempts ────────────────


class TestUnboundAttemptInvalidation:
    def test_new_map_invalidates_unbound_live_attempt(self, store):
        progress = _progress()
        unbound = FeynmanAttempt(
            id="u1",
            knowledge_point_id="kp1",
            status=AttemptStatus.COLLECTING,
            active_chain_id="u1:chain:1",
            map_version_id="",
            source_snapshot_ids=[],
        )
        progress.attempts.append(unbound)
        progress.source_snapshots.extend([SourceSnapshot(id="s1"), SourceSnapshot(id="s2")])
        invalidated = apply_map_version(
            progress,
            KnowledgeMapVersion(
                id="p1:map:1",
                path_id=progress.book_id,
                version=1,
                source_snapshot_ids=["s1", "s2"],
            ),
        )
        assert invalidated == ["u1"]
        assert progress.attempts[0].status == AttemptStatus.INVALIDATED


# ── Final correction: required idempotency keys / concurrency tokens ───────


class TestRequiredIdempotencyKeys:
    def test_record_evidence_missing_event_id_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(FeynmanError, match="event_id"):
            service.record_evidence(
                progress,
                attempt_id=attempt.id,
                kind="explanation",
                event_id="",
                content="x",
                identity=_identity(),
                expected_attempt_version=progress.aggregate_versions.attempt,
            )

    def test_record_evidence_missing_expected_version_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(FeynmanError, match="expected_attempt_version"):
            service.record_evidence(
                progress,
                attempt_id=attempt.id,
                kind="explanation",
                event_id="e1",
                content="x",
                identity=_identity(),
                expected_attempt_version=None,
            )

    def test_finalize_missing_event_id_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        with pytest.raises(FeynmanError, match="event_id"):
            service.finalize(
                progress,
                attempt_id=attempt.id,
                rubric=_passing_rubric(),
                critical_errors=[],
                strengths=[],
                gap_candidates=[],
                evidence_ids=evidence_ids,
                source_citations=[],
                event_id="",
                expected_attempt_version=progress.aggregate_versions.attempt,
            )

    def test_finalize_missing_expected_version_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        with pytest.raises(FeynmanError, match="expected_attempt_version"):
            service.finalize(
                progress,
                attempt_id=attempt.id,
                rubric=_passing_rubric(),
                critical_errors=[],
                strengths=[],
                gap_candidates=[],
                evidence_ids=evidence_ids,
                source_citations=[],
                event_id="fin-x",
                expected_attempt_version=None,
            )

    def test_edit_map_missing_request_id_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(FeynmanError, match="request_id"):
            service.edit_map(
                progress,
                nodes=[],
                edges=[],
                priorities={},
                expected_map_version=1,
                request_id="",
                actor_id="owner",
            )

    def test_confirm_map_missing_request_id_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        with pytest.raises(FeynmanError, match="request_id"):
            service.confirm_map(
                progress,
                expected_map_version=1,
                request_id="",
                actor_id="owner",
            )

    def test_resolve_missing_request_id_rejected(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(FeynmanError, match="request_id"):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_resolve_missing_expected_versions_rejected(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(FeynmanError, match="expected_conflict_version"):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="r",
                expected_conflict_version=None,
                expected_map_version=1,
            )
        with pytest.raises(FeynmanError, match="expected_map_version"):
            service.resolve_conflict(
                progress,
                conflict_id="c1",
                accepted_snapshot_id="s1",
                resolution_note="note",
                actor_id="owner",
                request_id="r",
                expected_conflict_version=1,
                expected_map_version=None,
            )

    def test_reopen_missing_request_id_rejected(self, service, store):
        progress = _with_conflict(_with_map_and_sources(_progress()))
        with pytest.raises(FeynmanError, match="request_id"):
            service.reopen_conflict(
                progress,
                conflict_id="c1",
                actor_id="owner",
                request_id="",
                expected_conflict_version=1,
                expected_map_version=1,
            )

    def test_challenge_missing_request_id_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(FeynmanError, match="request_id"):
            service.create_challenge(
                progress,
                attempt_id=attempt.id,
                mode="reassess_existing",
                request_id="",
                expected_attempt_version=progress.aggregate_versions.attempt,
            )

    def test_challenge_missing_expected_version_rejected(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        with pytest.raises(FeynmanError, match="expected_attempt_version"):
            service.create_challenge(
                progress,
                attempt_id=attempt.id,
                mode="reassess_existing",
                request_id="ch-x",
                expected_attempt_version=None,
            )


class TestConcurrencyTokenAdvancement:
    def test_evidence_advances_token_and_stale_token_rejected_for_new_event(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        before = progress.aggregate_versions.attempt
        first = _record(
            service,
            progress,
            attempt.id,
            kind="explanation",
            event_id="e1",
            content="x",
            expected_attempt_version=before,
        )
        assert first["attempt_version"] == progress.aggregate_versions.attempt
        assert first["attempt_version"] > before
        # A different event reusing the pre-mutation token is stale.
        with pytest.raises(StaleVersionError):
            _record(
                service,
                progress,
                attempt.id,
                kind="probe_question",
                event_id="e2",
                content="Q?",
                expected_attempt_version=before,
            )
        # The post-mutation token works.
        second = _record(
            service,
            progress,
            attempt.id,
            kind="probe_question",
            event_id="e2",
            content="Q?",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        assert second["attempt_version"] > first["attempt_version"]

    def test_finalize_advances_token_and_replays_with_original_token(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        before = progress.aggregate_versions.attempt
        _finalize(
            service,
            progress,
            attempt.id,
            evidence_ids=evidence_ids,
            event_id="fin-1",
            expected_attempt_version=before,
        )
        # A different finalize (new event) with the pre-finalize token is stale.
        with pytest.raises(StaleVersionError):
            _finalize(
                service,
                progress,
                attempt.id,
                evidence_ids=evidence_ids,
                event_id="fin-2",
                expected_attempt_version=before,
            )
        # A committed retry with the ORIGINAL token still replays exactly.
        replayed = _finalize(
            service,
            progress,
            attempt.id,
            evidence_ids=evidence_ids,
            event_id="fin-1",
            expected_attempt_version=before,
        )
        assert replayed["replayed"] is True
        assert len(progress.rubric_assessments) == 1

    def test_challenge_requires_current_token_for_new_request(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_ids = _complete_chain(service, progress, attempt.id)
        _finalize(service, progress, attempt.id, evidence_ids=evidence_ids)
        before = progress.aggregate_versions.attempt
        challenge = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="reassess_existing",
            request_id="ch-1",
            expected_attempt_version=before,
        )
        # A different challenge request reusing the pre-challenge token is stale.
        with pytest.raises(StaleVersionError):
            service.create_challenge(
                progress,
                attempt_id=attempt.id,
                mode="reassess_existing",
                request_id="ch-2",
                expected_attempt_version=before,
            )
        # Once the pending challenge is completed, a distinct request with the
        # current token passes the version check and is accepted.
        _finalize(
            service, progress, attempt.id, evidence_ids=evidence_ids, challenge_id=challenge.id
        )
        second = service.create_challenge(
            progress,
            attempt_id=attempt.id,
            mode="collect_new_evidence",
            request_id="ch-3",
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        assert second.id != challenge.id


class TestPreFingerprintEvidenceRow:
    def test_same_text_different_kind_cannot_replay_without_fingerprint(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_id = f"{attempt.id}:ev:e1"
        # A persisted pre-fingerprint evidence row (history payload has no
        # ``request_fingerprint``) — exactly what older writers left behind.
        progress.evidence_items.append(
            EvidenceItem(
                id=evidence_id,
                attempt_id=attempt.id,
                chain_id=attempt.active_chain_id,
                kind=EvidenceKind.EXPLANATION,
                content_snapshot="same",
                content_hash=_content_hash("same"),
                created_at=START,
            )
        )
        append_history(
            progress,
            "evidence_recorded",
            aggregate="evidence",
            summary="legacy evidence",
            payload={
                "evidence_id": evidence_id,
                "attempt_id": attempt.id,
                "chain_id": attempt.active_chain_id,
                "kind": "explanation",
                "content_hash": _content_hash("same"),
                # no request_fingerprint
            },
        )
        # Same text under a different kind must NOT replay via content-only
        # equality — it fails closed on the missing fingerprint (finding 2).
        with pytest.raises(EvidenceConflictError, match="fingerprint"):
            _record(
                service,
                progress,
                attempt.id,
                kind="probe_question",
                event_id="e1",
                content="same",
            )

    def test_same_text_different_binding_cannot_replay_without_fingerprint(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt = _start(service, progress)
        evidence_id = f"{attempt.id}:ev:e1"
        progress.evidence_items.append(
            EvidenceItem(
                id=evidence_id,
                attempt_id=attempt.id,
                chain_id=attempt.active_chain_id,
                kind=EvidenceKind.EXPLANATION,
                content_snapshot="same",
                content_hash=_content_hash("same"),
                created_at=START,
            )
        )
        append_history(
            progress,
            "evidence_recorded",
            aggregate="evidence",
            summary="legacy evidence",
            payload={
                "evidence_id": evidence_id,
                "attempt_id": attempt.id,
                "chain_id": attempt.active_chain_id,
                "kind": "explanation",
                "content_hash": _content_hash("same"),
            },
        )
        # Same text, same kind, different trusted identity still cannot replay.
        with pytest.raises(EvidenceConflictError, match="fingerprint"):
            _record(
                service,
                progress,
                attempt.id,
                kind="explanation",
                event_id="e1",
                content="same",
                identity=_identity(session_id="other"),
            )


class TestEditMapReportsThisOperationOnly:
    def test_edit_map_reports_only_newly_invalidated_attempts(self, service, store):
        progress = _with_map_and_sources(_progress())
        attempt1 = _start(service, progress)
        first = service.edit_map(
            progress,
            nodes=["kp2"],
            edges=[],
            priorities={},
            expected_map_version=1,
            request_id="edit-1",
            actor_id="owner",
        )
        assert first["invalidated_attempt_ids"] == [attempt1.id]
        # A second edit invalidates nothing new; the historical invalidation
        # must NOT be reported again (finding 4).
        second = service.edit_map(
            progress,
            nodes=["kp3"],
            edges=[],
            priorities={},
            expected_map_version=2,
            request_id="edit-2",
            actor_id="owner",
        )
        assert second["invalidated_attempt_ids"] == []
        assert progress.attempts[0].status == AttemptStatus.INVALIDATED


class TestConfirmMapWithoutCurrentMap:
    def test_confirm_map_no_current_map_raises_stable_error(self, service, store):
        progress = _progress()  # no map versions / no source basis
        with pytest.raises(FeynmanError, match="no confirmed map"):
            service.confirm_map(
                progress,
                expected_map_version=0,
                request_id="confirm-none",
                actor_id="owner",
            )
