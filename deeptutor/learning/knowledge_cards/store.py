"""Durable helpers over a :class:`LearningProgress` for knowledge cards (KB-02).

Pure lookups, append-only attempt management and the frozen generation-input
projection. Mutation stays in the service/worker; the store's CAS guarantees a
single atomic save per operation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardInputValidationError,
    KnowledgeCardNotFoundError,
)
from deeptutor.learning.models import (
    TERMINAL_GENERATION_ATTEMPT_STATUSES,
    AttemptStatus,
    FeynmanAttempt,
    KnowledgeCardGenerationAttempt,
    KnowledgeCardRecord,
    LearningProgress,
    RubricAssessment,
    SourceSnapshot,
)


def find_card(progress: LearningProgress, card_id: str) -> KnowledgeCardRecord | None:
    return next((card for card in progress.knowledge_cards if card.id == card_id), None)


def require_card(progress: LearningProgress, card_id: str) -> KnowledgeCardRecord:
    card = find_card(progress, card_id)
    if card is None:
        raise KnowledgeCardNotFoundError(f"knowledge card {card_id!r} not found")
    return card


def find_generation_attempt(
    progress: LearningProgress, attempt_id: str
) -> KnowledgeCardGenerationAttempt | None:
    return next(
        (
            attempt
            for attempt in progress.knowledge_card_generation_attempts
            if attempt.id == attempt_id
        ),
        None,
    )


def require_generation_attempt(
    progress: LearningProgress, attempt_id: str
) -> KnowledgeCardGenerationAttempt:
    attempt = find_generation_attempt(progress, attempt_id)
    if attempt is None:
        raise KnowledgeCardNotFoundError(f"generation attempt {attempt_id!r} not found")
    return attempt


def attempts_for_card(
    progress: LearningProgress, card_id: str
) -> list[KnowledgeCardGenerationAttempt]:
    return [
        attempt
        for attempt in progress.knowledge_card_generation_attempts
        if attempt.card_id == card_id
    ]


def latest_attempt_for_card(
    progress: LearningProgress, card_id: str
) -> KnowledgeCardGenerationAttempt | None:
    attempts = attempts_for_card(progress, card_id)
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda attempt: (attempt.generation_attempt_no, attempt.created_at, attempt.id),
    )


def nonterminal_attempt_for_input(
    progress: LearningProgress, card_id: str, input_card_revision: int
) -> KnowledgeCardGenerationAttempt | None:
    """A nonterminal attempt for ``(card_id, input_card_revision)``, if any.

    Single-flight (§7.9.1): at most one nonterminal generation attempt may exist
    per ``card_id + input_card_revision``.
    """
    for attempt in progress.knowledge_card_generation_attempts:
        if (
            attempt.card_id == card_id
            and attempt.input_card_revision == input_card_revision
            and attempt.status not in TERMINAL_GENERATION_ATTEMPT_STATUSES
        ):
            return attempt
    return None


def has_active_attempt(progress: LearningProgress, card_id: str) -> bool:
    """True when the card has any nonterminal (queued/running) attempt."""
    return any(
        attempt.card_id == card_id and attempt.status not in TERMINAL_GENERATION_ATTEMPT_STATUSES
        for attempt in progress.knowledge_card_generation_attempts
    )


def next_generation_attempt_no(progress: LearningProgress, card_id: str) -> int:
    attempts = attempts_for_card(progress, card_id)
    if not attempts:
        return 1
    return max(attempt.generation_attempt_no for attempt in attempts) + 1


def content_hash(title: str, body: str) -> str:
    """Deterministic content hash of the confirmed title/body."""
    canonical = f"{title}\n{body}".strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── frozen generation input (§6.6, requirement 3) ─────────────────────────


def _evidence_snapshot(
    progress: LearningProgress, assessment: RubricAssessment
) -> list[dict[str, Any]]:
    """Assessment-bound evidence, validated to exist and belong to the attempt."""
    attempt_id = assessment.attempt_id
    by_id = {item.id: item for item in progress.evidence_items}
    out: list[dict[str, Any]] = []
    for evidence_id in assessment.evidence_ids:
        item = by_id.get(evidence_id)
        if item is None:
            raise KnowledgeCardInputValidationError(
                f"evidence {evidence_id!r} referenced by assessment {assessment.id!r} "
                "does not exist"
            )
        if item.attempt_id != attempt_id:
            raise KnowledgeCardInputValidationError(
                f"evidence {evidence_id!r} belongs to attempt {item.attempt_id!r}, "
                f"not {attempt_id!r}"
            )
        out.append(
            {
                "id": item.id,
                "kind": item.kind.value,
                "content": item.content_snapshot,
                "content_hash": item.content_hash,
                "input_mode": item.input_mode.value,
                "transcript_confirmed": item.transcript_confirmed,
                "citations": [citation.model_dump() for citation in item.source_citations],
            }
        )
    return out


def _source_snapshot_refs(
    progress: LearningProgress,
    assessment: RubricAssessment,
    attempt: FeynmanAttempt,
) -> list[dict[str, Any]]:
    """Assessment-bound source snapshots, validated to exist and be frozen."""
    frozen = set(attempt.source_snapshot_ids)
    by_id: dict[str, SourceSnapshot] = {
        snapshot.id: snapshot for snapshot in progress.source_snapshots
    }
    ids: list[str] = []
    for citation in assessment.source_citations:
        if citation.source_snapshot_id not in ids:
            ids.append(citation.source_snapshot_id)
    for snapshot_id in ids:
        if snapshot_id not in frozen:
            raise KnowledgeCardInputValidationError(
                f"source snapshot {snapshot_id!r} cited by assessment {assessment.id!r} "
                "is not frozen on the attempt"
            )
        if snapshot_id not in by_id:
            raise KnowledgeCardInputValidationError(
                f"source snapshot {snapshot_id!r} is not a materialized snapshot"
            )
    return [
        {
            "id": by_id[sid].id,
            "source_type": by_id[sid].source_type.value,
            "title": by_id[sid].title,
            "locator": by_id[sid].locator,
            "content_hash": by_id[sid].content_hash,
            "citation_anchors": list(by_id[sid].citation_anchors),
        }
        for sid in ids
    ]


def frozen_input_fingerprint(
    progress: LearningProgress,
    card: KnowledgeCardRecord,
    assessment: RubricAssessment,
    *,
    artifact_ids: list[str] | None = None,
) -> str:
    """Deterministic SHA-256 of the frozen generation-input reference set.

    Only identities and content hashes participate — never raw conversation,
    provider prompt/response, auth data or base64. The fingerprint changes when
    any frozen reference set changes, so an attempt's ``input_hash`` pins the
    exact generation basis and a retry reuses the same hash (§7.9.1).
    """
    evidence_refs = sorted(
        {
            (item["id"], item["content_hash"] or "")
            for item in _evidence_snapshot(progress, assessment)
        }
    )
    source_refs = sorted(
        {
            (item["id"], item["content_hash"] or "")
            for item in _source_snapshot_refs(
                progress, assessment, _assessment_attempt(progress, assessment)
            )
        }
    )
    artifact_refs = sorted(set(artifact_ids if artifact_ids is not None else card.artifact_ids))
    payload = {
        "knowledge_point_id": card.knowledge_point_id,
        "stable_assessment_id": card.stable_assessment_id,
        "stable_assessment_sequence": card.stable_assessment_sequence,
        "evidence": [{"id": rid, "content_hash": rhash} for rid, rhash in evidence_refs],
        "sources": [{"id": sid, "content_hash": shash} for sid, shash in source_refs],
        "artifacts": artifact_refs,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assessment_attempt(progress: LearningProgress, assessment: RubricAssessment) -> FeynmanAttempt:
    attempt = next((a for a in progress.attempts if a.id == assessment.attempt_id), None)
    if attempt is None or attempt.status == AttemptStatus.INVALIDATED:
        raise KnowledgeCardInputValidationError(
            f"assessment {assessment.id!r} has no valid attempt {assessment.attempt_id!r}"
        )
    return attempt


def build_generation_input(
    progress: LearningProgress,
    card: KnowledgeCardRecord,
    assessment: RubricAssessment,
    *,
    media_store: Any = None,
) -> dict[str, Any]:
    """Secret-free executor input projection (in-memory only, never persisted).

    The executor may read the assessment-bound evidence content, source
    snapshots and the card's owned artifact identities to generate the draft.
    This projection is only ever hashed (``input_hash``) and passed to the
    executor — it is never serialized into card/attempt metadata (§6.6,
    requirement 3).
    """
    attempt = _assessment_attempt(progress, assessment)
    artifacts: list[dict[str, Any]] = []
    if media_store is not None:
        for artifact_id in card.artifact_ids:
            artifact = media_store.load_artifact(artifact_id)
            if artifact is None:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} referenced by card {card.id!r} does not exist"
                )
            if artifact.user_id != card.user_id:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} belongs to user {artifact.user_id!r}, "
                    f"not {card.user_id!r}"
                )
            artifacts.append(
                {
                    "id": artifact.id,
                    "sha256": artifact.sha256,
                    "mime_type": artifact.mime_type,
                    "original_path": artifact.original_path,
                }
            )
    return {
        "knowledge_point_id": card.knowledge_point_id,
        "stable_assessment_id": card.stable_assessment_id,
        "stable_assessment_sequence": card.stable_assessment_sequence,
        "title_hint": card.title,
        "evidence": _evidence_snapshot(progress, assessment),
        "sources": _source_snapshot_refs(progress, assessment, attempt),
        "artifacts": artifacts,
        "evaluator_snapshot_id": (
            f"{attempt.evaluator_snapshot.profile_id}/{attempt.evaluator_snapshot.resolved_model}"
            if attempt.evaluator_snapshot is not None
            else ""
        ),
    }


def append_generation_attempt(
    progress: LearningProgress, attempt: KnowledgeCardGenerationAttempt
) -> KnowledgeCardGenerationAttempt:
    """Append one attempt and link it on the card (append-only)."""
    card = require_card(progress, attempt.card_id)
    if attempt.id in card.generation_attempt_ids:
        return attempt
    progress.knowledge_card_generation_attempts.append(attempt)
    card.generation_attempt_ids.append(attempt.id)
    card.latest_generation_attempt_id = attempt.id
    return attempt


__all__ = [
    "append_generation_attempt",
    "attempts_for_card",
    "build_generation_input",
    "content_hash",
    "find_card",
    "find_generation_attempt",
    "frozen_input_fingerprint",
    "has_active_attempt",
    "latest_attempt_for_card",
    "next_generation_attempt_no",
    "nonterminal_attempt_for_input",
    "require_card",
    "require_generation_attempt",
]
