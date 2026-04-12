"""Pydantic models for Goal-Oriented Adaptive Learning Mode."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GoalLevel(str, Enum):
    FOUNDATION = "foundation"
    COMPETENT = "competent"
    ADVANCED = "advanced"


class PlanningStrategy(str, Enum):
    DEPTH_FIRST = "depth_first"
    BREADTH_FIRST = "breadth_first"
    HIGH_YIELD_FIRST = "high_yield_first"


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    FAILED = "failed"


class NodeType(str, Enum):
    CONCEPT = "concept"
    CHAPTER = "chapter"
    SKILL = "skill"


class EdgeType(str, Enum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    CONTAINS = "contains"


class TaskKind(str, Enum):
    LEARN = "learn"
    PRACTICE = "practice"
    REVIEW = "review"
    QUIZ = "quiz"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


class CompletionStatus(str, Enum):
    DONE = "done"
    PARTIAL = "partial"
    MISSED = "missed"
    SKIPPED = "skipped"


class ScopeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapters: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    exclude_topics: list[str] = Field(default_factory=list)


class PreferencesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: PlanningStrategy = PlanningStrategy.HIGH_YIELD_FIRST
    include_practice: bool = True
    practice_ratio: float = 0.4
    review_ratio: float = 0.2
    language: str = "zh"

    @field_validator("practice_ratio", "review_ratio")
    @classmethod
    def validate_ratio(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("ratio must be between 0 and 1")
        return value


class GoalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_level: GoalLevel
    remaining_days: int = 7
    daily_minutes: int
    days_per_week: int = 7
    kb_name: str | None = None
    goal_statement: str = ""
    scope: ScopeConfig = Field(default_factory=ScopeConfig)
    preferences: PreferencesConfig = Field(default_factory=PreferencesConfig)

    @field_validator("remaining_days", "daily_minutes", "days_per_week")
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @field_validator("days_per_week")
    @classmethod
    def validate_days_per_week(cls, value: int) -> int:
        if value > 7:
            raise ValueError("days_per_week must be <= 7")
        return value


class GoalMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_rate: float = 0.0
    avg_quiz_accuracy: float = 0.0
    replan_count: int = 0


class GoalArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_dir: str
    session_json: str = "session.json"
    plan_json: str | None = None
    graph_json: str | None = None
    events_jsonl: str = "events.jsonl"


class GoalSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    kb_name: str
    goal_config: GoalConfig
    status: SessionStatus = SessionStatus.CREATED
    plan_id: str | None = None
    plan_version: int = 0
    current_day_index: int = 1
    metrics: GoalMetrics = Field(default_factory=GoalMetrics)
    artifacts: GoalArtifacts

    @field_validator("plan_version", "current_day_index")
    @classmethod
    def non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value


class WeightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    snippet: str


class KnowledgeNodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    aliases: list[str] = Field(default_factory=list)
    evidence: list[WeightEvidence] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    node_type: NodeType = NodeType.CONCEPT
    estimated_minutes: int = 30
    doc_freq: float = 0.0
    practice_freq: float = 0.0
    heading_score: float = 0.0
    weakness_score: float = 0.0
    prerequisites: list[str] = Field(default_factory=list)


class KnowledgeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    node_type: NodeType = NodeType.CONCEPT
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    estimated_minutes: int = 30
    weight: float = 0.0
    weight_evidence: list[WeightEvidence] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)

    @field_validator("estimated_minutes")
    @classmethod
    def validate_minutes(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("estimated_minutes must be > 0")
        return value


class KnowledgeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_: str = Field(alias="from")
    to: str
    edge_type: EdgeType
    weight: float = 1.0


class TaskResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    ref: str


class PracticeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    difficulty: str
    question_type: str
    count: int


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    day_index: int
    node_id: str
    title: str
    kind: TaskKind
    objective: str
    estimate_minutes: int
    priority: int = 1
    resources: list[TaskResource] = Field(default_factory=list)
    practice_spec: PracticeSpec | None = None
    status: TaskStatus = TaskStatus.PENDING
    outputs: list[str] = Field(default_factory=list)
    optional: bool = False

    @field_validator("day_index", "estimate_minutes")
    @classmethod
    def positive_task_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be > 0")
        return value


class QuizResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int
    total: int

    @model_validator(mode="after")
    def validate_score(self) -> "QuizResult":
        if self.total <= 0:
            raise ValueError("total must be > 0")
        if self.score < 0 or self.score > self.total:
            raise ValueError("score must be between 0 and total")
        return self


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str
    session_id: str
    task_id: str
    completion: CompletionStatus
    actual_minutes: int | None = None
    quiz: QuizResult | None = None
    reflection: str = ""
    timestamp: str

    @field_validator("actual_minutes")
    @classmethod
    def validate_actual_minutes(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("actual_minutes must be >= 0")
        return value


class PlanDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_index: int
    date: str | None = None
    budget_minutes: int
    task_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class DayPlanTimeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    title: str
    kind: TaskKind
    minutes: int
    steps: list[str] = Field(default_factory=list)
    linked_task_ids: list[str] = Field(default_factory=list)


class DayPlanDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    day_index: int
    date: str | None = None
    objective_summary: str
    time_blocks: list[DayPlanTimeBlock] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    review_actions: list[str] = Field(default_factory=list)
    linked_task_ids: list[str] = Field(default_factory=list)


class PlanDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added_tasks: list[str] = Field(default_factory=list)
    moved_tasks: list[str] = Field(default_factory=list)
    dropped_tasks: list[str] = Field(default_factory=list)


class PlanArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_dir: str
    plan_json: str = "plan.json"
    graph_json: str = "graph.json"
    events_jsonl: str = "events.jsonl"


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    plan_id: str
    session_id: str
    kb_name: str
    plan_version: int
    status: PlanStatus = PlanStatus.READY
    knowledge_nodes: list[KnowledgeNode] = Field(default_factory=list)
    knowledge_edges: list[KnowledgeEdge] = Field(default_factory=list)
    days: list[PlanDay]
    tasks: list[Task]
    diff: PlanDiff | None = None
    artifacts: PlanArtifacts

    @field_validator("plan_version")
    @classmethod
    def validate_plan_version(cls, value: int) -> int:
        if value < 0:
            raise ValueError("plan_version must be >= 0")
        return value

    @model_validator(mode="after")
    def ensure_required_collections(self) -> "Plan":
        if not self.session_id:
            raise ValueError("session_id is required")
        if self.days is None:
            raise ValueError("days is required")
        if self.tasks is None:
            raise ValueError("tasks is required")
        return self


def model_to_dict(model: BaseModel) -> dict[str, Any]:
    """Serialize a pydantic model using JSON-compatible values."""

    return model.model_dump(mode="json", by_alias=True)
