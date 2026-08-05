from __future__ import annotations

from enum import Enum
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_KNOWLEDGE_TYPE_LEGACY: dict[str, str] = {
    "记忆型": "memory",
    "概念型": "concept",
    "程序型": "procedure",
    "设计型": "design",
}

_ERROR_TYPE_LEGACY: dict[str, str] = {
    "知识结构性": "structural",
    "理解偏差型": "deviation",
    "应用错误": "application",
    "元认知型": "metacognitive",
}


class KnowledgeType(str, Enum):
    MEMORY = "memory"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    DESIGN = "design"

    @classmethod
    def _missing_(cls, value: object) -> KnowledgeType | None:
        mapped = _KNOWLEDGE_TYPE_LEGACY.get(str(value))
        return cls(mapped) if mapped else None


class ErrorType(str, Enum):
    KNOWLEDGE_STRUCTURAL = "structural"
    UNDERSTANDING_DEVIATION = "deviation"
    APPLICATION_ERROR = "application"
    METACOGNITIVE = "metacognitive"

    @classmethod
    def _missing_(cls, value: object) -> ErrorType | None:
        mapped = _ERROR_TYPE_LEGACY.get(str(value))
        return cls(mapped) if mapped else None


# Stages removed in the Mastery Path simplification are mapped onto the nearest
# surviving stage so progress persisted by the older engine still deserializes.
_STAGE_LEGACY: dict[str, str] = {
    "diagnostic_phase1": "diagnostic",
    "diagnostic_phase2": "diagnostic",
    "metacognitive_intro": "explain",
    "plan": "explain",
    "pretest": "explain",
    "practice_quiz": "practice",
    "module_test": "review",
}


class LearningStage(str, Enum):
    """The Mastery Path loop: diagnose once, then per knowledge point teach and
    check understanding, then practice the module, diagnose errors, and schedule
    spaced review."""

    DIAGNOSTIC = "diagnostic"
    EXPLAIN = "explain"
    FEYNMAN_CHECK = "feynman_check"
    PRACTICE = "practice"
    ERROR_DIAGNOSIS = "error_diagnosis"
    REVIEW = "review"
    COMPLETED = "completed"

    @classmethod
    def _missing_(cls, value: object) -> LearningStage | None:
        mapped = _STAGE_LEGACY.get(str(value))
        return cls(mapped) if mapped else None


class KnowledgePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    type: KnowledgeType
    module_id: str


