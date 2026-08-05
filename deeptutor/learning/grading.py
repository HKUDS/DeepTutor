"""Deterministic answer grading + coarse error classification for Mastery Path.

Two halves live here:

* :func:`grade_answer` / :func:`classify_error` — the legacy post-answer
  pipeline: a pure correctness check plus a coarse wrong-answer tagger.
* The Feynman evidence gate (LRN-02) — a pure, deterministic validator over
  the append-only evidence chain plus the server-side rubric hard gate. No LLM
  call and no wall-clock dependence: every decision is recomputed from the
  persisted ``LearningProgress``, and the caller/model can never set ``passed``
  — the server computes and records the :class:`ServerGateResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.learning.models import ErrorType

from deeptutor.learning.models import (
    ConflictStatus,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    HelpLevel,
    InputMode,
    LearningProgress,
    RubricAssessment,
    ServerGateResult,
    SourceCitation,
    SourceConflict,
)

# ── Feynman evidence chain (spec §6.1, §7.2) ────────────────────────────

#: The required evidence kinds, in the order the chain is normally collected.
REQUIRED_EVIDENCE_KINDS: tuple[str, ...] = (
    "explanation",
    "probe_question",
    "probe_answer",
    "transfer_question",
    "transfer_answer",
)

#: Evidence kinds produced by the learner. Voice-transcript learner evidence
#: counts only when ``transcript_confirmed`` is true (§6.1 step 1).
_LEARNER_EVIDENCE_KINDS: frozenset[EvidenceKind] = frozenset(
    {
        EvidenceKind.EXPLANATION,
        EvidenceKind.PROBE_ANSWER,
        EvidenceKind.TRANSFER_ANSWER,
    }
)

#: Kinds that can serve as the plain explanation; a ``reteach`` restates it.
_EXPLANATION_KINDS: frozenset[EvidenceKind] = frozenset(
    {EvidenceKind.EXPLANATION, EvidenceKind.RETEACH}
)


@dataclass(frozen=True)
class EvidenceChainResult:
    """Result of validating one attempt's current active evidence chain."""

    valid: bool
    chain_id: str = ""
    explanation_ids: tuple[str, ...] = ()
    probe_pairs: tuple[tuple[str, str], ...] = ()
    transfer_pairs: tuple[tuple[str, str], ...] = ()
    missing_evidence_kinds: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    used_full_explanation: bool = False


def _evidence_confirmed(item: EvidenceItem) -> bool:
    """Whether a learner-produced evidence item counts.

    Tutor-posed evidence (questions, references) is always counted; learner
    evidence from a voice transcript counts only once the transcript is
    confirmed, exactly as the approved spec requires.
    """
    if item.kind not in _LEARNER_EVIDENCE_KINDS:
        return True
    return item.input_mode != InputMode.VOICE_TRANSCRIPT or item.transcript_confirmed


def _order_key(item: EvidenceItem) -> tuple[float, int]:
    """Deterministic ordering for chain consistency (time, then event seq)."""
    return (item.created_at, item.event_seq)


def _bound_pairs(
    questions: list[EvidenceItem], answers: list[EvidenceItem]
) -> tuple[tuple[str, str], ...]:
    """Return ``(question_id, answer_id)`` pairs bound by ``question_evidence_id``.

    One pair per distinct question: two answers bound to the same question do
    not satisfy a two-pair requirement, an answer whose ``question_evidence_id``
    does not resolve to a question in the chain is ignored, an unconfirmed
    voice-transcript answer is ignored, and an answer that precedes its
    question (chain-consistency) is ignored.
    """
    by_id = {q.id: q for q in questions}
    pairs: dict[str, tuple[str, str]] = {}
    for answer in answers:
        question = by_id.get(answer.question_evidence_id)
        if question is None:
            continue
        if not _evidence_confirmed(answer):
            continue
        if _order_key(answer) < _order_key(question):
            continue
        if answer.question_evidence_id not in pairs:
            pairs[answer.question_evidence_id] = (question.id, answer.id)
    return tuple(sorted(pairs.values()))


def _active_chain_evidence(
    progress: LearningProgress, attempt: FeynmanAttempt, chain_id: str
) -> list[EvidenceItem]:
    """Evidence belonging to the attempt's current active chain, deduplicated."""
    seen: set[str] = set()
    items: list[EvidenceItem] = []
    for item in progress.evidence_items:
        if item.attempt_id != attempt.id or item.chain_id != chain_id:
            continue
        if item.id in seen:
            continue
        seen.add(item.id)
        items.append(item)
    return items


