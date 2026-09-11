"""Canonical v2 wire models for the browser turn protocol."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deeptutor.app.contracts import TurnRequest

PROTOCOL_VERSION: Literal["2.0"] = "2.0"
MINIMUM_WEB_PROTOCOL_VERSION: Literal["2.0"] = "2.0"


class TurnStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TurnQueryState(str, Enum):
    """Client observation state, including server-side recovery windows."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TurnFailureCode(str, Enum):
    WORKER_LOST = "worker_lost"
    LEASE_LOST = "lease_lost"
    COORDINATION_UNAVAILABLE = "coordination_unavailable"
    PROVIDER_ERROR = "provider_error"
    INTERNAL_ERROR = "internal_error"
    REJECTED = "rejected"
    SERVER_SHUTDOWN = "server_shutdown"


class StreamEventType(str, Enum):
    STAGE_START = "stage_start"
    STAGE_END = "stage_end"
    THINKING = "thinking"
    OBSERVATION = "observation"
    CONTENT = "content"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PROGRESS = "progress"
    SOURCES = "sources"
    RESULT = "result"
    ERROR = "error"
    SESSION = "session"
    SESSION_META = "session_meta"
    WAIT_FOR_INPUT = "wait_for_input"
    DONE = "done"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartTurnCommand(TurnRequest):
    type: Literal["message", "start_turn"] = "start_turn"
    protocol_version: Literal["2.0"]


class SubscribeTurnCommand(WireModel):
    type: Literal["subscribe_turn"] = "subscribe_turn"
    turn_id: str = Field(min_length=1)
    after_seq: int = Field(default=0, ge=0)
    protocol_version: Literal["2.0"]


class SubscribeSessionCommand(WireModel):
    type: Literal["subscribe_session"] = "subscribe_session"
    session_id: str = Field(min_length=1)
    after_seq: int = Field(default=0, ge=0)
    protocol_version: Literal["2.0"]


class ResumeTurnCommand(WireModel):
    type: Literal["resume_from"] = "resume_from"
    turn_id: str = Field(min_length=1)
    seq: int = Field(default=0, ge=0)
    protocol_version: Literal["2.0"]


class UnsubscribeCommand(WireModel):
    type: Literal["unsubscribe"] = "unsubscribe"
    turn_id: str | None = None
    session_id: str | None = None
    protocol_version: Literal["2.0"]

    @model_validator(mode="after")
    def _has_target(self) -> "UnsubscribeCommand":
        if not self.turn_id and not self.session_id:
            raise ValueError("unsubscribe requires turn_id or session_id")
        return self


class CancelTurnCommand(WireModel):
    type: Literal["cancel_turn"] = "cancel_turn"
    turn_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    protocol_version: Literal["2.0"]


class RegenerateCommand(WireModel):
    type: Literal["regenerate"] = "regenerate"
    session_id: str = Field(min_length=1)
    overrides: dict[str, Any] = Field(default_factory=dict)
    protocol_version: Literal["2.0"]


class UserAnswer(WireModel):
    questionId: str = Field(min_length=1)
    text: str = ""


class SubmitUserReplyCommand(WireModel):
    type: Literal["submit_user_reply"] = "submit_user_reply"
    turn_id: str = Field(min_length=1)
    text: str | None = None
    answers: list[UserAnswer] | None = None
    command_id: str = Field(min_length=1)
    protocol_version: Literal["2.0"]

    @model_validator(mode="after")
    def _has_reply(self) -> "SubmitUserReplyCommand":
        if self.text is None and not self.answers:
            raise ValueError("submit_user_reply requires text or answers")
        return self


class UserInputCommand(WireModel):
    type: Literal["user_input"] = "user_input"
    turn_id: str = Field(min_length=1)
    content: str
    command_id: str = Field(min_length=1)
    protocol_version: Literal["2.0"]


class CheckActiveTurnCommand(WireModel):
    type: Literal["check_active_turn"] = "check_active_turn"
    session_id: str = Field(min_length=1)
    protocol_version: Literal["2.0"]


class PingCommand(WireModel):
    type: Literal["ping"] = "ping"
    protocol_version: Literal["2.0"]