class LearningModule(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    order: int
    pass_threshold: float = 0.7
    knowledge_points: list[KnowledgePoint] = Field(default_factory=list)


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_questions: int = 0
    correct_count: int = 0
    module_mastery: dict[str, float] = Field(default_factory=dict)


class QuizAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question_id: str
    knowledge_point_id: str
    module_id: str = ""
    is_correct: bool
    user_answer: Any = None
    error_type: ErrorType | None = None
    self_attribution: str = ""
    mastery_estimate: float = 0.0
    timestamp: float = Field(default_factory=time.time)


class RetryAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: float
    is_correct: bool
    attempt_number: int


class ErrorRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    question_id: str
    knowledge_point_id: str
    module_id: str
    error_type: ErrorType
    self_attribution: str = ""
    ai_confirmation: str = ""
    retry_history: list[RetryAttempt] = Field(default_factory=list)
    status: Literal["active", "retrying", "review", "graduated"] = "active"
    created_at: float = Field(default_factory=time.time)


class RepetitionState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interval_index: int = 0
    consecutive_correct: int = 0
    consecutive_wrong: int = 0
    next_review_at: float


class ReviewTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    knowledge_point_id: str
    knowledge_type: KnowledgeType
    due_at: float
    priority: int
    state: RepetitionState


class PendingQuestion(BaseModel):
    """A question posed to the learner and awaiting their answer.

    Persisted so grading is deterministic across turns: the expected answer
    lives here server-side and never round-trips through the model. The tutor
    poses a question with ``mastery_quiz`` (storing this), the learner answers
    on a later turn, and ``mastery_grade`` scores the stored answer.
    """

    model_config = ConfigDict(extra="ignore")

    question_id: str
    knowledge_point_id: str
    module_id: str = ""
    prompt: str = ""
    question_type: str = "short"
    expected_answer: str = ""
    options: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


# ── Feynman learning v2 aggregates (LRN-01) ───────────────────────────────
# Historical records are append-only; the current state is a rebuildable
# projection. Legacy progress is imported as a *provisional* legacy projection
# and scheduled for a delayed reteach, never silently upgraded to stable.


class AttemptCycleType(str, Enum):
    INITIAL = "initial"
    DELAYED_RETEACH = "delayed_reteach"
    REEVALUATION = "reevaluation"
    TEST_OUT = "test_out"
    # Created by migration from a pre-v2 LearningProgress; projected as
    # provisional mastery and scheduled for a delayed reteach (§16.1).
    LEGACY_IMPORT = "legacy_import"


class AttemptStatus(str, Enum):
    DRAFT = "draft"
    COLLECTING = "collecting"
    READY_TO_ASSESS = "ready_to_assess"
    ASSESSED = "assessed"
    CLOSED = "closed"
    INVALIDATED = "invalidated"


class EvidenceKind(str, Enum):
    EXPLANATION = "explanation"
    PROBE_QUESTION = "probe_question"
    PROBE_ANSWER = "probe_answer"
    TRANSFER_QUESTION = "transfer_question"
    TRANSFER_ANSWER = "transfer_answer"
    RETEACH = "reteach"
    SOURCE_REFERENCE = "source_reference"


class InputMode(str, Enum):
    TEXT = "text"
    VOICE_TRANSCRIPT = "voice_transcript"


class MasteryState(str, Enum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    NEEDS_REVISION = "needs_revision"
    PROVISIONAL_MASTERY = "provisional_mastery"
    STABLE_MASTERY = "stable_mastery"


class ReviewState(str, Enum):
    UNSCHEDULED = "unscheduled"
    SCHEDULED = "scheduled"
    DUE = "due"
    IN_PROGRESS = "in_progress"


class HelpLevel(str, Enum):
    QUESTION = "question"
    HINT = "hint"
    SOURCE_LOCATOR = "source_locator"
    FULL_EXPLANATION = "full_explanation"


class SourceType(str, Enum):
    USER_MATERIAL = "user_material"
    WEB = "web"


class ConflictStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class ChallengeMode(str, Enum):
    REASSESS_EXISTING = "reassess_existing"
    COLLECT_NEW_EVIDENCE = "collect_new_evidence"


class ChallengeStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GapStatus(str, Enum):
    ACTIVE = "active"
    IMPROVING = "improving"
    RESOLVED = "resolved"
    REOPENED = "reopened"


#: Reason set when a source or knowledge-map update is incompatible with an
#: in-flight attempt, which is then atomically invalidated (§7.7).
INVALIDATION_REASON_SOURCE_VERSION_CHANGED = "source_version_changed"


class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_snapshot_id: str
    anchor: str = ""


class RubricScores(BaseModel):
    model_config = ConfigDict(extra="ignore")

    correctness: float = 0.0
    completeness: float = 0.0
    causal_clarity: float = 0.0
    transfer: float = 0.0


class ServerGateResult(BaseModel):
    """Server-side hard gate verdict recorded on every RubricAssessment."""

    model_config = ConfigDict(extra="ignore")

    passed: bool = False
    required_evidence_kinds: list[str] = Field(default_factory=list)
    missing_evidence_kinds: list[str] = Field(default_factory=list)
    blocked_by_conflict: list[str] = Field(default_factory=list)
    used_full_explanation: bool = False
    reasons: list[str] = Field(default_factory=list)


class EvaluatorSnapshot(BaseModel):
    """Frozen evaluation configuration captured at attempt start (§7.6).

    The snapshot is resolved without making an LLM call and pinned on the
    attempt; switching the teaching model mid-attempt never mutates it.
    Credentials are never stored — only the safe ``base_url_fingerprint``.
    """

    model_config = ConfigDict(extra="ignore")

    profile_id: str = ""
    profile_name: str = ""
    profile_revision: str = ""
    requested_provider: str = ""
    requested_api_protocol: str = ""
    requested_model: str = ""
    resolved_provider: str = ""
    resolved_api_protocol: str = ""
    resolved_model: str = ""
    auto_resolution_reason: str = ""
    base_url_fingerprint: str = ""
    strict_protocol: bool = False
    prompt_version: str = ""
    rubric_version: str = ""
    created_at: float = Field(default_factory=time.time)


class ModelInvocationPurpose(str, Enum):
    """Why an LLM invocation happened (§7.8)."""

    CHAT = "chat"
    TEACHING = "teaching"
    EVALUATION = "evaluation"
    KNOWLEDGE_CARD_DRAFT = "knowledge_card_draft"


class ModelInvocationStatus(str, Enum):
    """Lifecycle of one invocation audit record (§7.8).

    ``pending`` is appended *before* the provider call so a crash still leaves
    an audit trail; ``finish`` transitions it to a terminal state exactly once
    (``completed`` / ``failed`` / ``paused``). A paused record means the
    evaluator was unavailable at finalize and the frozen profile/model was NOT
    switched (§9.3).
    """

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class ModelInvocationUsage(BaseModel):
    """Normalized token usage for one invocation (§7.8).

    Kept deliberately minimal and provider-neutral; raw provider counters never
    appear here. Counters are validated to be non-negative so a corrupted or
    misreported provider total can never be persisted.
    """

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ModelInvocationRecord(BaseModel):
    """Append-only audit record for one LLM invocation (§7.8, §9.4).

    Created with ``status=pending`` before the provider call, then finalized
    afterwards by *immutable append/revision* semantics: the ``pending``
    revision is preserved as the historical record and a terminal revision
    (same ``id``, ``revision`` incremented) is appended. ``find``/API
    projections deterministically select the latest revision; historical
    revisions stay serialized and can never be overwritten or dropped. Only
    fingerprints and sanitized data are persisted — never API keys, auth
    headers, full private URLs, raw prompts/responses, or base64 media.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    #: Monotonic per-invocation revision. Revision 1 is the ``pending``
    #: pre-call record; each terminal ``finish`` appends the next revision.
    revision: int = 1
    purpose: ModelInvocationPurpose
    # Session/turn/tool references where applicable.
    session_id: str = ""
    turn_id: str = ""
    message_id: str = ""
    tool_call_id: str = ""
    attempt_id: str = ""
    knowledge_card_generation_attempt_id: str = ""
    # Requested (what the caller asked for).
    profile_id: str = ""
    profile_revision: str = ""
    requested_provider: str = ""
    requested_protocol: str = ""
    requested_model: str = ""
    # Resolved (what the runtime actually used after ``auto`` resolution).
    resolved_provider: str = ""
    resolved_protocol: str = ""
    resolved_model: str = ""
    auto_resolution_reason: str = ""
    base_url_fingerprint: str = ""
    strict_protocol: bool = False
    # Provider-reported identity. Literal ``unknown`` when absent — the
    # requested model is never copied into these fields (§7.6).
    provider_reported_model: str = "unknown"
    provider_model_version: str = "unknown"
    # Content/config fingerprints only — never raw prompts or responses.
    prompt_version: str = ""
    tool_schema_version: str = ""
    request_fingerprint: str = ""
    response_fingerprint: str = ""
    # Status/timing/usage/error.
    status: ModelInvocationStatus = ModelInvocationStatus.PENDING
    usage: ModelInvocationUsage = Field(default_factory=ModelInvocationUsage)
    sanitized_error: str = ""
    error_code: str = ""
    created_at: float = Field(default_factory=time.time)
    #: Monotonic: ``started_at`` is populated at pre-call start and
    #: ``finished_at`` is clamped to never precede it.
    started_at: float | None = None
    finished_at: float | None = None


class FeynmanAttempt(BaseModel):
    """One Feynman evidence-gathering cycle (§7.1)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    knowledge_point_id: str
    cycle_type: AttemptCycleType = AttemptCycleType.INITIAL
    status: AttemptStatus = AttemptStatus.DRAFT
    invalidated_reason: str = ""
    # Content version the attempt started from; a map update that bumps it
    # invalidates active attempts bound to the older version instead of
    # silently re-grading them.
    knowledge_point_version: int = 0
    # Map version (and materialized source snapshots) the attempt is bound to.
    map_version_id: str = ""
    source_snapshot_ids: list[str] = Field(default_factory=list)
    supersedes_attempt_id: str = ""
    session_id: str = ""
    started_turn_id: str = ""
    active_chain_id: str = ""
    max_help_level: HelpLevel = HelpLevel.QUESTION
    evaluator_snapshot: EvaluatorSnapshot | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    closed_at: float | None = None


class EvidenceItem(BaseModel):
    """A single evidence event bound to real session records (§7.2)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    attempt_id: str = ""
    chain_id: str = ""
    kind: EvidenceKind
    session_id: str = ""
    turn_id: str = ""
    message_id: str = ""
    event_seq: int = 0
    input_mode: InputMode = InputMode.TEXT
    transcript_confirmed: bool = False
    content_snapshot: str = ""
    content_hash: str = ""
    question_evidence_id: str = ""
    source_citations: list[SourceCitation] = Field(default_factory=list)
    help_level: HelpLevel | None = None
    created_at: float = Field(default_factory=time.time)


class RubricAssessment(BaseModel):
    """A single rubric scoring pass over one attempt's evidence (§7.3)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    attempt_id: str
    revision: int = 1
    assessment_sequence: int = 1
    rubric: RubricScores = Field(default_factory=RubricScores)
    critical_errors: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_citations: list[SourceCitation] = Field(default_factory=list)
    evaluator_snapshot: EvaluatorSnapshot | None = None
    model_invocation_id: str = ""
    supersedes_assessment_id: str = ""
    challenge_id: str = ""
    server_gate_result: ServerGateResult = Field(default_factory=ServerGateResult)
    created_at: float = Field(default_factory=time.time)


class ChallengeRecord(BaseModel):
    """A learner-initiated challenge of an assessment (§7.3.1)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    knowledge_point_id: str
    source_attempt_id: str = ""
    source_assessment_id: str = ""
    mode: ChallengeMode = ChallengeMode.REASSESS_EXISTING
    requested_evaluator_snapshot: EvaluatorSnapshot | None = None
    result_attempt_id: str = ""
    result_assessment_id: str = ""
    status: ChallengeStatus = ChallengeStatus.PENDING
    reason: str = ""
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None


class GapRecord(BaseModel):
    """A knowledge gap surfaced by an assessment (§7.4)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    knowledge_point_id: str
    label: str = ""
    description: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    source_citations: list[SourceCitation] = Field(default_factory=list)
    status: GapStatus = GapStatus.ACTIVE
    priority: int = 0
    first_seen_at: float = Field(default_factory=time.time)
    last_seen_at: float = Field(default_factory=time.time)
    resolved_at: float | None = None


class KnowledgeStateProjection(BaseModel):
    """Cached per-KP projection; rebuildable from attempts/assessments (§7.5)."""

    model_config = ConfigDict(extra="ignore")

    knowledge_point_id: str
    mastery_state: MasteryState = MasteryState.NEW
    review_state: ReviewState = ReviewState.UNSCHEDULED
    active_attempt_id: str = ""
    latest_assessment_id: str = ""
    provisional_since: float | None = None
    stable_since: float | None = None
    next_review_at: float | None = None
    updated_at: float = Field(default_factory=time.time)


class SourceSnapshot(BaseModel):
    """A materialized source; web material must be snapshotted before use (§7.7)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    source_type: SourceType = SourceType.USER_MATERIAL
    material_id: str = ""
    locator: str = ""
    title: str = ""
    content_hash: str = ""
    citation_anchors: list[str] = Field(default_factory=list)
    captured_at: float = Field(default_factory=time.time)


class KnowledgeMapVersion(BaseModel):
    """A confirmed revision of the learner's knowledge map (§7.7)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path_id: str
    version: int = 1
    nodes: list[str] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    priorities: dict[str, int] = Field(default_factory=dict)
    source_snapshot_ids: list[str] = Field(default_factory=list)
    confirmed_at: float = Field(default_factory=time.time)


class SourceConflict(BaseModel):
    """An open/resolved conflict between source snapshots (§7.7)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path_id: str = ""
    knowledge_point_ids: list[str] = Field(default_factory=list)
    claim: str = ""
    source_snapshot_ids: list[str] = Field(default_factory=list)
    citation_anchors: list[str] = Field(default_factory=list)
    version: int = 1
    status: ConflictStatus = ConflictStatus.OPEN
    accepted_snapshot_id: str = ""
    resolution_note: str = ""
    resolved_at: float | None = None
    resolved_by: str = ""


# ── Knowledge-card drafts and generation attempts (KB-02) ─────────────────
# Durable domain for §7.9 / §7.9.1. The *current* card projection is a mutable
# ``KnowledgeCardRecord``; generation attempts are append-only history. Neither
# ever copies raw conversation, rubric, gap text, provider response, prompt,
# auth data, base64 media or private URLs — only ids/hashes and the user
# confirmed/generated title/body.


class KnowledgeCardStatus(str, Enum):
    """Lifecycle of a knowledge-card record (§7.9)."""

    DRAFT = "draft"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    RECONCILE_REQUIRED = "reconcile_required"
    STALE_EVIDENCE = "stale_evidence"
    DISCARDED = "discarded"
    RETRACTING = "retracting"
    RETRACT_RECONCILE_REQUIRED = "retract_reconcile_required"
    RETRACTED = "retracted"


class DraftGenerationStatus(str, Enum):
    """Current generation outcome projected on the card (§7.9)."""

    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SUPERSEDED_BY_EDIT = "superseded_by_edit"


class GenerationAttemptStatus(str, Enum):
    """Lifecycle of one knowledge-card generation attempt (§7.9.1)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SUPERSEDED_BY_EDIT = "superseded_by_edit"


#: Terminal attempt states; these never auto-run and are never reopened.
TERMINAL_GENERATION_ATTEMPT_STATUSES: frozenset[GenerationAttemptStatus] = frozenset(
    {
        GenerationAttemptStatus.SUCCEEDED,
        GenerationAttemptStatus.FAILED,
        GenerationAttemptStatus.UNKNOWN,
        GenerationAttemptStatus.SUPERSEDED_BY_EDIT,
    }
)


class PublicationStatus(str, Enum):
    """Lifecycle of one knowledge-card publication record (KB-03, §7.9.2)."""

    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    RECONCILE_REQUIRED = "reconcile_required"


class RetractionStatus(str, Enum):
    """Lifecycle of one knowledge-card retraction record (KB-04, §7.11).

    Retraction records are append-only history; each record transitions its
    status in place under optimistic concurrency, and a retry after a confirmed
    failed rollback appends a *new* record for the same card revision.
    """

    QUEUED = "queued"
    QUARANTINING = "quarantining"
    REINDEXING = "reindexing"
    ROLLING_BACK = "rolling_back"
    RETRACTED = "retracted"
    FAILED = "failed"
    RECONCILE_REQUIRED = "reconcile_required"


#: Terminal retraction statuses; these never re-run and are never reopened.
TERMINAL_RETRACTION_STATUSES: frozenset[RetractionStatus] = frozenset(
    {
        RetractionStatus.RETRACTED,
        RetractionStatus.FAILED,
        RetractionStatus.RECONCILE_REQUIRED,
    }
)

#: Card statuses that occupy the per-knowledge-point "current card" slot
#: (§7.9). ``stale_evidence``, ``discarded`` and ``retracted`` do not occupy.
KNOWLEDGE_CARD_OCCUPYING_STATUSES: frozenset[KnowledgeCardStatus] = frozenset(
    {
        KnowledgeCardStatus.DRAFT,
        KnowledgeCardStatus.PUBLISHING,
        KnowledgeCardStatus.PUBLISH_FAILED,
        KnowledgeCardStatus.RECONCILE_REQUIRED,
        KnowledgeCardStatus.PUBLISHED,
        KnowledgeCardStatus.RETRACTING,
        KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED,
    }
)

#: Unpublished occupying states that a stale-evidence reconcile can convert to
#: ``stale_evidence`` (§6.6, §15). Published cards are immutable snapshots and
#: in-flight publication/retraction states are owned by KB-03/KB-04, so they are
#: left untouched by this reconcile.
STALEABLE_CARD_STATUSES: frozenset[KnowledgeCardStatus] = frozenset(
    {
        KnowledgeCardStatus.DRAFT,
        KnowledgeCardStatus.PUBLISH_FAILED,
        KnowledgeCardStatus.RECONCILE_REQUIRED,
    }
)


class KnowledgeCardRecord(BaseModel):
    """The current knowledge-card projection for one knowledge point (§7.9).

    This is a mutable projection guarded by optimistic concurrency
    (``revision`` / ``version``). It stores only the user confirmed/generated
    title/body plus provenance ids and hashes — raw conversation, rubric, gap,
    provider prompt/response, auth data, base64 media and private URLs are never
    copied here (they stay in the Evidence Store / Media Store).
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str = ""
    path_id: str = ""
    knowledge_point_id: str
    stable_attempt_id: str = ""
    stable_assessment_id: str = ""
    stable_assessment_sequence: int = 0
    status: KnowledgeCardStatus = KnowledgeCardStatus.DRAFT
    #: Content revision — increments whenever title/body (or artifact set)
    #: changes. Generation attempts freeze this as ``input_card_revision`` and
    #: API mutations carry it as ``expected_card_revision`` (§8.3).
    revision: int = 1
    #: General optimistic-concurrency counter, bumped on every card mutation.
    version: int = 0
    generation_locked_by_user_edit: bool = False
    title: str = ""
    body: str = ""
    content_hash: str = ""
    source_snapshot_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    generation_attempt_ids: list[str] = Field(default_factory=list)
    latest_generation_attempt_id: str = ""
    draft_generation_status: DraftGenerationStatus = DraftGenerationStatus.QUEUED
    # Publication fields (owned by KB-03); defaulted so old records load.
    target_kb_name: str = ""
    document_rel_path: str = ""
    document_sha256: str = ""
    publication_key: str = ""
    index_task_id: str = ""
    index_version: str = ""
    error_code: str = ""
    sanitized_error: str = ""
    #: Durable id of the last ``card_publish`` write operation (KB-03). Lets
    #: ``reconcile-publication`` inspect the exact write-operation record.
    publication_operation_id: str = ""
    #: Durable publication intent persisted before lease acquisition (KB-03).
    #: Non-``None`` only while a publication is staged/in-flight; cleared on a
    #: terminal outcome so a fresh draft never carries stale intent.
    publication_intent: PublicationIntent | None = None
    #: Durable retraction projection fields (KB-04). ``quarantine_rel_path`` is
    #: the fixed same-volume sandbox path the original raw bytes move to;
    #: ``retraction_request_id`` is the idempotency key for one card revision;
    #: ``retraction_operation_id`` links the exact ``card_retract`` write
    #: operation; ``retraction_intent`` is the durable intent persisted before
    #: lease acquisition (analogous to ``publication_intent``). All defaulted so
    #: old records load unchanged.
    quarantine_rel_path: str = ""
    retraction_request_id: str = ""
    retraction_operation_id: str = ""
    retraction_intent: RetractionIntent | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    confirmed_at: float | None = None
    published_at: float | None = None
    stale_at: float | None = None
    retracted_at: float | None = None

    @property
    def occupies_slot(self) -> bool:
        return self.status in KNOWLEDGE_CARD_OCCUPYING_STATUSES

    @property
    def is_editable_draft(self) -> bool:
        return self.status == KnowledgeCardStatus.DRAFT

    def content_fingerprint(self) -> str:
        """Deterministic fingerprint of the confirmed title/body."""
        import hashlib

        canonical = f"{self.title}\n{self.body}".strip()
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class KnowledgeCardGenerationAttempt(BaseModel):
    """One append-only generation attempt over a card's frozen input (§7.9.1).

    Attempts are append-only history: retries append a *new* attempt record
    linked through ``retry_of_generation_attempt_id``; a terminal attempt is
    never reopened or overwritten. The attempt's own lifecycle/lease fields
    (``status``/``version``/``lease_owner``/``lease_expires_at``/...) transition
    in place under optimistic concurrency, exactly like a media job record.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    card_id: str
    #: The card ``revision`` this attempt generated against. The apply step
    #: only lands when ``card.revision == input_card_revision`` and the card is
    #: still an editable, evidence-current draft not locked by a user edit.
    input_card_revision: int = 1
    stable_assessment_id: str = ""
    generation_attempt_no: int = 1
    retry_of_generation_attempt_id: str = ""
    #: Frozen copy of the stable assessment's evaluator snapshot; every retry
    #: reuses this exact snapshot — never silently re-resolved (§6.6).
    frozen_model_snapshot: EvaluatorSnapshot | None = None
    #: Deterministic hash of the frozen generation input projection.
    input_hash: str = ""
    status: GenerationAttemptStatus = GenerationAttemptStatus.QUEUED
    #: Optimistic-concurrency counter for lease/status transitions.
    version: int = 1
    model_invocation_id: str = ""
    #: Immutable content-addressed output blob (persisted before apply).
    output_blob_ref: str = ""
    output_hash: str = ""
    #: Single-flight lease: at most one unexpired holder may call the executor.
    lease_owner: str = ""
    lease_expires_at: float = 0.0
    error_code: str = ""
    sanitized_error: str = ""
    created_at: float = Field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_GENERATION_ATTEMPT_STATUSES

    @property
    def lease_active(self) -> bool:
        return bool(self.lease_owner)


class PublicationIntent(BaseModel):
    """Durable publication intent persisted *before* lease acquisition (KB-03).

    Closes the crash window between ``coordinator.acquire`` and the durable
    ``publishing`` card transition: the intent carries the target knowledge
    base, publication key, fixed path, content hash and request identity so a
    process crash at any point — before acquire, after acquire but before
    operation-id attachment, or after attachment but before staging — leaves
    enough durable identity for ``reconcile-publication`` to locate the exact
    orphan ``card_publish`` operation by target + subject + request identity
    and converge it without guessing or releasing another card's operation.
    """

    model_config = ConfigDict(extra="ignore")

    target_kb_name: str = ""
    publication_key: str = ""
    document_rel_path: str = ""
    document_sha256: str = ""
    request_id: str = ""
    expected_card_revision: int = 0
    #: Operation id filled in by the ``publishing`` transition; empty while the
    #: intent is merely staged ahead of lease acquisition.
    operation_id: str = ""
    created_at: float = Field(default_factory=time.time)


class KnowledgeCardPublicationRecord(BaseModel):
    """One append-only knowledge-card publication record (KB-03, §7.9.2).

    Publication records are append-only *revision history*: revision 1 is the
    first ``publication started`` record; every lifecycle transition (retry /
    finalize / reconcile) appends the next revision of the same logical record
    id — the original failure/request/timestamp is never overwritten or
    dropped. ``find``/``_latest_publication``/the read projection
    deterministically select the latest revision. Each record stores only
    identities, hashes, the fixed document path and sanitized diagnostics; raw
    conversation, provider prompts/responses, credentials, base64 and private
    URLs are never copied here. A logical publication keeps one key/path/hash,
    so a retry never creates a second raw/indexed document.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    #: Monotonic per-publication revision. Revision 1 is the initial
    #: ``publication started`` revision; each terminal/retry transition appends
    #: the next revision. Historical revisions are never mutated.
    revision: int = 1
    card_id: str
    #: Deterministic publication key ``user_id + card_id + card_revision +
    #: target_kb_name`` (§7.9.2 requirement 5). Same key + same content hash
    #: replays/reuses; same key + different content conflicts.
    publication_key: str
    #: The card ``revision`` that was published (the fixed path embeds it).
    card_revision: int
    target_kb_name: str
    #: Fixed relative document path ``learning_cards/{card_id}-v{revision}.md``.
    document_rel_path: str
    #: SHA-256 of the rendered UTF-8 Markdown document.
    document_sha256: str
    status: PublicationStatus = PublicationStatus.PUBLISHING
    request_id: str = ""
    error_code: str = ""
    sanitized_error: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    published_at: float | None = None


class RetractionIntent(BaseModel):
    """Durable retraction intent persisted *before* lease acquisition (KB-04).

    Closes the crash window between ``coordinator.acquire`` and the durable
    ``retracting`` card transition, exactly like :class:`PublicationIntent` for
    publication: the intent carries the target knowledge base, request identity,
    fixed original path, deterministic quarantine path, content hash and card
    revision so a process crash at any point — before acquire, after acquire but
    before operation-id attachment, or after attachment but before quarantine —
    leaves enough durable identity for ``reconcile-retraction`` to locate the
    exact orphan ``card_retract`` operation by target + subject + request
    identity and converge it without guessing or releasing another card's
    operation (§7.11, requirement 4).
    """

    model_config = ConfigDict(extra="ignore")

    target_kb_name: str = ""
    request_id: str = ""
    #: Internal attempt token distinguishing concurrent writers that reuse the
    #: same public ``request_id`` (KB-04 review round 2). Only the writer that
    #: durably owns the exact staged attempt may acquire/begin/clear the
    #: crash-recovery bridge; a losing concurrent caller must no-op/fail closed
    #: rather than overwrite the winner's intent. Defaulted so legacy intents
    #: load unchanged (backward compatible).
    attempt_id: str = ""
    original_rel_path: str = ""
    quarantine_rel_path: str = ""
    document_sha256: str = ""
    card_revision: int = 0
    #: Operation id filled in by the ``retracting`` transition; empty while the
    #: intent is merely staged ahead of lease acquisition.
    operation_id: str = ""
    created_at: float = Field(default_factory=time.time)


class KnowledgeCardRetractionRecord(BaseModel):
    """One append-only knowledge-card retraction record (KB-04, §7.11).

    Retraction records are append-only history separated from the card status
    projection: the list never drops or overwrites a prior record, and each
    record's lifecycle fields transition in place under optimistic concurrency
    (exactly like a generation attempt or media job record). A retry after a
    confirmed failed rollback appends a *new* record for the same card revision;
    at most one non-terminal retraction record may exist per
    ``(card_id, card_revision)``.

    ``request_id`` is idempotent for one card revision: the same request id with
    the same payload replays the existing result; reusing it with different
    retraction facts (a different target/path/hash) is a stable conflict. Each
    record stores only identities, fixed paths, hashes and sanitized
    diagnostics — raw conversation, provider secrets and private URLs are never
    copied here.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    card_id: str
    #: The card ``revision`` this retraction operates on (the fixed original
    #: path embeds it). One active retraction per card revision.
    card_revision: int
    user_id: str = ""
    target_kb_name: str
    request_id: str = ""
    status: RetractionStatus = RetractionStatus.QUEUED
    #: Durable id of the exact ``card_retract`` write operation (KB-04).
    operation_id: str = ""
    #: Fixed raw document path ``learning_cards/{card_id}-v{revision}.md``.
    original_rel_path: str
    #: Deterministic same-volume sandbox path the original bytes are moved to.
    quarantine_rel_path: str
    #: SHA-256 of the quarantined/published document.
    document_sha256: str
    index_task_id: str = ""
    error_code: str = ""
    sanitized_error: str = ""
    #: Post-terminal quarantine-cleanup state (KB-04 review round 1). The
    #: retraction is proven and durably ``retracted`` before any quarantine copy
    #: is deleted; ``pending`` means the exact matching copy is still present and
    #: cleanup is due, ``cleaned`` means it was durably deleted, and ``failed``
    #: means the last cleanup attempt errored (sanitized error + timestamp
    #: retained). A restart exposes these states and an explicit replay/cleanup
    #: path retries deterministically. Defaulted so old records load unchanged.
    cleanup_status: str = "pending"
    cleanup_error: str = ""
    cleanup_updated_at: float | None = None
    created_at: float = Field(default_factory=time.time)
    started_at: float = 0.0
    updated_at: float = Field(default_factory=time.time)
    finished_at: float = 0.0


class HistoryEvent(BaseModel):
    """An append-only audit record; ``seq`` is never rewritten once persisted."""

    model_config = ConfigDict(extra="ignore")

    seq: int
    event_type: str
    aggregate: str = ""
    aggregate_version: int = 0
    summary: str = ""
    at: float = Field(default_factory=time.time)
    payload: dict[str, Any] = Field(default_factory=dict)


class AggregateVersions(BaseModel):
    """Per-aggregate monotonic version counters (§17.2 idempotency contract)."""

    model_config = ConfigDict(extra="ignore")

    attempt: int = 0
    evidence: int = 0
    assessment: int = 0
    challenge: int = 0
    map: int = 0
    conflict: int = 0
    gap: int = 0
    model_invocation: int = 0


class LearningProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    book_id: str
    diagnostic: DiagnosticResult | None = None
    modules: list[LearningModule] = Field(default_factory=list)
    current_module_id: str = ""
    current_stage: LearningStage = LearningStage.DIAGNOSTIC
    current_kp_index: int = 0
    mastery_levels: dict[str, float] = Field(default_factory=dict)
    # Qualitative gate for CONCEPT / DESIGN knowledge points: True once the
    # tutor judges the learner's explanation sufficient (``mastery_assess``).
    # The quantitative ``mastery_levels`` gate covers MEMORY / PROCEDURE.
    qualitative_mastery: dict[str, bool] = Field(default_factory=dict)
    knowledge_types: dict[str, KnowledgeType] = Field(default_factory=dict)
    quiz_attempts: list[QuizAttempt] = Field(default_factory=list)
    error_records: list[ErrorRecord] = Field(default_factory=list)
    repetition_states: dict[str, RepetitionState] = Field(default_factory=dict)
    review_queue: list[ReviewTask] = Field(default_factory=list)
    # A single outstanding question; grading reads its expected answer so the
    # model never has to recall it across turns.
    pending_question: PendingQuestion | None = None
    feynman_retries: dict[str, int] = Field(default_factory=dict)
    feynman_explanations: dict[str, str] = Field(default_factory=dict)
    stage_failure_counts: dict[str, int] = Field(default_factory=dict)
    stage_failure_notes: dict[str, str] = Field(default_factory=dict)
    # ── Feynman learning v2 aggregates (append-only) ──
    attempts: list[FeynmanAttempt] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    rubric_assessments: list[RubricAssessment] = Field(default_factory=list)
    challenge_records: list[ChallengeRecord] = Field(default_factory=list)
    gaps: list[GapRecord] = Field(default_factory=list)
    projections: dict[str, KnowledgeStateProjection] = Field(default_factory=dict)
    source_snapshots: list[SourceSnapshot] = Field(default_factory=list)
    map_versions: list[KnowledgeMapVersion] = Field(default_factory=list)
    source_conflicts: list[SourceConflict] = Field(default_factory=list)
    # Evaluator configuration fixed on the learning path (§9.3). Resolved and
    # frozen into an ``EvaluatorSnapshot`` at attempt start; teaching-model
    # switches never change that snapshot.
    evaluator_profile_id: str = ""
    evaluator_model_id: str = ""
    evaluator_api_protocol: str = ""
    # Append-only LLM invocation audit (§7.8); entries are never overwritten.
    model_invocations: list[ModelInvocationRecord] = Field(default_factory=list)
    # ── Knowledge-card drafts and generation attempts (KB-02) ──
    # ``knowledge_cards`` is the mutable current-card projection list (at most
    # one occupying card per knowledge point); generation attempts are
    # append-only history. Legacy JSON without these fields still loads.
    knowledge_cards: list[KnowledgeCardRecord] = Field(default_factory=list)
    knowledge_card_generation_attempts: list[KnowledgeCardGenerationAttempt] = Field(
        default_factory=list
    )
    # ── Knowledge-card publication records (KB-03, append-only) ──
    # Durable publication history; entries are never overwritten or dropped
    # while the card projects current status.
    knowledge_card_publication_records: list[KnowledgeCardPublicationRecord] = Field(
        default_factory=list
    )
    # ── Knowledge-card retraction records (KB-04, append-only) ──
    # Durable retraction history; entries are never overwritten or dropped
    # while the card projects current retraction state.
    knowledge_card_retraction_records: list[KnowledgeCardRetractionRecord] = Field(
        default_factory=list
    )
    # Append-only audit trail; entries are never overwritten by later saves.
    history: list[HistoryEvent] = Field(default_factory=list)
    aggregate_versions: AggregateVersions = Field(default_factory=AggregateVersions)
    version: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


__all__ = [
    "KnowledgeType",
    "ErrorType",
    "LearningStage",
    "KnowledgePoint",
    "LearningModule",
    "DiagnosticResult",
    "QuizAttempt",
    "RetryAttempt",
    "ErrorRecord",
    "RepetitionState",
    "ReviewTask",
    "PendingQuestion",
    "AttemptCycleType",
    "AttemptStatus",
    "EvidenceKind",
    "InputMode",
    "MasteryState",
    "ReviewState",
    "HelpLevel",
    "SourceType",
    "ConflictStatus",
    "ChallengeMode",
    "ChallengeStatus",
    "GapStatus",
    "INVALIDATION_REASON_SOURCE_VERSION_CHANGED",
    "SourceCitation",
    "RubricScores",
    "ServerGateResult",
    "EvaluatorSnapshot",
    "ModelInvocationPurpose",
    "ModelInvocationStatus",
    "ModelInvocationUsage",
    "ModelInvocationRecord",
    "FeynmanAttempt",
    "EvidenceItem",
    "RubricAssessment",
    "ChallengeRecord",
    "GapRecord",
    "KnowledgeStateProjection",
    "SourceSnapshot",
    "KnowledgeMapVersion",
    "SourceConflict",
    "HistoryEvent",
    "AggregateVersions",
    "KnowledgeCardStatus",
    "DraftGenerationStatus",
    "GenerationAttemptStatus",
    "TERMINAL_GENERATION_ATTEMPT_STATUSES",
    "KNOWLEDGE_CARD_OCCUPYING_STATUSES",
    "STALEABLE_CARD_STATUSES",
    "KnowledgeCardRecord",
    "KnowledgeCardGenerationAttempt",
    "PublicationStatus",
    "KnowledgeCardPublicationRecord",
    "PublicationIntent",
    "RetractionStatus",
    "TERMINAL_RETRACTION_STATUSES",
    "KnowledgeCardRetractionRecord",
    "RetractionIntent",
    "LearningProgress",
]
