"""Conservative repeated-error / misconception tracking for Mastery Path.

Equivalence is ``knowledge_point_id`` plus a signature. The signature prefers
the structured ``error_type`` from a quiz attempt; when that is missing it
falls back to ``repeated_failure``. No embeddings, clustering, or LLM calls.
"""

from __future__ import annotations

import time
from typing import Any

from deeptutor.learning.models import (
    ErrorType,
    LearningEvidence,
    LearningProgress,
    MisconceptionState,
)

REPEATED_FAILURE = "repeated_failure"
REASON_ACTIVE_MISCONCEPTION = "active_misconception"

_WEAK_CONFIDENCE = 0.3
_ACTIVE_CONFIDENCE = 0.6
_CONFIDENCE_STEP = 0.25
_DECAY_PER_SUCCESS = 0.35
_RESOLVE_AFTER_SUCCESSES = 2
_RESOLVE_CONFIDENCE_FLOOR = 0.15
_MAX_EVIDENCE_REFS = 8


def misconception_key(kp_id: str, signature: str) -> str:
    return f"{kp_id}:{signature or REPEATED_FAILURE}"


def misconception_signature(
    *,
    error_type: ErrorType | str | None = None,
    evidence: LearningEvidence | None = None,
) -> str:
    """Stable grouping key for one failure.

    Prefer the graded ``error_type``. Without one, incorrect/partial evidence
    collapses to the conservative ``repeated_failure`` baseline.
    """
    if isinstance(error_type, ErrorType):
        return error_type.value
    if isinstance(error_type, str) and error_type.strip():
        return error_type.strip()
    if evidence is not None and evidence.result in {"incorrect", "partial"}:
        return REPEATED_FAILURE
    return REPEATED_FAILURE


def misconceptions_for(progress: LearningProgress, kp_id: str) -> list[MisconceptionState]:
    return [
        state for state in progress.misconceptions.values() if state.knowledge_point_id == kp_id
    ]


def has_active_misconception(progress: LearningProgress, kp_id: str) -> bool:
    return any(state.status == "active" for state in misconceptions_for(progress, kp_id))


def _clamp(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _append_ref(state: MisconceptionState, evidence_ref: str) -> None:
    ref = str(evidence_ref or "").strip()
    if not ref:
        return
    if ref in state.evidence_refs:
        return
    state.evidence_refs.append(ref)
    if len(state.evidence_refs) > _MAX_EVIDENCE_REFS:
        state.evidence_refs = state.evidence_refs[-_MAX_EVIDENCE_REFS:]


def _open_weak(
    kp_id: str,
    signature: str,
    *,
    now: float,
    evidence_ref: str,
) -> MisconceptionState:
    state = MisconceptionState(
        knowledge_point_id=kp_id,
        signature=signature or REPEATED_FAILURE,
        status="weak",
        confidence=_WEAK_CONFIDENCE,
        severity=_WEAK_CONFIDENCE,
        occurrence_count=1,
        consecutive_successes=0,
        last_seen_at=now,
    )
    _append_ref(state, evidence_ref)
    return state


def _record_failure(
    progress: LearningProgress,
    kp_id: str,
    *,
    signature: str,
    now: float,
    evidence_ref: str,
) -> MisconceptionState:
    key = misconception_key(kp_id, signature)
    existing = progress.misconceptions.get(key)
    if existing is None or existing.status == "resolved":
        state = _open_weak(kp_id, signature, now=now, evidence_ref=evidence_ref)
        progress.misconceptions[key] = state
        return state

    existing.occurrence_count += 1
    existing.consecutive_successes = 0
    existing.last_seen_at = now
    _append_ref(existing, evidence_ref)
    if existing.occurrence_count >= 2:
        existing.status = "active"
        existing.confidence = _clamp(
            max(_ACTIVE_CONFIDENCE, existing.confidence + _CONFIDENCE_STEP)
        )
        existing.severity = _clamp(max(_ACTIVE_CONFIDENCE, existing.severity + _CONFIDENCE_STEP))
    return existing


def _decay_success(
    progress: LearningProgress,
    kp_id: str,
    *,
    now: float,
    evidence_ref: str,
) -> None:
    for state in misconceptions_for(progress, kp_id):
        if state.status == "resolved":
            continue
        state.consecutive_successes += 1
        state.confidence = _clamp(state.confidence - _DECAY_PER_SUCCESS)
        state.severity = _clamp(state.severity - _DECAY_PER_SUCCESS)
        state.last_seen_at = now
        _append_ref(state, evidence_ref)
        if (
            state.consecutive_successes >= _RESOLVE_AFTER_SUCCESSES
            or state.confidence < _RESOLVE_CONFIDENCE_FLOOR
        ):
            state.status = "resolved"
            state.confidence = 0.0
            state.severity = 0.0
            state.last_resolved_at = now


def record_outcome(
    progress: LearningProgress,
    kp_id: str,
    *,
    failed: bool,
    signature: str = REPEATED_FAILURE,
    now: float | None = None,
    evidence_ref: str = "",
) -> MisconceptionState | None:
    """Update misconception state for one graded outcome. Mutates ``progress``."""
    if not kp_id:
        return None
    moment = time.time() if now is None else now
    if failed:
        return _record_failure(
            progress,
            kp_id,
            signature=signature or REPEATED_FAILURE,
            now=moment,
            evidence_ref=evidence_ref,
        )
    _decay_success(progress, kp_id, now=moment, evidence_ref=evidence_ref)
    return None


def record_from_evidence(
    progress: LearningProgress,
    evidence: LearningEvidence,
    *,
    error_type: ErrorType | str | None = None,
) -> MisconceptionState | None:
    """Apply one ``LearningEvidence`` event, using ``error_type`` when present."""
    failed = evidence.result in {"incorrect", "partial"}
    signature = misconception_signature(error_type=error_type, evidence=evidence)
    ref = (
        evidence.turn_id
        or evidence.session_id
        or f"{evidence.assessment_type}:{evidence.timestamp}"
    )
    return record_outcome(
        progress,
        evidence.knowledge_point_id,
        failed=failed,
        signature=signature,
        now=evidence.timestamp,
        evidence_ref=str(ref),
    )


def drop_unknown(progress: LearningProgress, known_kp_ids: set[str]) -> None:
    """Drop misconception rows whose knowledge point left the path."""
    progress.misconceptions = {
        key: state
        for key, state in progress.misconceptions.items()
        if state.knowledge_point_id in known_kp_ids
    }


def snapshot(progress: LearningProgress, kp_id: str) -> list[dict[str, Any]]:
    """JSON-ready misconception rows for one objective."""
    return [
        {
            "signature": state.signature,
            "status": state.status,
            "confidence": round(state.confidence, 3),
            "severity": round(state.severity, 3),
            "occurrence_count": state.occurrence_count,
            "consecutive_successes": state.consecutive_successes,
            "last_seen_at": state.last_seen_at,
            "last_resolved_at": state.last_resolved_at,
        }
        for state in misconceptions_for(progress, kp_id)
    ]


__all__ = [
    "REASON_ACTIVE_MISCONCEPTION",
    "REPEATED_FAILURE",
    "drop_unknown",
    "has_active_misconception",
    "misconception_key",
    "misconception_signature",
    "misconceptions_for",
    "record_from_evidence",
    "record_outcome",
    "snapshot",
]
