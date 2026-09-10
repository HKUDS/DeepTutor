from __future__ import annotations

from enum import Enum
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    # What this module is *for*, in one sentence, written when the outline was
    # designed. Two things read it: the learner, who otherwise sees a bare noun
    # where a purpose belongs, and ``mastery_revise``, which may only reshape
    # knowledge points in ways this sentence still covers. Empty means an
    # outline built before the field existed — every reader degrades to the
    # module name, so no migration is needed.
    objective: str = ""
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


class PendingOption(BaseModel):
    """One choice a mastery question offers: a stable label and its answer text.

    Two fields rather than one ``"A: body"`` string because they are two
    different things — the learner picks the label, the card renders the body,
    and grading compares labels. The flat string was inherited from the
    generic ``ask_user`` card, and it had to be split back apart with a regex
    on every read: that is how the maths option ``"x - 1 = 0"`` once
    registered as label ``X`` with the body ``"1 = 0"``. Mastery questions now
    carry the split the tutor made.
    """

    model_config = ConfigDict(extra="ignore")

    label: str
    body: str


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
    options: list[PendingOption] = Field(default_factory=list)
    # Reference explanation and difficulty, captured when the question is
    # posed. Server-side like ``expected_answer`` — ``public_pending_question``
    # never projects them, so an explanation cannot leak the answer into the
    # card the learner is about to answer. They travel with the attempt into
    # the question bank, which is what makes a mastery mistake reviewable
    # later instead of a bare right/wrong.
    explanation: str = ""
    difficulty: str = ""
    created_at: float = Field(default_factory=time.time)

    @field_validator("options", mode="before")
    @classmethod
    def _read_legacy_option_strings(cls, value: Any) -> Any:
        """Read the ``["A: body", …]`` rows written before options were split.

        The regex inference lives here, on the way in, so it runs once for a
        question stored by an older version instead of on every read — and
        never for a question posed since.
        """
        if not isinstance(value, list) or not value:
            return value
        if not all(isinstance(entry, str) for entry in value):
            return value
        from deeptutor.learning.pending import parse_options

        return [{"label": label, "body": body} for label, body in parse_options(value).items()]

    @property
    def choice_map(self) -> dict[str, str]:
        """The ``{label: body}`` form grading and the question bank compare on."""
        return {option.label: option.body for option in self.options}


class InteractionStatus(str, Enum):
    """Durable lifecycle for one learner-facing mastery interaction.

    The chat runtime may disappear at any point; this state is the source of
    truth for whether a question still needs an answer or has already been
    graded.  Terminal interactions are retained for idempotent retries and
    audit history.
    """

    REGISTERED = "registered"
    AWAITING_INPUT = "awaiting_input"
    ANSWERED = "answered"
    GRADED = "graded"
    ABANDONED = "abandoned"


class MasteryInteraction(BaseModel):
    """A persisted question/answer transaction for a mastery path."""

    model_config = ConfigDict(extra="ignore")

    interaction_id: str
    path_id: str
    question: PendingQuestion
    status: InteractionStatus = InteractionStatus.REGISTERED
    session_id: str = ""
    turn_id: str = ""
    user_answer: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class MasteryEvent(BaseModel):
    """Committed path event consumed by recovery and future live UIs."""

    model_config = ConfigDict(extra="ignore")

    id: int = 0
    path_id: str
    revision: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    created_at: float = Field(default_factory=time.time)


class MasteryPathLease(BaseModel):
    """The one active mutating turn allowed for a mastery path."""

    model_config = ConfigDict(extra="ignore")

    path_id: str
    session_id: str
    turn_id: str
    acquired_at: float = Field(default_factory=time.time)


class TopicSourceKind(str, Enum):
    """What a learner may point a mastery goal at.

    Everything DeepTutor already holds for them is fair game: their library
    (``BOOK``), their notes (``NOTEBOOK``), an indexed corpus or one document
    inside it (``KNOWLEDGE_BASE`` / ``FILE``), and — added with the mastery
    goal rework — the working history that shows what they have actually been
    doing: past conversations, their own wrong answers, drafts they are
    writing, and study partner transcripts.
    """

    GOAL = "goal"
    BOOK = "book"
    NOTEBOOK = "notebook"
    KNOWLEDGE_BASE = "knowledge_base"
    FILE = "file"
    #: One chat session. ``source_id`` is its session id, or a
    #: ``partner:{pid}:{session_key}`` reference for a study partner's.
    CHAT = "chat"
    #: One question-bank entry — a question the learner has already answered.
    #: ``source_id`` is its numeric entry id.
    QUESTION_BANK = "question_bank"
    #: One Co-Writer draft. ``source_id`` is the document id.
    COWRITER = "cowriter"
    #: One partner-group conversation, as ``{group_id}:{session_key}``.
    PARTNER_GROUP = "partner_group"


