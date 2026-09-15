"""Pure, evidence-backed calculation of the six-dimension learner profile.

The calculator reads a ``LearningProgress`` snapshot and optional evidence
supplied by adjacent domains.  It performs no persistence or network I/O, so
the API, tests, and future batch jobs all share exactly the same scoring rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
import time
from typing import Protocol, Sequence

from deeptutor.learning.models import (
    ErrorType,
    KnowledgeType,
    LearningProgress,
    QuizAttempt,
    RepetitionState,
    SixDimensionEvidenceRef,
    SixDimensionKey,
    SixDimensionResult,
    SixDimensionSnapshot,
)
from deeptutor.learning.policy import display_mastery
from deeptutor.learning.scheduler import INTERVAL_SEQUENCES

DIMENSION_ORDER: tuple[SixDimensionKey, ...] = (
    "knowledge",
    "procedure",
    "understanding",
    "transfer",
    "retention",
    "habit",
)

# A dimension never receives a numeric zero merely because its evidence is
# absent. Habit needs several route-task observations because one completed
# task is not yet a learning habit; the other dimensions have event-level
# evidence that can be scored from the first observation while confidence
# remains deliberately low.
MIN_EVIDENCE_COUNTS: dict[SixDimensionKey, int] = {
    "knowledge": 1,
    "procedure": 1,
    "understanding": 1,
    "transfer": 1,
    "retention": 1,
    "habit": 3,
}

FULL_CONFIDENCE_COUNTS: dict[SixDimensionKey, int] = {
    "knowledge": 8,
    "procedure": 8,
    "understanding": 4,
    "transfer": 4,
    "retention": 4,
    "habit": 7,
}


@dataclass(frozen=True, slots=True)
class TransferEvidence:
    """Normalized future output of the approved-variant classifier."""

    id: str
    score: float
    timestamp: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("transfer evidence id must not be empty")
        if not 0 <= self.score <= 1:
            raise ValueError("transfer evidence score must be between 0 and 1")


class TransferEvidenceAdapter(Protocol):
    """Reserved boundary for variant-classification evidence.

    T012 intentionally provides only this interface.  The question/variant
    domain will implement it later without adding a dependency from learning
    back into that domain.
    """

    def list_transfer_evidence(
        self,
        book_id: str,
        *,
        since: float | None = None,
        until: float | None = None,
    ) -> Sequence[TransferEvidence]: ...


@dataclass(frozen=True, slots=True)
class RouteTaskEvidence:
    """A completed/planned-route observation used only when that feature exists."""

    id: str
    score: float
    timestamp: float | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("route-task evidence id must not be empty")
        if not 0 <= self.score <= 1:
            raise ValueError("route-task evidence score must be between 0 and 1")


def _in_window(timestamp: float | None, since: float | None, until: float | None) -> bool:
    if timestamp is None:
        return since is None and until is None
    return (since is None or timestamp >= since) and (until is None or timestamp <= until)


def _attempt_ref(attempt: QuizAttempt) -> SixDimensionEvidenceRef:
    # QuizAttempt predates this feature and has no dedicated id. Combining its
    # stable question id with its timestamp makes repeated attempts separately
    # addressable while remaining deterministic across snapshot calls.
    return SixDimensionEvidenceRef(
        kind="attempt",
        id=f"{attempt.question_id}@{attempt.timestamp:.6f}",
    )


def _dedupe_refs(refs: Sequence[SixDimensionEvidenceRef]) -> list[SixDimensionEvidenceRef]:
    seen: set[tuple[str, str]] = set()
    result: list[SixDimensionEvidenceRef] = []
    for ref in refs:
        identity = (ref.kind, ref.id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(ref)
    return result


def _dimension(
    *,
    key: SixDimensionKey,
    samples: Sequence[float],
    refs: Sequence[SixDimensionEvidenceRef],
    scored_explanation: str,
    insufficient_explanation: str,
    next_action: str,
) -> SixDimensionResult:
    evidence_refs = _dedupe_refs(refs)
    evidence_count = len(evidence_refs)
    confidence = round(min(1.0, evidence_count / FULL_CONFIDENCE_COUNTS[key]), 2)
    enough = bool(samples) and evidence_count >= MIN_EVIDENCE_COUNTS[key]
    return SixDimensionResult(
        key=key,
        score=round(fmean(samples) * 100, 1) if enough else None,
        data_state="scored" if enough else "insufficient",
        confidence=confidence,
        evidence_count=evidence_count,
        evidence_refs=evidence_refs,
        explanation=scored_explanation if enough else insufficient_explanation,
        next_action=next_action,
    )


def _knowledge_dimension(
    progress: LearningProgress,
    *,
    since: float | None,
    until: float | None,
) -> SixDimensionResult:
    kp_by_id = {kp.id: kp for module in progress.modules for kp in module.knowledge_points}
    attempts = [
        attempt for attempt in progress.quiz_attempts if _in_window(attempt.timestamp, since, until)
    ]
    observed_kp_ids = {attempt.knowledge_point_id for attempt in attempts}
    refs: list[SixDimensionEvidenceRef] = [_attempt_ref(attempt) for attempt in attempts]

    # Qualitative assessments do not yet have event timestamps. For an
    # unbounded snapshot they are valid lifetime evidence; for a bounded query
    # the progress update timestamp is the narrowest honest timestamp available.
    if _in_window(progress.updated_at, since, until):
        observed_kp_ids.update(progress.qualitative_mastery)
        refs.extend(
            SixDimensionEvidenceRef(kind="attempt", id=f"feynman:{kp_id}")
            for kp_id in progress.qualitative_mastery
        )

    samples = [
        display_mastery(progress, kp_by_id[kp_id])
        for kp_id in sorted(observed_kp_ids)
        if kp_id in kp_by_id
    ]
    return _dimension(
        key="knowledge",
        samples=samples,
        refs=refs,
        scored_explanation=f"基于 {len(samples)} 个已观察知识点的当前掌握度。",
        insufficient_explanation="尚无可用于知识掌握度评分的答题或讲解证据。",
        next_action="完成一次当前知识点练习，并查看掌握度变化。",
    )


def _procedure_dimension(
    progress: LearningProgress,
    *,
    since: float | None,
    until: float | None,
) -> SixDimensionResult:
    attempts = [
        attempt for attempt in progress.quiz_attempts if _in_window(attempt.timestamp, since, until)
    ]
    samples = [1.0 if attempt.is_correct else 0.0 for attempt in attempts]
    refs: list[SixDimensionEvidenceRef] = [_attempt_ref(attempt) for attempt in attempts]
    represented_errors = {
        (attempt.question_id, attempt.knowledge_point_id)
        for attempt in attempts
        if attempt.error_type == ErrorType.APPLICATION_ERROR
    }

    application_errors = [
        error
        for error in progress.error_records
        if error.error_type == ErrorType.APPLICATION_ERROR
        and _in_window(error.created_at, since, until)
    ]
    for error in application_errors:
        refs.append(SixDimensionEvidenceRef(kind="error", id=error.id))
        if (error.question_id, error.knowledge_point_id) not in represented_errors:
            # Legacy progress can contain an error record after its originating
            # attempt was pruned. It is still valid negative procedure evidence.
            samples.append(0.0)

    return _dimension(
        key="procedure",
        samples=samples,
        refs=refs,
        scored_explanation=(
            f"基于 {len(attempts)} 次答题的正确性及 {len(application_errors)} 条应用错因。"
        ),
        insufficient_explanation="尚无答题正确性或应用错误证据。",
        next_action="完成一道需要分步求解的练习，并复盘解题步骤。",
    )


def _understanding_dimension(
    progress: LearningProgress,
    *,
    since: float | None,
    until: float | None,
) -> SixDimensionResult:
    assessment_ids = set(progress.qualitative_mastery) | set(progress.feynman_explanations)
    if not _in_window(progress.updated_at, since, until):
        assessment_ids = set()
    samples = [
        1.0 if progress.qualitative_mastery.get(kp_id, False) else 0.0 for kp_id in assessment_ids
    ]
    refs = [
        SixDimensionEvidenceRef(kind="attempt", id=f"feynman:{kp_id}")
        for kp_id in sorted(assessment_ids)
    ]
    return _dimension(
        key="understanding",
        samples=samples,
        refs=refs,
        scored_explanation=f"基于 {len(assessment_ids)} 次费曼式讲解评估。",
        insufficient_explanation="尚无用自己的话讲解知识点的评估证据。",
        next_action="选择一个知识点，用自己的话完整讲解一次。",
    )


def _transfer_dimension(
    evidence: Sequence[TransferEvidence],
    *,
    since: float | None,
    until: float | None,
) -> SixDimensionResult:
    selected = [item for item in evidence if _in_window(item.timestamp, since, until)]
    return _dimension(
        key="transfer",
        samples=[item.score for item in selected],
        refs=[SixDimensionEvidenceRef(kind="attempt", id=item.id) for item in selected],
        scored_explanation=f"基于 {len(selected)} 次迁移或变式练习。",
        insufficient_explanation="尚无足够的迁移或变式练习证据。",
        next_action="完成一次变式练习，检验能否把方法迁移到新情境。",
    )


def _retention_dimension(
    progress: LearningProgress,
    *,
    since: float | None,
    until: float | None,
) -> SixDimensionResult:
    # ReviewTask carries the stable reference id while its RepetitionState
    # carries the achieved interval. The state itself has no updated_at, so the
    # parent progress timestamp is used for bounded snapshots.
    if not _in_window(progress.updated_at, since, until):
        return _dimension(
            key="retention",
            samples=[],
            refs=[],
            scored_explanation="基于 0 个间隔复习状态的已达间隔。",
            insufficient_explanation="尚无间隔复习状态可用于保持度评分。",
            next_action="完成一次到期复习，让系统记录长期保持证据。",
        )

    tasks_by_kp = {task.knowledge_point_id: task for task in progress.review_queue}
    review_states: list[tuple[str, KnowledgeType, RepetitionState]] = []
    for kp_id, state in progress.repetition_states.items():
        task = tasks_by_kp.pop(kp_id, None)
        kp_type = (
            task.knowledge_type
            if task is not None
            else progress.knowledge_types.get(kp_id, KnowledgeType.MEMORY)
        )
        review_states.append((task.id if task is not None else f"review_{kp_id}", kp_type, state))
    review_states.extend(
        (task.id, task.knowledge_type, task.state) for task in tasks_by_kp.values()
    )

    samples: list[float] = []
    for _, kp_type, state in review_states:
        interval_count = len(INTERVAL_SEQUENCES[kp_type])
        max_index = max(1, interval_count - 1)
        samples.append(min(1.0, max(0.0, state.interval_index / max_index)))
    return _dimension(
        key="retention",
        samples=samples,
        refs=[
            SixDimensionEvidenceRef(kind="review", id=review_id)
            for review_id, _, _ in review_states
        ],
        scored_explanation=f"基于 {len(review_states)} 个间隔复习状态的已达间隔。",
        insufficient_explanation="尚无间隔复习状态可用于保持度评分。",
        next_action="完成一次到期复习，让系统记录长期保持证据。",
    )


def _habit_dimension(
    evidence: Sequence[RouteTaskEvidence],
    *,
    since: float | None,
    until: float | None,
) -> SixDimensionResult:
    selected = [item for item in evidence if _in_window(item.timestamp, since, until)]
    return _dimension(
        key="habit",
        samples=[item.score for item in selected],
        refs=[SixDimensionEvidenceRef(kind="route_task", id=item.id) for item in selected],
        scored_explanation=f"基于 {len(selected)} 条学习路线任务记录。",
        insufficient_explanation=(
            f"学习路线任务证据不足（至少需要 {MIN_EVIDENCE_COUNTS['habit']} 条）。"
        ),
        next_action="连续完成学习路线中的每日任务，形成稳定学习节奏。",
    )


def compute_six_dimension_snapshot(
    progress: LearningProgress,
    *,
    since: float | None = None,
    until: float | None = None,
    transfer_evidence: Sequence[TransferEvidence] = (),
    route_task_evidence: Sequence[RouteTaskEvidence] = (),
    generated_at: float | None = None,
) -> SixDimensionSnapshot:
    """Calculate one traceable snapshot without mutating ``progress``.

    ``transfer_evidence`` and ``route_task_evidence`` default to empty because
    their producer features are not enabled yet. Empty or below-threshold input
    becomes ``score=null`` with ``data_state=insufficient``; it never becomes a
    misleading zero.
    """

    if since is not None and until is not None and since > until:
        raise ValueError("since must be less than or equal to until")

    dimensions = [
        _knowledge_dimension(progress, since=since, until=until),
        _procedure_dimension(progress, since=since, until=until),
        _understanding_dimension(progress, since=since, until=until),
        _transfer_dimension(transfer_evidence, since=since, until=until),
        _retention_dimension(progress, since=since, until=until),
        _habit_dimension(route_task_evidence, since=since, until=until),
    ]
    scored = [dimension.score for dimension in dimensions if dimension.score is not None]
    overall = round(fmean(scored), 1) if scored else None
    return SixDimensionSnapshot(
        book_id=progress.book_id,
        generated_at=time.time() if generated_at is None else generated_at,
        dimensions=dimensions,
        overall=overall,
    )


__all__ = [
    "DIMENSION_ORDER",
    "MIN_EVIDENCE_COUNTS",
    "FULL_CONFIDENCE_COUNTS",
    "TransferEvidence",
    "TransferEvidenceAdapter",
    "RouteTaskEvidence",
    "compute_six_dimension_snapshot",
]
