"""Domain models for first-class groups of DeepTutor Partners."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class PartnerGroupConfig:
    group_id: str
    owner_id: str
    name: str
    description: str = ""
    member_ids: list[str] = field(default_factory=list)
    discussion_mode: str = "panel_parallel"
    shared_memory: str = "whiteboard"
    emoji: str = "👥"
    color: str = "#6366f1"
    created_at: str = ""
    updated_at: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GroupMessage:
    event_id: str
    turn_id: str
    session_key: str
    role: str
    content: str
    author_id: str
    author_name: str
    created_at: str
    mentions: list[str] = field(default_factory=list)
    error: bool = False
    kind: str = "message"
    events: list[dict[str, Any]] = field(default_factory=list)
    invocation_id: str = ""
    invocation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GroupTurnResult:
    turn_id: str
    targets: list[str]
    user_message: GroupMessage
    replies: list[GroupMessage]
    unknown_mentions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "targets": self.targets,
            "user_message": self.user_message.to_dict(),
            "replies": [reply.to_dict() for reply in self.replies],
            "unknown_mentions": list(self.unknown_mentions),
        }


@dataclass(frozen=True, slots=True)
class GroupSessionSummary:
    session_key: str
    title: str
    message_count: int
    updated_at: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PartnerInvocation:
    """Durable approval state for one proposed Partner-to-Partner question."""

    invocation_id: str
    group_id: str
    session_key: str
    parent_turn_id: str
    requester_partner_id: str
    requester_partner_name: str
    target_partner_id: str
    target_partner_name: str
    question: str
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    question_event_id: str = ""
    reply_event_id: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "GroupMessage",
    "GroupSessionSummary",
    "GroupTurnResult",
    "PartnerGroupConfig",
    "PartnerInvocation",
    "utc_now",
]
