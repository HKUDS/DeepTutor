"""Shared deterministic builders for the LRN-02 Feynman policy tests.

Not a test module itself (no ``test_`` prefix); imported by the focused
grading/policy/scheduler/property tests so they share one convention for
constructing evidence chains, attempts and assessments with fixed timestamps.
"""

from __future__ import annotations

from deeptutor.learning.models import (
    AttemptStatus,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    InputMode,
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
    RubricAssessment,
    RubricScores,
    SourceCitation,
    SourceSnapshot,
)

#: Fixed clock so tests never depend on wall time.
START = 1_000_000.0
DAY = 86400.0


def kp_progress(
    kp_type: KnowledgeType = KnowledgeType.CONCEPT,
    *,
    kp_id: str = "kp1",
    chain_id: str = "chain-1",
    with_sources: bool = True,
    attempt_id: str = "a1",
    attempt_status: AttemptStatus = AttemptStatus.COLLECTING,
    attempt_cycle: str = "initial",
) -> tuple[LearningProgress, FeynmanAttempt]:
    """A progress with one module/knowledge point and a collecting attempt."""
    from deeptutor.learning.models import AttemptCycleType

    progress = LearningProgress(book_id="book1")
    progress.modules = [
        LearningModule(
            id="m1",
            name="Module 1",
            order=0,
            knowledge_points=[
                KnowledgePoint(id=kp_id, name=kp_id.upper(), type=kp_type, module_id="m1")
            ],
        )
    ]
    progress.knowledge_types[kp_id] = kp_type
    if with_sources:
        progress.source_snapshots.append(SourceSnapshot(id="s1", citation_anchors=["p.3", "p.4"]))
        progress.source_snapshots.append(SourceSnapshot(id="s2", citation_anchors=["fig.2"]))
    attempt = FeynmanAttempt(
        id=attempt_id,
        knowledge_point_id=kp_id,
        cycle_type=AttemptCycleType(attempt_cycle),
        status=attempt_status,
        active_chain_id=chain_id,
        source_snapshot_ids=["s1", "s2"] if with_sources else [],
    )
    progress.attempts.append(attempt)
    return progress, attempt


def add_attempt(
    progress: LearningProgress,
    *,
    attempt_id: str = "a2",
    kp_id: str = "kp1",
    cycle_type: str = "delayed_reteach",
    status: AttemptStatus = AttemptStatus.ASSESSED,
    chain_id: str = "chain-2",
    created_at: float | None = None,
) -> FeynmanAttempt:
    """Append another attempt for the same knowledge point."""
    from deeptutor.learning.models import AttemptCycleType

    attempt = FeynmanAttempt(
        id=attempt_id,
        knowledge_point_id=kp_id,
        cycle_type=AttemptCycleType(cycle_type),
        status=status,
        active_chain_id=chain_id,
        source_snapshot_ids=["s1", "s2"],
        created_at=created_at if created_at is not None else START + 200,
    )
    progress.attempts.append(attempt)
    return attempt


def add_evidence(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    kind: EvidenceKind,
    *,
    event_seq: int | None = None,
    created_at: float | None = None,
    question_evidence_id: str = "",
    input_mode: InputMode = InputMode.TEXT,
    transcript_confirmed: bool = False,
    source_citations: list[SourceCitation] | None = None,
    help_level: str | None = None,
    chain_id: str | None = None,
) -> EvidenceItem:
    """Append one evidence item with deterministic id/order."""
    cid = chain_id or attempt.active_chain_id
    seq = event_seq
    if seq is None:
        seq = (
            len(
                [
                    e
                    for e in progress.evidence_items
                    if e.attempt_id == attempt.id and e.chain_id == cid
                ]
            )
            + 1
        )
    created = created_at if created_at is not None else START + seq
    item = EvidenceItem(
        id=f"{cid}-{seq}",
        attempt_id=attempt.id,
        chain_id=cid,
        kind=kind,
        event_seq=seq,
        input_mode=input_mode,
        transcript_confirmed=transcript_confirmed,
        question_evidence_id=question_evidence_id,
        source_citations=source_citations or [],
        help_level=help_level,
        created_at=created,
    )
    progress.evidence_items.append(item)
    return item


