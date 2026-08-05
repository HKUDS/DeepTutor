"""Explicit cross-model challenge selection tests (MOD-03, §7.3.1 / §9.3).

A challenge can explicitly resolve a *different* configured evaluator snapshot.
The resulting invocation and assessment are linked through ``challenge_id`` /
``supersedes_assessment_id`` / ``model_invocation_id``; the original assessment,
evidence, evaluator snapshot and invocation records stay append-only.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.models import (
    AttemptStatus,
    ChallengeMode,
    ChallengeRecord,
    ChallengeStatus,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    ModelInvocationPurpose,
    ModelInvocationStatus,
    RubricAssessment,
)
from deeptutor.learning.storage import LearningStore, find_model_invocation
from deeptutor.services.model_selection import (
    ModelInvocationRecorder,
    ModelSelector,
    attach_evaluation_identity,
    resolve_challenge_evaluator,
)
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.selector import ResolvedModelSnapshot

from . import _fixtures as fx


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


def _original_snapshot() -> ResolvedModelSnapshot:
    return ModelSelector(catalog=fx.catalog()).resolve_evaluator(
        LLMSelection(profile_id="p1", model_id="m1")
    )


def _cross_snapshot() -> ResolvedModelSnapshot:
    return ModelSelector(catalog=fx.catalog()).resolve_evaluator(
        LLMSelection(profile_id="p2", model_id="m3")
    )


def _progress_with_assessment(store: LearningStore, book_id: str = "b1"):
    """Progress with an assessed attempt carrying the original evaluator."""
    progress = fx.progress(book_id)
    progress.attempts.append(
        FeynmanAttempt(
            id="a1",
            knowledge_point_id="kp1",
            status=AttemptStatus.ASSESSED,
            active_chain_id="chain-1",
            evaluator_snapshot=_original_snapshot().to_evaluator_snapshot(rubric_version="v1"),
        )
    )
    progress.evidence_items.append(
        EvidenceItem(id="ev1", attempt_id="a1", chain_id="chain-1", kind=EvidenceKind.EXPLANATION)
    )
    # The original evaluation invocation is itself an append-only audit record.
    recorder = ModelInvocationRecorder()
    original_invocation = recorder.start(
        progress,
        purpose=ModelInvocationPurpose.EVALUATION,
        snapshot=_original_snapshot(),
        attempt_id="a1",
    )
    recorder.finish(
        progress,
        original_invocation.id,
        status=ModelInvocationStatus.COMPLETED,
        reported_model="gpt-4o-mini",
    )
    progress.rubric_assessments.append(
        RubricAssessment(
            id="ra1",
            attempt_id="a1",
            revision=1,
            assessment_sequence=1,
            evidence_ids=["ev1"],
            evaluator_snapshot=_original_snapshot().to_evaluator_snapshot(rubric_version="v1"),
            model_invocation_id=original_invocation.id,
        )
    )
    store.save(progress)
    return progress


class TestCrossModelChallenge:
    def test_challenge_resolves_different_configured_evaluator(self):
        _, snapshot = resolve_challenge_evaluator(
            challenge_evaluator_selection=LLMSelection(profile_id="p2", model_id="m3"),
            catalog=fx.catalog(),
            rubric_version="v1",
        )
        # Different provider/model/protocol than the original evaluator.
        assert snapshot.profile_id == "p2"
        assert snapshot.resolved_provider == "anthropic"
        assert snapshot.resolved_model == "claude-3-7-sonnet"
        assert snapshot.resolved_api_protocol == "anthropic_messages"
        assert snapshot.resolved_model != _original_snapshot().resolved_model

    def test_challenge_links_invocation_and_assessment(self, store):
        progress = _progress_with_assessment(store)
        original_assessment = progress.rubric_assessments[0]
        original_snapshot_json = original_assessment.evaluator_snapshot.model_dump(mode="json")

        # A learner challenges ra1 and explicitly picks a different evaluator.
        challenge = ChallengeRecord(
            id="ch1",
            knowledge_point_id="kp1",
            source_attempt_id="a1",
            source_assessment_id="ra1",
            mode=ChallengeMode.REASSESS_EXISTING,
            requested_evaluator_snapshot=_cross_snapshot().to_evaluator_snapshot(
                rubric_version="v1"
            ),
            status=ChallengeStatus.COMPLETED,
            result_attempt_id="a1",
            result_assessment_id="ra2",
            completed_at=1000.0,
        )
        progress.challenge_records.append(challenge)

        # New invocation for the cross-model evaluator on the same attempt.
        recorder = ModelInvocationRecorder()
        cross = _cross_snapshot()
        record = recorder.start(
            progress,
            purpose=ModelInvocationPurpose.EVALUATION,
            snapshot=cross,
            attempt_id="a1",
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="claude-3-7-sonnet",
            reported_version="2026-06",
        )

        # Appended revision is linked through challenge/supersedes/invocation.
        assessment = RubricAssessment(
            id="ra2",
            attempt_id="a1",
            revision=2,
            assessment_sequence=2,
            evidence_ids=["ev1"],
            supersedes_assessment_id="ra1",
            challenge_id="ch1",
        )
        attach_evaluation_identity(
            assessment,
            snapshot=cross.to_evaluator_snapshot(rubric_version="v1"),
            invocation_id=record.id,
        )
        progress.rubric_assessments.append(assessment)
        store.save(progress)

        loaded = store.load("b1")
        ra1 = next(a for a in loaded.rubric_assessments if a.id == "ra1")
        ra2 = next(a for a in loaded.rubric_assessments if a.id == "ra2")
        inv = find_model_invocation(loaded, record.id)

        assert ra2.supersedes_assessment_id == "ra1"
        assert ra2.challenge_id == "ch1"
        assert ra2.model_invocation_id == record.id
        assert ra2.evaluator_snapshot.resolved_model == "claude-3-7-sonnet"
        assert ra2.evaluator_snapshot.resolved_api_protocol == "anthropic_messages"
        assert inv.attempt_id == "a1"
        assert inv.resolved_provider == "anthropic"
        assert inv.provider_reported_model == "claude-3-7-sonnet"

        # Original assessment, evidence and snapshot are append-only: unchanged.
        assert ra1.model_dump(mode="json")["evaluator_snapshot"] == original_snapshot_json
        original_invocation_id = original_assessment.model_invocation_id
        assert ra1.model_invocation_id == original_invocation_id
        assert ra1.model_invocation_id != record.id
        assert ra1.supersedes_assessment_id == ""
        assert {e.id for e in loaded.evidence_items} == {"ev1"}
        assert len(loaded.rubric_assessments) == 2
        # original + cross-model invocation ids, each with pending+terminal revisions.
        assert {r.id for r in loaded.model_invocations} == {original_invocation_id, record.id}
        assert len(loaded.model_invocations) == 4

    def test_collect_new_evidence_challenge_creates_new_attempt_link(self, store):
        progress = _progress_with_assessment(store)
        recorder = ModelInvocationRecorder()
        cross = _cross_snapshot()
        record = recorder.start(
            progress,
            purpose=ModelInvocationPurpose.EVALUATION,
            snapshot=cross,
            attempt_id="a2",
        )
        recorder.finish(progress, record.id, status=ModelInvocationStatus.COMPLETED)

        progress.attempts.append(
            FeynmanAttempt(
                id="a2",
                knowledge_point_id="kp1",
                status=AttemptStatus.ASSESSED,
                supersedes_attempt_id="a1",
                active_chain_id="chain-2",
            )
        )
        assessment = RubricAssessment(
            id="ra2",
            attempt_id="a2",
            revision=1,
            assessment_sequence=2,
            supersedes_assessment_id="ra1",
        )
        attach_evaluation_identity(
            assessment,
            snapshot=cross.to_evaluator_snapshot(rubric_version="v1"),
            invocation_id=record.id,
        )
        progress.rubric_assessments.append(assessment)
        store.save(progress)

        loaded = store.load("b1")
        new_attempt = next(a for a in loaded.attempts if a.id == "a2")
        assert new_attempt.supersedes_attempt_id == "a1"
        ra2 = next(a for a in loaded.rubric_assessments if a.id == "ra2")
        assert ra2.attempt_id == "a2"
        assert ra2.supersedes_assessment_id == "ra1"
        assert ra2.model_invocation_id == record.id
