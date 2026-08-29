"""Single-user host-Chrome endpoints for YouTube subtitle retrieval."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deeptutor.multi_user.learning_access import assert_learning_surface
from deeptutor.multi_user.paths import current_owner_id
from deeptutor.video_learning import TimedMediaError, TimedMediaNotFound, get_timed_media_store
from deeptutor.video_learning.subtitle_prefetch import get_subtitle_prefetch_service
from deeptutor.video_learning.youtube_session import HostChromeSessionStore, chrome_available

router = APIRouter()


class ConnectRequest(BaseModel):
    material_id: str = Field(default="", max_length=64)


def _error(exc: Exception) -> TimedMediaError:
    if isinstance(exc, TimedMediaError):
        return exc
    return TimedMediaError("Could not prepare YouTube subtitles.")


@router.get("/youtube-session/status")
async def status() -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        metadata = HostChromeSessionStore.metadata(current_owner_id())
        helper_available = chrome_available()
        return {
            "connection": "connected" if metadata and helper_available else ("error" if metadata else "disconnected"),
            "helper_available": helper_available,
            "last_validated_at": str((metadata or {}).get("enabled_at") or "") or None,
            "last_error_code": "chrome_unavailable" if metadata and not helper_available else None,
            "next_prefetch_at": None,
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/youtube-session/connect", status_code=202)
async def connect(payload: ConnectRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        if payload.material_id:
            get_timed_media_store().get(payload.material_id)
        HostChromeSessionStore.enable(current_owner_id())
        helper_available = chrome_available()
        return {
            "connection": "connected" if helper_available else "error",
            "helper_available": helper_available,
            "last_error_code": None if helper_available else "chrome_unavailable",
            "mode": "host_chrome",
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/youtube-session")
async def disconnect() -> dict[str, bool]:
    HostChromeSessionStore.delete(current_owner_id())
    return {"ok": True}


@router.post("/materials/{material_id}/subtitle-prefetch", status_code=202)
async def prefetch(material_id: str) -> JSONResponse:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        fetch = await get_subtitle_prefetch_service().enqueue(current_owner_id(), material_id, store, manual=True)
        return JSONResponse(status_code=202, content={"fetch": fetch})
    except TimedMediaNotFound as exc:
        raise _error(exc) from exc
    except Exception as exc:
        raise _error(exc) from exc