def _attempt_used_full_explanation(progress: LearningProgress, attempt: FeynmanAttempt) -> bool:
    """Whether a full explanation was ever used on this attempt.

    The chain is then closed for finalize and an entirely new complete reteach
    chain is required (§6.3, requirement 4).
    """
    if attempt.max_help_level == HelpLevel.FULL_EXPLANATION:
        return True
    return any(
        item.help_level == HelpLevel.FULL_EXPLANATION
        for item in progress.evidence_items
        if item.attempt_id == attempt.id
    )


def validate_evidence_chain(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    *,
    now: float | None = None,
) -> EvidenceChainResult:
    """Validate the attempt's current active evidence chain deterministically.

    A valid chain requires one confirmed plain explanation, at least two
    distinct probe-question/probe-answer pairs correctly bound by
    ``question_evidence_id``, and one transfer-question/transfer-answer pair —
    all belonging to the attempt and its current active chain. Duplicate ids or
    mismatched bindings never satisfy the count.
    """
    chain_id = attempt.active_chain_id
    used_full = _attempt_used_full_explanation(progress, attempt)

    if not chain_id:
        return EvidenceChainResult(
            valid=False,
            chain_id="",
            missing_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
            reasons=("attempt has no active chain",),
            used_full_explanation=used_full,
        )

    chain = _active_chain_evidence(progress, attempt, chain_id)
    if not chain:
        return EvidenceChainResult(
            valid=False,
            chain_id=chain_id,
            missing_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
            reasons=("active chain has no evidence",),
            used_full_explanation=used_full,
        )

    # The chain must respect the approved Feynman sequence (spec §6.1):
    # explanation -> at least two probe pairs -> transfer. Once transfer has
    # begun, a late explanation/reteach/probe would manufacture a
    # count-complete but out-of-order chain, so it can never pass the gate.
    order_items = sorted(chain, key=_order_key)
    transfer_began = False
    for item in order_items:
        is_chain_reset = (
            item.kind == EvidenceKind.RETEACH and item.help_level == HelpLevel.FULL_EXPLANATION
        )
        if item.kind in (EvidenceKind.TRANSFER_QUESTION, EvidenceKind.TRANSFER_ANSWER):
            transfer_began = True
        elif not is_chain_reset and (
            item.kind in _EXPLANATION_KINDS
            or item.kind in (EvidenceKind.PROBE_QUESTION, EvidenceKind.PROBE_ANSWER)
        ):
            if transfer_began:
                return EvidenceChainResult(
                    valid=False,
                    chain_id=chain_id,
                    missing_evidence_kinds=REQUIRED_EVIDENCE_KINDS,
                    reasons=(
                        f"evidence chain out of order: {item.kind.value} after transfer has begun",
                    ),
                    used_full_explanation=used_full,
                )

    explanations = [
        item for item in chain if item.kind in _EXPLANATION_KINDS and _evidence_confirmed(item)
    ]
    probe_questions = [item for item in chain if item.kind == EvidenceKind.PROBE_QUESTION]
    probe_answers = [item for item in chain if item.kind == EvidenceKind.PROBE_ANSWER]
    transfer_questions = [item for item in chain if item.kind == EvidenceKind.TRANSFER_QUESTION]
    transfer_answers = [item for item in chain if item.kind == EvidenceKind.TRANSFER_ANSWER]
    probe_pairs = _bound_pairs(probe_questions, probe_answers)
    transfer_pairs = _bound_pairs(transfer_questions, transfer_answers)

    missing: list[str] = []
    if not explanations:
        missing.append("explanation")
    if len(probe_questions) < 2:
        missing.append("probe_question")
    if len(probe_pairs) < 2:
        missing.append("probe_answer")
    if not transfer_questions:
        missing.append("transfer_question")
    if not transfer_pairs:
        missing.append("transfer_answer")

    reasons: list[str] = []
    if missing:
        reasons.append("evidence chain incomplete: " + ", ".join(missing))

    return EvidenceChainResult(
        valid=not missing,
        chain_id=chain_id,
        explanation_ids=tuple(item.id for item in explanations),
        probe_pairs=probe_pairs,
        transfer_pairs=transfer_pairs,
        missing_evidence_kinds=tuple(missing),
        reasons=tuple(reasons),
        used_full_explanation=used_full,
    )


# ── server-side rubric hard gate (spec §6.4) ─────────────────────────────

#: Allowed rubric domain. Each of the four scores must be exactly one of these.
RUBRIC_DOMAIN: tuple[int, ...] = (0, 1, 2)


def _in_rubric_domain(score: object) -> bool:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return False
    value = float(score)
    return value.is_integer() and value in (0.0, 1.0, 2.0)


