"""HTTP bridge for Invidious player remote control and iPhone notes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.path_service import PathService, get_path_service
from deeptutor.video_learning.store import (
    VideoLearningConflict,
    VideoLearningNotFound,
    VideoLearningStore,
    default_db_path,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_auth = [Depends(require_auth)]


def _session_db_path() -> Path:
    return default_db_path(path_service=get_path_service())


def _device_db_path() -> Path:
    return default_db_path(path_service=PathService.get_instance())


def _store_for_session() -> VideoLearningStore:
    if _session_db_path() != _device_db_path():
        raise HTTPException(
            501,
            "Video learning remote control is not available for this account yet: "
            "pairing and device sync would resolve different workspaces.",
        )
    return VideoLearningStore(_session_db_path())


def _owner_id() -> str:
    return get_current_user().id


def _auth_device(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    if not authorization or not authorization.startswith("VideoLearning "):
        raise HTTPException(401, "Missing or malformed Authorization header.")
    raw = authorization[len("VideoLearning ") :]
    if ":" not in raw:
        raise HTTPException(401, "Invalid Authorization format.")
    device_id, token = raw.split(":", 1)
    store = VideoLearningStore.open_existing(_device_db_path())
    if store is None:
        raise HTTPException(403, "Invalid device credentials.")
    device = store.verify_token(device_id, token)
    if device is None:
        raise HTTPException(403, "Invalid device credentials.")
    store.touch_device(device_id)
    return device, store


def _validate_origin(value: str) -> str:
    raw = (value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "instance_origin must be an absolute http(s) origin.")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise HTTPException(400, "instance_origin must not include a path or query.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, VideoLearningNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, VideoLearningConflict):
        return HTTPException(409, str(exc))
    return HTTPException(400, str(exc))


class ClaimPairingRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)
    device_name: str = Field("iPad", max_length=128)
    device_kind: str = Field("ipad", max_length=32)


class PlayerSyncRequest(BaseModel):
    session_id: str | None = Field(None, max_length=64)
    instance_origin: str = Field(..., max_length=256)
    video_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field("", max_length=512)
    position_ms: int = Field(0, ge=0)
    duration_ms: int = Field(0, ge=0)
    playback_state: str = Field("unknown", max_length=32)
    playback_rate: float = Field(1.0, gt=0, le=4)


class CommandRequest(BaseModel):
    command_id: str | None = Field(None, max_length=64)
    type: str = Field(..., max_length=16)
    position_ms: int | None = Field(None, ge=0)
    delta_ms: int | None = None


class CommandAckRequest(BaseModel):
    ok: bool = True
    error: str | None = Field(None, max_length=512)


class NoteCreateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)
    position_ms: int | None = Field(None, ge=0)
    title: str = Field("", max_length=512)
    source: str = Field("invidious", max_length=64)
    instance_origin: str = Field("", max_length=256)
    video_id: str | None = Field(None, max_length=64)
    session_id: str | None = Field(None, max_length=64)


class NoteUpdateRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


@router.post("/pairings")
async def create_pairing() -> dict[str, Any]:
    """Create a short-lived pairing code for an Invidious player tab."""
    store = VideoLearningStore(_device_db_path())
    pairing = store.create_pairing()
    return {
        "pairing_id": pairing.pairing_id,
        "code": pairing.code,
        "claim_secret": pairing.claim_secret,
        "expires_at": pairing.expires_at,
    }


@router.get("/pairings/{pairing_id}/status")
async def pairing_status(
    pairing_id: str,
    claim_secret: str,
) -> dict[str, Any]:
    store = VideoLearningStore.open_existing(_device_db_path())
    if store is None:
        raise HTTPException(404, "Pairing not found.")
    try:
        return store.pairing_status(pairing_id, claim_secret)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc


@router.post("/pairings/claim", dependencies=_auth)
async def claim_pairing(body: ClaimPairingRequest) -> dict[str, Any]:
    store = _store_for_session()
    try:
        pairing, device, _token = store.claim_pairing(
            code=body.code,
            owner_id=_owner_id(),
            device_name=body.device_name,
            device_kind=body.device_kind,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "pairing_id": pairing.pairing_id,
        "device_id": device.device_id,
        "device_name": device.device_name,
        "device_kind": device.device_kind,
        "owner_id": device.owner_id,
        "status": "claimed",
    }


@router.get("/devices", dependencies=_auth)
async def list_devices() -> list[dict[str, Any]]:
    store = _store_for_session()
    return [
        {
            "device_id": d.device_id,
            "device_name": d.device_name,
            "device_kind": d.device_kind,
            "paired_at": d.paired_at,
            "last_seen": d.last_seen,
            "active": d.active,
        }
        for d in store.list_devices(_owner_id())
    ]


@router.delete("/devices/{device_id}", dependencies=_auth)
async def revoke_device(device_id: str) -> dict[str, str]:
    store = _store_for_session()
    if not store.revoke_device(_owner_id(), device_id):
        raise HTTPException(404, "Device not found.")
    return {"status": "revoked", "device_id": device_id}


@router.post("/player/sync")
async def player_sync(
    body: PlayerSyncRequest,
    auth=Depends(_auth_device),
) -> dict[str, Any]:
    device, store = auth
    origin = _validate_origin(body.instance_origin)
    session = store.upsert_session(
        device=device,
        session_id=body.session_id,
        instance_origin=origin,
        video_id=body.video_id.strip(),
        title=body.title,
        position_ms=body.position_ms,
        duration_ms=body.duration_ms,
        playback_state=body.playback_state,
        playback_rate=body.playback_rate,
    )
    commands = store.pending_commands(device.device_id, session.session_id)
    return {
        "session": {
            "session_id": session.session_id,
            "video_id": session.video_id,
            "title": session.title,
            "position_ms": session.position_ms,
            "duration_ms": session.duration_ms,
            "playback_state": session.playback_state,
            "playback_rate": session.playback_rate,
            "updated_at": session.updated_at,
            "online": True,
        },
        "commands": [
            {
                "command_id": c.command_id,
                "type": c.command_type,
                "payload": c.payload,
                "created_at": c.created_at,
            }
            for c in commands
        ],
    }


@router.post("/player/commands/{command_id}/ack")
async def ack_player_command(
    command_id: str,
    body: CommandAckRequest,
    auth=Depends(_auth_device),
) -> dict[str, Any]:
    device, store = auth
    try:
        command = store.ack_command(
            device_id=device.device_id,
            command_id=command_id,
            ok=body.ok,
            error=body.error,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "command_id": command.command_id,
        "status": command.status,
        "acked_at": command.acked_at,
        "error": command.error,
    }


@router.get("/sessions", dependencies=_auth)
async def list_sessions() -> dict[str, Any]:
    store = _store_for_session()
    return {"sessions": store.list_sessions(_owner_id())}


@router.post("/sessions/{session_id}/commands", dependencies=_auth)
async def create_session_command(session_id: str, body: CommandRequest) -> dict[str, Any]:
    store = _store_for_session()
    session = store.get_session(session_id, _owner_id())
    if session is None:
        raise HTTPException(404, "Session not found.")
    payload: dict[str, Any] = {}
    command_type = body.type
    if command_type == "seek":
        if body.position_ms is not None:
            payload["position_ms"] = body.position_ms
        elif body.delta_ms is not None:
            payload["position_ms"] = max(0, session.position_ms + int(body.delta_ms))
        else:
            raise HTTPException(400, "seek requires position_ms or delta_ms.")
        command_type = "seek"
    try:
        command = store.enqueue_command(
            session=session,
            command_type=command_type,
            payload=payload,
            command_id=body.command_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "command_id": command.command_id,
        "type": command.command_type,
        "payload": command.payload,
        "status": command.status,
        "created_at": command.created_at,
    }


@router.get("/sessions/{session_id}/commands/{command_id}", dependencies=_auth)
async def get_session_command(session_id: str, command_id: str) -> dict[str, Any]:
    store = _store_for_session()
    command = store.get_command(command_id, _owner_id())
    if command is None or command.session_id != session_id:
        raise HTTPException(404, "Command not found.")
    return {
        "command_id": command.command_id,
        "type": command.command_type,
        "payload": command.payload,
        "status": command.status,
        "created_at": command.created_at,
        "acked_at": command.acked_at,
        "error": command.error,
    }


@router.get("/videos/{video_id}/notes", dependencies=_auth)
async def list_video_notes(video_id: str) -> dict[str, Any]:
    store = _store_for_session()
    notes = store.list_notes(_owner_id(), video_id)
    return {
        "notes": [
            {
                "note_id": n.note_id,
                "video_id": n.video_id,
                "title": n.title,
                "position_ms": n.position_ms,
                "body": n.body,
                "source": n.source,
                "instance_origin": n.instance_origin,
                "created_at": n.created_at,
                "updated_at": n.updated_at,
            }
            for n in notes
        ]
    }


@router.post("/videos/{video_id}/notes", dependencies=_auth, status_code=201)
async def create_video_note(video_id: str, body: NoteCreateRequest) -> dict[str, Any]:
    store = _store_for_session()
    position_ms = body.position_ms
    title = body.title
    instance_origin = body.instance_origin
    if body.session_id:
        session = store.get_session(body.session_id, _owner_id())
        if session is None:
            raise HTTPException(404, "Session not found.")
        if session.video_id != video_id:
            raise HTTPException(409, "session video_id mismatch.")
        if position_ms is None:
            position_ms = session.position_ms
        title = title or session.title
        instance_origin = instance_origin or session.instance_origin
    if position_ms is None:
        raise HTTPException(400, "position_ms is required when no live session is provided.")
    try:
        note = store.create_note(
            owner_id=_owner_id(),
            video_id=video_id,
            position_ms=position_ms,
            body=body.body,
            title=title,
            source=body.source,
            instance_origin=instance_origin,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "note_id": note.note_id,
        "video_id": note.video_id,
        "title": note.title,
        "position_ms": note.position_ms,
        "body": note.body,
        "source": note.source,
        "instance_origin": note.instance_origin,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


@router.patch("/notes/{note_id}", dependencies=_auth)
async def update_note(note_id: str, body: NoteUpdateRequest) -> dict[str, Any]:
    store = _store_for_session()
    try:
        note = store.update_note(_owner_id(), note_id, body.body)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "note_id": note.note_id,
        "video_id": note.video_id,
        "title": note.title,
        "position_ms": note.position_ms,
        "body": note.body,
        "updated_at": note.updated_at,
    }


@router.delete("/notes/{note_id}", dependencies=_auth)
async def delete_note(note_id: str) -> dict[str, bool]:
    store = _store_for_session()
    if not store.delete_note(_owner_id(), note_id):
        raise HTTPException(404, "Note not found.")
    return {"deleted": True}
