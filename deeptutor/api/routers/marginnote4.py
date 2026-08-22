"""HTTP bridge for MarginNote 4 Add-on devices.

The MN4 Add-on (JavaScript running inside MarginNote 4) calls these endpoints
to pair with this DeepTutor instance and push synced study data.

Authentication layers:
* ``/pair``, ``/devices``, ``/status`` -- DeepTutor session auth (the logged-in
  user manages their own devices). The router is mounted with ``_auth`` in
  ``main.py``.
* ``/sync``, ``/heartbeat`` -- device-token auth via
  ``Authorization: MarginNote <device_id>:<token>``. The Add-on stores the
  token received at pairing time.

Phase 1 scope: device pairing, incremental sync, heartbeat. Write-back to MN4
(propose / apply / verify) is Phase 2.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.capabilities.marginnote4.models import MarginNoteObject, SyncBatch
from deeptutor.capabilities.marginnote4.store import MarginNoteStore, resolve_db_path
from deeptutor.services.path_service import PathService

logger = logging.getLogger(__name__)
router = APIRouter()
_auth = [Depends(require_auth)]

# Upper bound on objects (and tombstones) accepted from one sync request.
MAX_SYNC_BATCH = 2000


def _requested_kb(request: Request) -> str:
    """The MN4 library this request addresses.

    In Phase 1 a single default store serves all devices; ``X-MN4-KB`` selects
    a dedicated database instead. The header is only a *selector* — the device
    token is the credential, and it is checked against whichever store the
    header names, so naming another library grants nothing.
    """
    return request.headers.get("x-mn4-kb", "default")


def _device_db_path(kb_name: str) -> Path:
    """The database the device-token endpoints address.

    Those endpoints carry no session, so ``get_path_service()`` would hand them
    whatever the ambient context happens to be — the default workspace in
    practice. Naming it explicitly keeps the sync path from drifting away from
    the store pairing wrote to, and gives :func:`pair_device` something to
    check itself against.
    """
    return resolve_db_path(kb_name, path_service=PathService.get_instance())


def _store_for(request: Request) -> MarginNoteStore:
    """Resolve (creating if absent) the store for a session-authenticated call."""
    return MarginNoteStore(resolve_db_path(_requested_kb(request)))


def _auth_device(request: Request, authorization: str | None) -> tuple[str, MarginNoteStore]:
    """Validate the device token and return ``(device_id, store)``.

    Reached with no session, so nothing here may create state from
    caller-supplied input: ``open_existing`` keeps an unauthenticated request
    from materialising a directory and a schema'd database per distinct
    ``X-MN4-KB`` value.
    """
    if not authorization or not authorization.startswith("MarginNote "):
        raise HTTPException(401, "Missing or malformed Authorization header.")
    raw = authorization[len("MarginNote ") :]
    if ":" not in raw:
        raise HTTPException(401, "Invalid Authorization format.")
    device_id, token = raw.split(":", 1)
    store = MarginNoteStore.open_existing(_device_db_path(_requested_kb(request)))
    if store is None or not store.verify_token(device_id, token):
        raise HTTPException(403, "Invalid device credentials.")
    store.touch_device(device_id)
    return device_id, store


# -- request / response models ---------------------------------------------


class PairRequest(BaseModel):
    device_name: str = Field("", max_length=128)
    device_kind: str = Field("macos", max_length=32)


class PairResponse(BaseModel):
    device_id: str
    token: str
    device_name: str
    device_kind: str


class SyncObjectIn(BaseModel):
    object_id: str
    object_type: str
    title: str = ""
    content: str = ""
    excerpt: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page: int | None = None
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    color: str | None = None
    created_at: str = ""
    updated_at: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class SyncRequest(BaseModel):
    # One batch, not one library: the Add-on pages through its backlog, so an
    # unbounded list only ever meant a token holder could pin the event loop
    # and the database on a single request.
    cursor: str = Field("", max_length=256)
    objects: list[SyncObjectIn] = Field(default_factory=list, max_length=MAX_SYNC_BATCH)
    deleted_ids: list[str] = Field(default_factory=list, max_length=MAX_SYNC_BATCH)


class SyncResponse(BaseModel):
    stored: int
    updated: int
    deleted: int
    new_cursor: str


class DeviceInfo(BaseModel):
    device_id: str
    device_name: str
    device_kind: str
    paired_at: str
    last_seen: str
    active: bool


# -- session-authenticated endpoints (DeepTutor user) -----------------------


@router.post("/pair", response_model=PairResponse, dependencies=_auth)
async def pair_device(body: PairRequest, request: Request) -> PairResponse:
    """Pair a new MN4 device. Requires a DeepTutor session.

    Returns a one-time token the Add-on stores and presents on every sync.
    """
    kb_name = _requested_kb(request)
    if resolve_db_path(kb_name) != _device_db_path(kb_name):
        # Pairing runs under a session and resolves the caller's own
        # workspace; /sync does not and resolves the default one. Where those
        # differ, pairing would hand out a token that 403s on every sync
        # forever, so refuse instead of issuing a dead credential.
        raise HTTPException(
            501,
            "MN4 device sync is not available for this account yet: pairing and "
            "sync would resolve different workspaces.",
        )
    store = _store_for(request)
    device, token = store.pair_device(device_name=body.device_name, device_kind=body.device_kind)
    logger.info("Paired MN4 device %s (%s)", device.device_id, device.device_name)
    return PairResponse(
        device_id=device.device_id,
        token=token,
        device_name=device.device_name,
        device_kind=device.device_kind,
    )


@router.get("/devices", response_model=list[DeviceInfo], dependencies=_auth)
async def list_devices(request: Request) -> list[DeviceInfo]:
    """List all paired devices."""
    store = _store_for(request)
    return [
        DeviceInfo(
            device_id=d.device_id,
            device_name=d.device_name,
            device_kind=d.device_kind,
            paired_at=d.paired_at,
            last_seen=d.last_seen,
            active=d.active,
        )
        for d in store.list_devices()
    ]


@router.delete("/devices/{device_id}", dependencies=_auth)
async def revoke_device(device_id: str, request: Request) -> dict[str, str]:
    """Revoke a paired device."""
    store = _store_for(request)
    if not store.revoke_device(device_id):
        raise HTTPException(404, f"Device {device_id} not found.")
    return {"status": "revoked", "device_id": device_id}


@router.get("/status", dependencies=_auth)
async def status(request: Request) -> dict[str, Any]:
    """Health check and summary stats."""
    store = _store_for(request)
    return {
        "status": "ok",
        "devices": len(store.list_devices()),
        "objects": store.count(),
    }


# -- device-token-authenticated endpoints (MN4 Add-on) ---------------------


@router.post("/sync", response_model=SyncResponse)
async def sync_objects(
    body: SyncRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> SyncResponse:
    """Receive an incremental sync batch from a paired MN4 device."""
    device_id, store = _auth_device(request, authorization)
    objects = [
        MarginNoteObject(
            object_id=o.object_id,
            object_type=o.object_type,
            title=o.title,
            content=o.content,
            excerpt=o.excerpt,
            document_id=o.document_id,
            document_title=o.document_title,
            page=o.page,
            tags=o.tags,
            links=o.links,
            color=o.color,
            created_at=o.created_at,
            updated_at=o.updated_at,
            device_id=device_id,
            raw=o.raw,
        )
        for o in body.objects
    ]
    batch = SyncBatch(
        device_id=device_id,
        cursor=body.cursor,
        objects=objects,
        deleted_ids=body.deleted_ids,
    )
    result = store.ingest(batch)
    logger.info(
        "MN4 sync from %s: +%d ~%d -%d",
        device_id,
        result.stored,
        result.updated,
        result.deleted,
    )
    return SyncResponse(
        stored=result.stored,
        updated=result.updated,
        deleted=result.deleted,
        new_cursor=result.new_cursor,
    )


@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """Lightweight liveness check. Updates last_seen for the device."""
    device_id, store = _auth_device(request, authorization)
    return {
        "status": "ok",
        "device_id": device_id,
        "object_count": store.count(device_id=device_id),
    }
