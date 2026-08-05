"""Server-derived eligibility and stale-evidence reconciliation (KB-02).

The create/ensure operation never accepts an arbitrary assessment id — it
derives the latest valid passing stable assessment from the server projection
(§6.6, requirement 2). A card is only eligible when the current projection is
``stable_mastery``, ``latest_assessment_id`` resolves to a passing assessment
whose attempt is not invalidated, and a nonempty frozen evaluator snapshot
exists. Provisional mastery, ``needs_revision``, stale/older assessments,
cross-path/cross-user input and missing snapshots all fail closed.

This module is a pure read/reconcile helper over a :class:`LearningProgress`;
mutation happens in the service/worker under the store's CAS.
"""

from __future__ import annotations

import time
from typing import Any

from deeptutor.learning.models import (
    STALEABLE_CARD_STATUSES,
    AttemptStatus,
    EvaluatorSnapshot,
    FeynmanAttempt,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    LearningProgress,
    MasteryState,
    RubricAssessment,
)


def is_frozen_evaluator_snapshot(snapshot: EvaluatorSnapshot | None) -> bool:
    """True when *snapshot* is a nonempty frozen evaluator identity.

    "Nonempty" means it carries a resolved profile and model — an empty/legacy
    snapshot with no model is not a usable generation basis and fails closed
    (requirement 2/3).
    """
    if snapshot is None:
        return False
    return bool(getattr(snapshot, "profile_id", "")) and bool(
        getattr(snapshot, "resolved_model", "")
    )


def latest_valid_stable_assessment(
    progress: LearningProgress, kp_id: str
) -> tuple[FeynmanAttempt, RubricAssessment] | None:
    """The ``(attempt, assessment)`` the current stable projection rests on.

    Returns ``None`` (fail closed) unless all of the following hold:

    * the projection's mastery is ``stable_mastery``;
    * ``projection.latest_assessment_id`` resolves to a real assessment;
    * that assessment passed the server gate;
    * its attempt is not invalidated;
    * a nonempty frozen evaluator snapshot exists on the assessment/attempt.
    """
    projection = progress.projections.get(kp_id)
    if projection is None or projection.mastery_state != MasteryState.STABLE_MASTERY:
        return None
    latest_id = projection.latest_assessment_id
    if not latest_id:
        return None
    assessment = next((a for a in progress.rubric_assessments if a.id == latest_id), None)
    if assessment is None:
        return None
    if not assessment.server_gate_result.passed:
        return None
    attempt = next((a for a in progress.attempts if a.id == assessment.attempt_id), None)
    if attempt is None or attempt.status == AttemptStatus.INVALIDATED:
        return None
    snapshot = assessment.evaluator_snapshot or attempt.evaluator_snapshot
    if not is_frozen_evaluator_snapshot(snapshot):
        return None
    return attempt, assessment


def frozen_evaluator_snapshot_for(
    attempt: FeynmanAttempt, assessment: RubricAssessment
) -> EvaluatorSnapshot | None:
    """The frozen evaluator snapshot to copy for generation (§6.6/§7.9.1).

    Prefers the assessment's snapshot (the one recorded at evaluation time) and
    falls back to the attempt's frozen snapshot. Returns ``None`` when neither
    is a nonempty frozen identity.
    """
    snapshot = assessment.evaluator_snapshot or attempt.evaluator_snapshot
    return snapshot if is_frozen_evaluator_snapshot(snapshot) else None


def occupying_card(progress: LearningProgress, kp_id: str) -> KnowledgeCardRecord | None:
    """The card currently occupying ``kp_id``'s slot, if any (§7.9).

    ``stale_evidence``/``discarded``/``retracted`` cards do not occupy, so a
    later genuinely newer stable assessment may create a new card (§6.6).
    """
    for card in progress.knowledge_cards:
        if card.knowledge_point_id == kp_id and card.occupies_slot:
            return card
    return None


def max_retracted_sequence(progress: LearningProgress, kp_id: str) -> int:
    """The largest stable assessment sequence among retracted cards for *kp_id*.

    A new card's stable assessment sequence must be strictly greater than this
    so a retracted card's old stable evidence can never be reused (§6.6/§8.5).
    """
    return max(
        (
            card.stable_assessment_sequence
            for card in progress.knowledge_cards
            if card.knowledge_point_id == kp_id and card.status == KnowledgeCardStatus.RETRACTED
        ),
        default=0,
    )


def stable_assessment_is_current(progress: LearningProgress, card: KnowledgeCardRecord) -> bool:
    """True when *card*'s bound stable assessment is still the projection's
    latest valid stable assessment for its knowledge point.

    Used by the worker's apply guard and by the retry/eligibility checks: if the
    evidence was overturned (later failed review/challenge, or the projection no
    longer stable), the card's basis is stale and must not be published or
    regenerated (§6.6, requirement 7).
    """
    if not card.stable_assessment_id:
        return False
    current = latest_valid_stable_assessment(progress, card.knowledge_point_id)
    if current is None:
        return False
    _, assessment = current
    return assessment.id == card.stable_assessment_id


def reconcile_stale_evidence(progress: LearningProgress, *, now: float | None = None) -> list[str]:
    """Atomically stale every unpublished occupying card whose evidence is no
    longer current; returns the ids of cards newly marked ``stale_evidence``.

    A card is stale when its bound stable assessment is no longer the
    projection's latest valid stable assessment, or mastery is no longer stable.
    Staling preserves the card, its attempts, blobs and provenance for
    viewing/discard but disables generation/edit/publication preparation
    (§6.6, §15). The reconcile is a pure mutation of the in-memory progress and
    is persisted by the caller's single CAS save.
    """
    moment = now if now is not None else time.time()
    stale_ids: list[str] = []
    for card in progress.knowledge_cards:
        if card.status not in STALEABLE_CARD_STATUSES:
            continue
        current = latest_valid_stable_assessment(progress, card.knowledge_point_id)
        if current is None:
            stale_ids.append(card.id)
            continue
        _, assessment = current
        if assessment.id != card.stable_assessment_id:
            stale_ids.append(card.id)
    for card in progress.knowledge_cards:
        if card.id in stale_ids:
            card.status = KnowledgeCardStatus.STALE_EVIDENCE
            card.stale_at = card.stale_at or moment
            card.updated_at = moment
            card.version += 1
    return stale_ids


def eligibility_result(progress: LearningProgress, kp_id: str) -> dict[str, Any]:
    """A secret-free, API-ready eligibility view for one knowledge point."""
    current = latest_valid_stable_assessment(progress, kp_id)
    projection = progress.projections.get(kp_id)
    retracted = max_retracted_sequence(progress, kp_id)
    eligible = current is not None
    sequence_ok = current is not None and current[1].assessment_sequence > retracted
    return {
        "eligible": bool(eligible and sequence_ok),
        "mastery_state": projection.mastery_state.value if projection else "",
        "latest_assessment_id": projection.latest_assessment_id if projection else "",
        "stable_assessment_sequence": current[1].assessment_sequence if current else 0,
        "retracted_sequence": retracted,
        "sequence_ok": bool(sequence_ok),
    }


__all__ = [
    "eligibility_result",
    "frozen_evaluator_snapshot_for",
    "is_frozen_evaluator_snapshot",
    "latest_valid_stable_assessment",
    "max_retracted_sequence",
    "occupying_card",
    "reconcile_stale_evidence",
    "stable_assessment_is_current",
]