class TopicSource(BaseModel):
    """One ordered source selected while designing a learning topic."""

    model_config = ConfigDict(extra="ignore")

    id: str
    kind: TopicSourceKind
    source_id: str = ""
    label: str
    excerpt: str = ""
    position: int = 0
    available: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class TopicMetadata(BaseModel):
    """Product-level identity around the deterministic learning aggregate."""

    model_config = ConfigDict(extra="ignore")

    path_id: str
    goal: str = ""
    description: str = ""
    emoji: str = "🧭"
    map_seed: int = 0
    status: Literal["active", "archived"] = "active"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class MasteryTopic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metadata: TopicMetadata
    sources: list[TopicSource] = Field(default_factory=list)


class LearnerMasteryOverride(BaseModel):
    """Explicit learner claim that bypasses, but never impersonates, evidence."""

    model_config = ConfigDict(extra="ignore")

    knowledge_point_id: str
    note: str = ""
    created_at: float = Field(default_factory=time.time)


class LearnerProfile(BaseModel):
    """Who is learning this goal — collected once, honoured every turn.

    An outline used to be designed from the goal and the materials alone, so
    the same "I want to learn linear algebra" produced the same route for a
    second-year undergraduate and for a backend engineer with six evenings.
    These are the things only the learner knows; the tutor can read the
    material's own difficulty for itself.

    Every field is free text on purpose. The useful answer to "how much time do
    you have" is "两周，每天晚上一小时", not an enum the learner has to be
    translated into. Empty means never asked, which is why nothing here is
    required: a goal created before intake existed reads as a profile with
    nothing in it, and the tutor simply asks.
    """

    model_config = ConfigDict(extra="ignore")

    #: What they can already do — where the route should start, and where
    #: ``probe`` should aim.
    prior_knowledge: str = ""
    #: What "done" means to them. "Read papers in the field" and "implement it
    #: myself" are different routes over the same subject.
    target_level: str = ""
    #: How much time they have. Sizes the outline.
    time_budget: str = ""
    #: How they want it taught — language, worked examples over prose,
    #: intuition before formalism.
    preferences: str = ""
    #: Anything else worth carrying that the four fields above do not hold.
    notes: str = ""
    updated_at: float = Field(default_factory=time.time)

    def is_empty(self) -> bool:
        """Whether intake has produced nothing yet."""
        return not any(
            (
                self.prior_knowledge.strip(),
                self.target_level.strip(),
                self.time_budget.strip(),
                self.preferences.strip(),
                self.notes.strip(),
            )
        )


class LearningProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    book_id: str
    # Who is learning this goal. Absent on every path created before intake
    # existed, and on any goal whose learner has not been asked yet — readers
    # treat both the same way, so no migration is needed.
    learner_profile: LearnerProfile | None = None
    # The learner-facing name of this path. Empty means "never named": the
    # display name is then derived (``policy.path_display_name``), which is how
    # every path behaved before this field existed — so an aggregate persisted
    # without it needs no migration.
    name: str = ""
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
    # A learner may explicitly claim prior mastery.  Policy exposes this as a
    # separate provenance (``mastery_source=learner``); assessed mastery and
    # its evidence remain untouched and can take over later.
    learner_mastery_overrides: dict[str, LearnerMasteryOverride] = Field(default_factory=dict)
    # A single outstanding question; grading reads its expected answer so the
    # model never has to recall it across turns.
    pending_question: PendingQuestion | None = None
    feynman_retries: dict[str, int] = Field(default_factory=dict)
    feynman_explanations: dict[str, str] = Field(default_factory=dict)
    stage_failure_counts: dict[str, int] = Field(default_factory=dict)
    stage_failure_notes: dict[str, str] = Field(default_factory=dict)
    version: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


__all__ = [
    "LearnerProfile",
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
    "InteractionStatus",
    "MasteryInteraction",
    "MasteryEvent",
    "MasteryPathLease",
    "TopicSourceKind",
    "TopicSource",
    "TopicMetadata",
    "MasteryTopic",
    "LearnerMasteryOverride",
    "LearningProgress",
]
