"""Shared deterministic builders for the KB-02 knowledge-card tests.

Not a test module itself (no ``test_`` prefix); imported by the knowledge-card
model/service/worker tests. Builds a stable-mastery :class:`LearningProgress`
with the real integrated contracts (LRN-02 projection, MOD-03 evaluator
snapshot, LRN-01 append-only aggregates) and media fixtures for artifact
reference tests.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.learning.models import (
    AttemptCycleType,
    AttemptStatus,
    EvaluatorSnapshot,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    KnowledgePoint,
    KnowledgeStateProjection,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    MasteryState,
    ReviewState,
    RubricAssessment,
    RubricScores,
    ServerGateResult,
    SourceCitation,
    SourceSnapshot,
)
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import GeneratedArtifact
from deeptutor.services.media.store import MediaStore

START = 1_000_000.0
DAY = 86400.0


def evaluator_snapshot(
    *,
    profile_id: str = "p1",
    model: str = "gpt-4o-mini",
) -> EvaluatorSnapshot:
    """A nonempty frozen evaluator snapshot (MOD-03 shape, secret-free)."""
    return EvaluatorSnapshot(
        profile_id=profile_id,
        profile_name="Eval",
        profile_revision="r1",
        requested_provider="openai",
        requested_api_protocol="openai_responses",
        requested_model=model,
        resolved_provider="openai",
        resolved_api_protocol="openai_responses",
        resolved_model=model,
        auto_resolution_reason="auto:default",
        # Matches the real ``tests.services.model_selection._fixtures.catalog()``
        # base_url ``https://api.example.com/v1`` so a real executor resolving
        # against that catalog passes the endpoint-fingerprint check.
        base_url_fingerprint="74d0333a4063c6e8",
        strict_protocol=True,
        prompt_version="v1",
        rubric_version="rv1",
        created_at=START + 10,
    )


def stable_mastery_progress(
    book_id: str = "b1",
    *,
    kp_id: str = "kp1",
    attempt_id: str = "a1",
    assessment_id: str = "ra1",
    assessment_sequence: int = 1,
    snapshot: EvaluatorSnapshot | None = None,
    passed: bool = True,
    retracted_sequence: int = 0,
) -> tuple[LearningProgress, FeynmanAttempt, RubricAssessment]:
    """A progress with one knowledge point in stable mastery.

    The delayed-reteach attempt carries the frozen evaluator snapshot and a
    passing assessment; the projection is ``stable_mastery`` with
    ``latest_assessment_id`` pointing at it. ``retracted_sequence`` optionally
    adds an older retracted card so the sequence-greater rule can be tested.
    """
    progress = LearningProgress(book_id=book_id)
    progress.modules = [
        LearningModule(
            id="m1",
            name="Module 1",
            order=0,
            knowledge_points=[
                KnowledgePoint(
                    id=kp_id, name=kp_id.upper(), type=KnowledgeType.CONCEPT, module_id="m1"
                )
            ],
        )
    ]
    progress.knowledge_types[kp_id] = KnowledgeType.CONCEPT
    progress.source_snapshots.append(
        SourceSnapshot(
            id="s1", title="Source 1", content_hash="src-hash-1", citation_anchors=["p.1"]
        )
    )
    snap = snapshot or evaluator_snapshot()
    attempt = FeynmanAttempt(
        id=attempt_id,
        knowledge_point_id=kp_id,
        cycle_type=AttemptCycleType.DELAYED_RETEACH,
        status=AttemptStatus.ASSESSED,
        source_snapshot_ids=["s1"],
        evaluator_snapshot=snap,
        closed_at=START + 100,
        created_at=START + 100,
        updated_at=START + 100,
    )
    progress.attempts.append(attempt)
    evidence = EvidenceItem(
        id="ev1",
        attempt_id=attempt_id,
        chain_id="chain-1",
        kind=EvidenceKind.EXPLANATION,
        content_snapshot="Learner's plain-language explanation of the idea.",
        content_hash="evidence-hash-1",
        source_citations=[SourceCitation(source_snapshot_id="s1", anchor="p.1")],
        created_at=START + 101,
    )
    progress.evidence_items.append(evidence)
    assessment = RubricAssessment(
        id=assessment_id,
        attempt_id=attempt_id,
        revision=1,
        assessment_sequence=assessment_sequence,
        rubric=RubricScores(correctness=2, completeness=1, causal_clarity=1, transfer=2),
        critical_errors=[],
        evidence_ids=["ev1"],
        source_citations=[SourceCitation(source_snapshot_id="s1", anchor="p.1")],
        evaluator_snapshot=snap,
        model_invocation_id="inv-1",
        server_gate_result=ServerGateResult(passed=passed, reasons=["delayed reteach pass"]),
        created_at=START + 102,
    )
    progress.rubric_assessments.append(assessment)
    progress.projections[kp_id] = KnowledgeStateProjection(
        knowledge_point_id=kp_id,
        mastery_state=MasteryState.STABLE_MASTERY if passed else MasteryState.NEEDS_REVISION,
        review_state=ReviewState.SCHEDULED,
        latest_assessment_id=assessment_id if passed else "",
        stable_since=START + 100 if passed else None,
        next_review_at=START + 100 + 30 * DAY,
        updated_at=START + 102,
    )
    if retracted_sequence:
        from deeptutor.learning.models import KnowledgeCardRecord, KnowledgeCardStatus

        progress.knowledge_cards.append(
            KnowledgeCardRecord(
                id="old-card",
                user_id="owner",
                path_id=book_id,
                knowledge_point_id=kp_id,
                stable_assessment_id="old-ra",
                stable_assessment_sequence=retracted_sequence,
                status=KnowledgeCardStatus.RETRACTED,
                retracted_at=START,
            )
        )
    return progress, attempt, assessment


def media_store_with_artifact(
    root: Path,
    *,
    user_id: str = "owner",
    artifact_id: str = "art1",
) -> tuple[MediaStore, GeneratedArtifact]:
    """A MediaStore with one persistent same-user GeneratedArtifact."""
    store = MediaStore(root=root / "media", limits=MediaLimits())
    artifact = GeneratedArtifact(
        id=artifact_id,
        user_id=user_id,
        sha256="a" * 64,
        mime_type="image/png",
        size_bytes=10,
        original_path=f"originals/aa/{'a' * 64}.png",
    )
    store.save_artifact(artifact, check_quota=False)
    return store, artifact
