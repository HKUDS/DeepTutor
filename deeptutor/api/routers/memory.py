"""
Two-file public memory API: SUMMARY and PROFILE.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deeptutor.services.memory import MemoryFile, get_memory_service
from deeptutor.services.session import get_session_store

router = APIRouter()

_VALID_FILES: set[MemoryFile] = {"summary", "profile"}


def _snap_dict(snap) -> dict:
    return {
        "summary": snap.summary,
        "profile": snap.profile,
        "summary_updated_at": snap.summary_updated_at,
        "profile_updated_at": snap.profile_updated_at,
    }


class FileUpdateRequest(BaseModel):
    file: MemoryFile
    content: str = ""


class MemoryRefreshRequest(BaseModel):
    session_id: str | None = None
    language: str = "en"


class MemoryClearRequest(BaseModel):
    file: MemoryFile | None = None


@router.get("")
async def get_memory():
    return _snap_dict(get_memory_service().read_snapshot())


@router.put("")
async def update_memory(payload: FileUpdateRequest):
    if payload.file not in _VALID_FILES:
        raise HTTPException(status_code=400, detail=f"Invalid file: {payload.file}")
    snap = get_memory_service().write_file(payload.file, payload.content)
    return {**_snap_dict(snap), "saved": True}


@router.post("/refresh")
async def refresh_memory(payload: MemoryRefreshRequest):
    store = get_session_store()
    session_id = str(payload.session_id or "").strip()
    if session_id:
        session = await store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

    result = await get_memory_service().refresh_from_session(
        session_id or None,
        language=payload.language,
    )
    snap = get_memory_service().read_snapshot()
    return {**_snap_dict(snap), "changed": result.changed}


@router.post("/clear")
async def clear_memory(payload: MemoryClearRequest | None = None):
    svc = get_memory_service()
    target = payload.file if payload else None
    if target and target not in _VALID_FILES:
        raise HTTPException(status_code=400, detail=f"Invalid file: {target}")

    if target:
        snap = svc.clear_file(target)
    else:
        snap = svc.clear_memory()
    return {**_snap_dict(snap), "cleared": True}