def _allowed_snapshot_ids(progress: LearningProgress, attempt: FeynmanAttempt) -> frozenset[str]:
    """Source snapshots the attempt is allowed to cite.

    The attempt pins its own snapshot set; otherwise the latest confirmed map
    version's snapshots are the allowed current source.
    """
    if attempt.source_snapshot_ids:
        return frozenset(attempt.source_snapshot_ids)
    if progress.map_versions:
        latest = max(progress.map_versions, key=lambda version: version.version)
        return frozenset(latest.source_snapshot_ids)
    return frozenset()


def _citation_resolves(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    citation: SourceCitation,
) -> bool:
    """Whether a citation resolves to an allowed current source snapshot/anchor."""
    if citation.source_snapshot_id not in _allowed_snapshot_ids(progress, attempt):
        return False
    snapshot = next(
        (
            candidate
            for candidate in progress.source_snapshots
            if candidate.id == citation.source_snapshot_id
        ),
        None,
    )
    if snapshot is None:
        return False
    if citation.anchor:
        # A supplied anchor must match a materialized anchor exactly; a snapshot
        # with no materialized anchors cannot satisfy a non-empty anchor.
        if citation.anchor not in snapshot.citation_anchors:
            return False
    return True


def _applicable_open_conflicts(progress: LearningProgress, kp_id: str) -> list[SourceConflict]:
    """Open source conflicts that block the correctness gate for this KP.

    ``SourceConflict`` is versioned (resolve/reopen append new revisions), so
    only the *newest* revision per conflict id is authoritative: an old OPEN
    revision must stop blocking once a RESOLVED revision is appended, and a
    reopen restores the block via a fresh OPEN revision (§7.7).
    """
    newest_by_id: dict[str, SourceConflict] = {}
    for conflict in progress.source_conflicts:
        if kp_id not in conflict.knowledge_point_ids:
            continue
        current = newest_by_id.get(conflict.id)
        if current is None or conflict.version > current.version:
            newest_by_id[conflict.id] = conflict
    return [
        conflict for conflict in newest_by_id.values() if conflict.status == ConflictStatus.OPEN
    ]


def compute_server_gate(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    assessment: RubricAssessment,
    *,
    now: float | None = None,
) -> ServerGateResult:
    """Compute the server-side hard gate verdict for one assessment.

    The gate is fully deterministic and never trusts the caller or the model:
    ``passed`` is recomputed here from the persisted evidence, rubric, citations
    and conflicts. Use :func:`record_server_gate` to stamp the result onto the
    assessment.
    """
    reasons: list[str] = []
    missing: list[str] = []
    used_full = _attempt_used_full_explanation(progress, attempt)

    rubric = assessment.rubric
    score_map = {
        "correctness": rubric.correctness,
        "completeness": rubric.completeness,
        "causal_clarity": rubric.causal_clarity,
        "transfer": rubric.transfer,
    }
    domain_ok = all(_in_rubric_domain(score) for score in score_map.values())
    if not domain_ok:
        bad = [name for name, score in score_map.items() if not _in_rubric_domain(score)]
        reasons.append(f"rubric outside 0|1|2 domain: {', '.join(bad)}")
    else:
        if rubric.correctness != 2:
            reasons.append("correctness must be 2")
        if rubric.transfer != 2:
            reasons.append("transfer must be 2")
        if rubric.completeness < 1:
            reasons.append("completeness must be >= 1")
        if rubric.causal_clarity < 1:
            reasons.append("causal_clarity must be >= 1")

    if assessment.critical_errors:
        reasons.append("critical errors present: " + "; ".join(assessment.critical_errors))

    chain = validate_evidence_chain(progress, attempt, now=now)
    missing.extend(chain.missing_evidence_kinds)
    if not chain.valid:
        reasons.extend(chain.reasons)

    # Every assessment evidence id must resolve to the current active chain.
    chain_ids = {
        item.id for item in _active_chain_evidence(progress, attempt, attempt.active_chain_id)
    }
    if not assessment.evidence_ids:
        missing.append("assessment_evidence")
        reasons.append("assessment references no evidence")
    else:
        for evidence_id in assessment.evidence_ids:
            if evidence_id not in chain_ids:
                missing.append("assessment_evidence")
                reasons.append(f"assessment evidence {evidence_id} is not in the active chain")

    # Citations on the assessment and on the evidence it references must
    # resolve to an allowed current source snapshot/anchor.
    all_citations = list(assessment.source_citations)
    for evidence_id in assessment.evidence_ids:
        item = next(
            (candidate for candidate in progress.evidence_items if candidate.id == evidence_id),
            None,
        )
        if item is not None:
            all_citations.extend(item.source_citations)
    for citation in all_citations:
        if not _citation_resolves(progress, attempt, citation):
            reasons.append(
                f"citation {citation.source_snapshot_id}:{citation.anchor} does not "
                "resolve to an allowed current source snapshot/anchor"
            )

    conflicts = _applicable_open_conflicts(progress, attempt.knowledge_point_id)
    blocked = [conflict.id for conflict in conflicts]
    if conflicts:
        reasons.append("open source conflict blocks the correctness gate")

    # Deduplicate missing kinds while preserving required-kind order.
    missing_set = set(missing)
    ordered_missing = [kind for kind in REQUIRED_EVIDENCE_KINDS if kind in missing_set]
    ordered_missing.extend(
        kind
        for kind in missing
        if kind not in REQUIRED_EVIDENCE_KINDS and kind not in ordered_missing
    )

    passed = not reasons and not missing
    return ServerGateResult(
        passed=passed,
        required_evidence_kinds=list(REQUIRED_EVIDENCE_KINDS),
        missing_evidence_kinds=ordered_missing,
        blocked_by_conflict=blocked,
        used_full_explanation=used_full,
        reasons=reasons,
    )