def append_complete_chain(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    *,
    start: float = START,
    chain_id: str | None = None,
    explanation_voice: bool = False,
    explanation_confirmed: bool = False,
    answer_voice: bool = False,
    answer_confirmed: bool = False,
    probe_answers: bool = True,
    transfer: bool = True,
) -> list[EvidenceItem]:
    """Append a full, valid evidence chain and return its evidence items.

    ``answer_voice``/``answer_confirmed`` apply to the learner's probe and
    transfer answers; ``explanation_voice``/``explanation_confirmed`` apply to
    the explanation. The returned list is in chain order.
    """
    cid = chain_id or attempt.active_chain_id
    existing = [
        e for e in progress.evidence_items if e.attempt_id == attempt.id and e.chain_id == cid
    ]
    seq = len(existing)
    items: list[EvidenceItem] = []

    def add(kind: EvidenceKind, **kwargs) -> EvidenceItem:
        nonlocal seq
        seq += 1
        kwargs.setdefault("event_seq", seq)
        kwargs.setdefault("created_at", start + seq)
        item = add_evidence(progress, attempt, kind, chain_id=cid, **kwargs)
        items.append(item)
        return item

    add(
        EvidenceKind.EXPLANATION,
        input_mode=InputMode.VOICE_TRANSCRIPT if explanation_voice else InputMode.TEXT,
        transcript_confirmed=explanation_confirmed,
        source_citations=[SourceCitation(source_snapshot_id="s1", anchor="p.3")],
    )
    q1 = add(EvidenceKind.PROBE_QUESTION)
    if probe_answers:
        add(
            EvidenceKind.PROBE_ANSWER,
            question_evidence_id=q1.id,
            input_mode=InputMode.VOICE_TRANSCRIPT if answer_voice else InputMode.TEXT,
            transcript_confirmed=answer_confirmed,
        )
    q2 = add(EvidenceKind.PROBE_QUESTION)
    if probe_answers:
        add(
            EvidenceKind.PROBE_ANSWER,
            question_evidence_id=q2.id,
            input_mode=InputMode.VOICE_TRANSCRIPT if answer_voice else InputMode.TEXT,
            transcript_confirmed=answer_confirmed,
        )
    if transfer:
        qt = add(EvidenceKind.TRANSFER_QUESTION)
        add(
            EvidenceKind.TRANSFER_ANSWER,
            question_evidence_id=qt.id,
            input_mode=InputMode.VOICE_TRANSCRIPT if answer_voice else InputMode.TEXT,
            transcript_confirmed=answer_confirmed,
        )
    return items


def passing_assessment(
    attempt_id: str = "a1",
    *,
    assessment_id: str = "ra1",
    evidence_ids: list[str] | None = None,
    created_at: float | None = None,
    source_citation: bool = True,
    critical_errors: list[str] | None = None,
    rubric: RubricScores | None = None,
) -> RubricAssessment:
    """A rubric assessment that passes every server-side threshold."""
    return RubricAssessment(
        id=assessment_id,
        attempt_id=attempt_id,
        rubric=rubric or RubricScores(correctness=2, completeness=1, causal_clarity=1, transfer=2),
        critical_errors=critical_errors or [],
        evidence_ids=list(evidence_ids or []),
        source_citations=(
            [SourceCitation(source_snapshot_id="s1", anchor="p.3")] if source_citation else []
        ),
        created_at=created_at if created_at is not None else START + 100,
    )


def chain_evidence_ids(progress: LearningProgress, attempt: FeynmanAttempt) -> list[str]:
    """The evidence ids currently in the attempt's active chain."""
    return [
        e.id
        for e in progress.evidence_items
        if e.attempt_id == attempt.id and e.chain_id == attempt.active_chain_id
    ]
