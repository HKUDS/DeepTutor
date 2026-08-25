"""Domain records for Invidious <-> DeepTutor remote video learning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


CommandType = Literal["pause", "play", "seek"]
CommandStatus = Literal["pending", "acked", "failed", "expired"]
PlaybackState = Literal["playing", "paused", "buffering", "ended", "unknown"]


@dataclass(slots=True)
class Pairing:
    pairing_id: str
    code: str
    claim_secret: str
    created_at: str
    expires_at: str
    claimed: bool = False
    claimed_at: str | None = None
    owner_id: str | None = None
    device_id: str | None = None


@dataclass(slots=True)
class Device:
    device_id: str
    owner_id: str
    device_name: str
    device_kind: str
    paired_at: str
    last_seen: str
    active: bool = True


@dataclass(slots=True)
class PlayerSession:
    session_id: str
    owner_id: str
    device_id: str
    instance_origin: str
    video_id: str
    title: str
    position_ms: int
    duration_ms: int
    playback_state: PlaybackState
    playback_rate: float
    updated_at: str
    last_heartbeat_at: str


@dataclass(slots=True)
class PlayerCommand:
    command_id: str
    session_id: str
    owner_id: str
    device_id: str
    command_type: CommandType
    payload: dict[str, Any] = field(default_factory=dict)
    status: CommandStatus = "pending"
    created_at: str = ""
    acked_at: str | None = None
    error: str | None = None


@dataclass(slots=True)
class VideoNote:
    note_id: str
    owner_id: str
    source: str
    instance_origin: str
    video_id: str
    title: str
    position_ms: int
    body: str
    created_at: str
    updated_at: str