def record_server_gate(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    assessment: RubricAssessment,
    *,
    now: float | None = None,
) -> ServerGateResult:
    """Compute and record the server gate, overwriting any caller-set value.

    This is the only way an assessment's ``passed`` flag is set: the caller or
    the model cannot supply it.
    """
    result = compute_server_gate(progress, attempt, assessment, now=now)
    assessment.server_gate_result = result
    return result


def rotate_chain_for_full_explanation(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    *,
    now: float | None = None,
) -> str:
    """Close the current evidence chain and open a fresh reteach chain.

    After a ``full_explanation`` the old chain can no longer contribute to a
    finalize (spec §6.3): a new chain id becomes ``attempt.active_chain_id``,
    so the validator only sees evidence collected after the reset. Old evidence
    stays readable in the append-only store. Returns the new chain id.
    """
    moment = now if now is not None else time.time()
    existing = {
        item.chain_id
        for item in progress.evidence_items
        if item.attempt_id == attempt.id and item.chain_id
    }
    if attempt.active_chain_id:
        existing.add(attempt.active_chain_id)
    # Chain suffixes may have holes or be non-contiguous (e.g. 1 and 3 after a
    # mid-chain reset); the next id is always one past the largest seen suffix,
    # so a fresh chain never reuses/overwrites an existing chain id.
    prefix = f"{attempt.id}:chain:"
    max_suffix = 0
    for chain_id in existing:
        if chain_id.startswith(prefix):
            try:
                suffix = int(chain_id[len(prefix) :])
            except ValueError:
                continue
            max_suffix = max(max_suffix, suffix)
    new_chain_id = f"{prefix}{max_suffix + 1}"
    attempt.active_chain_id = new_chain_id
    attempt.max_help_level = HelpLevel.FULL_EXPLANATION
    attempt.updated_at = moment
    return new_chain_id


def grade_answer(user_answer: str, expected_answer: str, question_type: str = "short") -> bool:
    """Grade user answer against expected answer.

    Args:
        user_answer: The user's submitted answer.
        expected_answer: The stored expected answer.
        question_type: One of "choice", "short", "open".

    Returns:
        True if answer is correct.
    """
    user = user_answer.strip().lower()
    expected = expected_answer.strip().lower()

    if not expected:
        return False

    if question_type == "choice":
        user_norm = user.replace(" ", "")
        expected_norm = expected.replace(" ", "")
        return user_norm == expected_norm

    if question_type == "short":
        if user == expected:
            return True
        if len(expected) <= 30:
            return SequenceMatcher(None, user, expected).ratio() >= 0.85
        return False

    if question_type == "open":
        keywords = [k.strip() for k in re.split(r"[,;，；。\n]+", expected) if k.strip()]
        if not keywords:
            return False
        matched = sum(1 for kw in keywords if kw in user)
        return matched / len(keywords) >= 0.6

    return False


def classify_error(user_answer: str) -> ErrorType:
    """Coarse error classification for a wrong answer.

    A blank answer signals the student did not know (metacognitive); anything
    else is treated as a wrong application. The richer four-type taxonomy is
    assigned later by the LLM in the error-diagnosis stage.
    """
    from deeptutor.learning.models import ErrorType

    return ErrorType.METACOGNITIVE if not user_answer.strip() else ErrorType.APPLICATION_ERROR


__all__ = [
    "grade_answer",
    "classify_error",
    "REQUIRED_EVIDENCE_KINDS",
    "RUBRIC_DOMAIN",
    "EvidenceChainResult",
    "validate_evidence_chain",
    "compute_server_gate",
    "record_server_gate",
    "rotate_chain_for_full_explanation",
]