ClientCommand = Annotated[
    StartTurnCommand
    | SubscribeTurnCommand
    | SubscribeSessionCommand
    | ResumeTurnCommand
    | UnsubscribeCommand
    | CancelTurnCommand
    | RegenerateCommand
    | SubmitUserReplyCommand
    | UserInputCommand
    | CheckActiveTurnCommand
    | PingCommand,
    Field(discriminator="type"),
]


class StreamEvent(WireModel):
    type: StreamEventType
    source: str = ""
    stage: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    turn_id: str = ""
    seq: int = Field(default=0, ge=0)
    timestamp: float
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION


class ActiveTurnInfo(WireModel):
    type: Literal["active_turn_info"] = "active_turn_info"
    turn_id: str = ""
    status: TurnQueryState | Literal["none"] = "none"
    owner_id: str = ""
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION


class PongEvent(WireModel):
    type: Literal["pong"] = "pong"
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION


class CommandAckEvent(WireModel):
    type: Literal["command_ack"] = "command_ack"
    command_id: str = Field(min_length=1)
    command_type: Literal["cancel_turn", "submit_user_reply", "user_input"]
    accepted: bool
    turn_id: str = ""
    error_code: str = ""
    message: str = ""
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION


class ProtocolErrorEvent(WireModel):
    type: Literal["protocol_error"] = "protocol_error"
    error_code: str = Field(min_length=1)
    message: str
    retryable: bool = False
    session_id: str = ""
    turn_id: str = ""
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION


ServerEvent = StreamEvent | ActiveTurnInfo | PongEvent | CommandAckEvent | ProtocolErrorEvent


class TurnSummary(WireModel):
    id: str
    session_id: str
    status: TurnStatus
    query_state: TurnQueryState | None = None
    capability: str = ""
    owner_id: str = ""
    last_seq: int = Field(default=0, ge=0)
    error: str = ""
    error_code: TurnFailureCode | None = None
    retryable: bool = False
    created_at: float | None = None
    updated_at: float | None = None


class SessionSummary(WireModel):
    id: str
    title: str
    created_at: float | None = None
    updated_at: float | None = None
    active_turn: TurnSummary | None = None


class SessionDetail(SessionSummary):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)


class RuntimeStatus(WireModel):
    worker_id: str
    worker_count: int = Field(ge=1)
    coordination_mode: Literal["memory", "redis"]
    redis_configured: bool
    redis_status: Literal["ok", "unavailable", "not_configured"]
    leader_id: str | None = None
    leader_healthy: bool | None = None
    owner_turn_count: int = Field(default=0, ge=0)
    recovery_backlog: int = Field(default=0, ge=0)
    lease_ttl_seconds: int = Field(ge=1)
    renew_interval_seconds: int = Field(ge=1)
    recovery_interval_seconds: int = Field(ge=1)
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION
    minimum_web_protocol_version: Literal["2.0"] = MINIMUM_WEB_PROTOCOL_VERSION


class ErrorEnvelope(WireModel):
    error_code: str
    message: str
    retryable: bool = False
    correlation_id: str | None = None


class TurnProtocolDocument(WireModel):
    protocol_version: Literal["2.0"] = PROTOCOL_VERSION
    minimum_web_protocol_version: Literal["2.0"] = MINIMUM_WEB_PROTOCOL_VERSION
    client_command: ClientCommand
    server_event: ServerEvent
    runtime_status: RuntimeStatus
    session_summary: SessionSummary
    session_detail: SessionDetail
    error: ErrorEnvelope


__all__ = [
    "ActiveTurnInfo",
    "ClientCommand",
    "CommandAckEvent",
    "ErrorEnvelope",
    "MINIMUM_WEB_PROTOCOL_VERSION",
    "PROTOCOL_VERSION",
    "ProtocolErrorEvent",
    "RuntimeStatus",
    "ServerEvent",
    "SessionDetail",
    "SessionSummary",
    "StreamEvent",
    "StreamEventType",
    "TurnFailureCode",
    "TurnProtocolDocument",
    "TurnQueryState",
    "TurnStatus",
    "TurnSummary",
]
