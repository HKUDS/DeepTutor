"""Stable value objects for turn and background-runtime coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Any
import uuid


class TurnStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TurnFailureCode(StrEnum):
    WORKER_LOST = "worker_lost"
    LEASE_LOST = "lease_lost"
    COORDINATION_UNAVAILABLE = "coordination_unavailable"
    PROVIDER_ERROR = "provider_error"
    INTERNAL_ERROR = "internal_error"
    REJECTED = "rejected"
    SERVER_SHUTDOWN = "server_shutdown"


class TurnCommandKind(StrEnum):
    CANCEL = "cancel"
    SUBMIT_USER_REPLY = "submit_user_reply"
    USER_INPUT = "user_input"


class BackgroundCommandKind(StrEnum):
    CRON_RELOAD = "cron_reload"
    PARTNER_START = "partner_start"
    PARTNER_STOP = "partner_stop"
    PARTNER_RELOAD = "partner_reload"


@dataclass(frozen=True, slots=True)
class TurnLease:
    turn_id: str
    session_id: str
    owner_id: str
    fencing_token: int
    expires_at: float


@dataclass(frozen=True, slots=True)
class LeaderLease:
    owner_id: str
    fencing_token: int
    expires_at: float


@dataclass(frozen=True, slots=True)
class TurnCommand:
    command_id: str
    turn_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        turn_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> "TurnCommand":
        return cls(
            command_id=command_id or f"cmd_{uuid.uuid4().hex}",
            turn_id=turn_id,
            kind=kind,
            payload=dict(payload or {}),
        )


@dataclass(frozen=True, slots=True)
class BackgroundCommand:
    command_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> "BackgroundCommand":
        return cls(
            command_id=command_id or f"bgcmd_{uuid.uuid4().hex}",
            kind=kind,
            payload=dict(payload or {}),
        )


__all__ = [
    "BackgroundCommand",
    "BackgroundCommandKind",
    "LeaderLease",
    "TurnCommand",
    "TurnCommandKind",
    "TurnFailureCode",
    "TurnLease",
    "TurnStatus",
]
