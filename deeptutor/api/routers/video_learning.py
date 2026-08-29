"""Immersive Watching API for YouTube timed media with Invidious integration."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
import httpx
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from deeptutor.multi_user.learning_access import assert_learning_surface
from deeptutor.multi_user.paths import current_owner_id
from deeptutor.services.config.runtime_settings import (
    load_integrations_settings,
)
from deeptutor.tools.video_learning import learn_video
from deeptutor.video_learning import (
    TimedMediaError,
    TimedMediaNotFound,
    TimedMediaStore,
    YouTubeResolver,
    get_timed_media_store,
)
from deeptutor.video_learning.invidious_auth import (
    AuthStateStore,
    InvidiousTokenStore,
    disconnect_account,
    get_authorization_url,
    get_invidious_base_url,
    get_invidious_home_feed,
    get_invidious_public_base_url,
    get_user_preferences,
    sync_watch_history,
)
from deeptutor.video_learning.kb_publish import (
    learning_publish_state,
    publish_material_to_kb,
)
from deeptutor.video_learning.marks import (
    create_mark,
    delete_mark,
    suggest_marks,
    update_mark,
)
from deeptutor.video_learning.service import (
    _is_local_host,
)
from deeptutor.video_learning.subtitle_prefetch import get_subtitle_prefetch_service
from deeptutor.video_learning.youtube_session import HostChromeSessionStore, chrome_available

router = APIRouter()
public_router = APIRouter()
MAX_JOB_DURATION_SECONDS = 4 * 60 * 60
MAX_ACTIVE_TRANSCRIPT_JOBS_PER_USER = 2
ASR_JOB_TIMEOUT_SECONDS = 20 * 60
STREAM_TIMEOUT_SECONDS = 30.0
MAX_STREAM_REDIRECTS = 3
_SAFE_JOB_ID = r"[0-9a-f]{32}"
_JOBS: dict[str, asyncio.Task[None]] = {}
_JOB_ROOTS: dict[str, str] = {}


class ResolveRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    language: str = Field(default="", max_length=32)


class TranscriptJobRequest(BaseModel):
    language: str = Field(default="", max_length=32)


class YouTubeConnectRequest(BaseModel):
    material_id: str = Field(default="", max_length=64)


class PositionRequest(BaseModel):
    time_seconds: float = Field(ge=0, le=24 * 60 * 60)


class WatchProgressRequest(BaseModel):
    time_seconds: float = Field(ge=0, le=24 * 60 * 60)
    cumulative_played_seconds: float = Field(default=0.0, ge=0, le=24 * 60 * 60)


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    time_seconds: float = Field(default=0.0, ge=0, le=24 * 60 * 60)
    quote: str = Field(default="", max_length=4000)


class MarkCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    start_seconds: float = Field(ge=0, le=24 * 60 * 60)
    end_seconds: float = Field(ge=0, le=24 * 60 * 60)
    start_locator: int = Field(default=0, ge=0)
    end_locator: int = Field(default=0, ge=0)
    quote: str = Field(default="", max_length=4000)
    note: str = Field(default="", max_length=2000)
    author: str = Field(default="user", max_length=32)
    source: str = Field(default="immersive", max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkPatchRequest(BaseModel):
    kind: str | None = Field(default=None, max_length=32)
    start_seconds: float | None = Field(default=None, ge=0, le=24 * 60 * 60)
    end_seconds: float | None = Field(default=None, ge=0, le=24 * 60 * 60)
    start_locator: int | None = Field(default=None, ge=0)
    end_locator: int | None = Field(default=None, ge=0)
    quote: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=2000)
    reviewed: bool | None = None
    metadata: dict[str, Any] | None = None


class MarkSuggestionRequest(BaseModel):
    time_seconds: float = Field(default=0.0, ge=0, le=24 * 60 * 60)


class PublishToKbRequest(BaseModel):
    kb_name: str = Field(default="default", max_length=200)


class CreateBookFromVideoRequest(BaseModel):
    kb_name: str = Field(default="default", max_length=200)
    user_intent: str = Field(default="", max_length=4000)
    language: str = Field(default="en", max_length=32)
    depth: str = Field(default="standard", max_length=32)
    publish: bool = True


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, TimedMediaNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TimedMediaError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="The video learning service could not complete the request.")


def _public_material(material: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(material)
    playback = payload.get("playback") if isinstance(payload.get("playback"), dict) else {}
    formats = playback.get("formats") if isinstance(playback.get("formats"), dict) else {}
    public_formats: dict[str, dict[str, Any]] = {}
    material_id = str(payload.get("material_id") or "")
    for format_id, row in formats.items():
        if not isinstance(row, dict):
            continue
        safe = {key: value for key, value in row.items() if key != "url"}
        safe["stream_url"] = f"/api/v1/video-learning/materials/{material_id}/stream/{format_id}"
        public_formats[str(format_id)] = safe
    payload.setdefault("playback", {})["formats"] = public_formats
    return payload


def _vtt_timestamp(value: Any) -> str:
    seconds = max(0.0, float(value or 0.0))
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _material_vtt(material: dict[str, Any]) -> str:
    transcript = material.get("transcript") if isinstance(material.get("transcript"), dict) else {}
    cues = transcript.get("cues") if isinstance(transcript.get("cues"), list) else []
    lines = ["WEBVTT", ""]
    for index, cue in enumerate(cues, start=1):
        if not isinstance(cue, dict):
            continue
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        start = _vtt_timestamp(cue.get("start"))
        end = _vtt_timestamp(cue.get("end"))
        lines.extend(
            [
                str(index),
                f"{start} --> {end}",
                escaped,
                "",
            ]
        )
    return "\n".join(lines)


def _job_path(store: TimedMediaStore, job_id: str):
    if not re.fullmatch(_SAFE_JOB_ID, job_id or ""):
        raise TimedMediaNotFound("Transcript job was not found.")
    return store.root / f"job-{job_id}.json"


def _read_job(store: TimedMediaStore, job_id: str) -> dict[str, Any]:
    path = _job_path(store, job_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise TimedMediaNotFound("Transcript job was not found.") from exc
    if not isinstance(payload, dict):
        raise TimedMediaNotFound("Transcript job was not found.")
    return payload


def _write_job(store: TimedMediaStore, job_id: str, **fields: Any) -> dict[str, Any]:
    current = {}
    try:
        current = _read_job(store, job_id)
    except TimedMediaNotFound:
        pass
    current.update(fields)
    current["job_id"] = job_id
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    from deeptutor.services.file_io import atomic_write_json

    atomic_write_json(_job_path(store, job_id), current)
    return current


# Invidious account & feed endpoints

@router.get("/invidious/status")
async def get_invidious_status() -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        owner_id = current_owner_id()
        base_url = get_invidious_base_url()
        public_base = get_invidious_public_base_url()
        connected = InvidiousTokenStore.has_token(owner_id)
        prefs = await get_user_preferences(owner_id) if connected else None
        return {
            "configured": bool(base_url),
            "connected": connected and prefs is not None,
            "invidious_base_url": base_url,
            "invidious_public_base_url": public_base,
            "user_preferences": prefs,
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/invidious/authorize")
async def get_invidious_authorize_url(
    callback_base: str = Query(default="", description="Optional external API base override"),
) -> dict[str, str]:
    try:
        assert_learning_surface("watching")
        owner_id = current_owner_id()
        auth_url = await get_authorization_url(owner_id, callback_base)
        return {"authorize_url": auth_url}
    except Exception as exc:
        raise _error(exc) from exc


@public_router.get("/invidious/callback", response_class=HTMLResponse)
async def invidious_oauth_callback(
    token: str = Query(default=""),
    state: str = Query(default=""),
) -> Response:
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }
    if not token or not state:
        html = (
            "<!DOCTYPE html><html><head><title>Authorization Failed</title></head>"
            "<body style='font-family:sans-serif;padding:2rem;text-align:center;'>"
            "<h2>Authorization Incomplete</h2><p>Missing token or state parameter.</p>"
            "</body></html>"
        )
        return HTMLResponse(content=html, status_code=400, headers=headers)

    owner_id = await AuthStateStore.validate_and_consume_state(state)
    if not owner_id:
        html = (
            "<!DOCTYPE html><html><head><title>Authorization Expired</title></head>"
            "<body style='font-family:sans-serif;padding:2rem;text-align:center;'>"
            "<h2>Authorization Expired</h2><p>The authorization state is invalid or has expired. Please try again from DeepTutor.</p>"
            "</body></html>"
        )
        return HTMLResponse(content=html, status_code=400, headers=headers)

    InvidiousTokenStore.set_token(owner_id, token)

    html = (
        "<!DOCTYPE html><html><head><title>Authorization Successful</title>"
        "<script>"
        "try {"
        "  if (window.opener) { window.opener.postMessage({ type: 'INVIDIOUS_AUTH_SUCCESS' }, '*'); }"
        "} catch(e) {}"
        "setTimeout(function() { window.close(); }, 1500);"
        "</script></head>"
        "<body style='font-family:sans-serif;padding:2rem;text-align:center;'>"
        "<h2>Connected to Invidious!</h2>"
        "<p>Your Invidious account has been connected successfully. You can return to DeepTutor.</p>"
        "<p><a href='/home' style='color:#0969da;'>Return to DeepTutor</a></p>"
        "</body></html>"
    )
    return HTMLResponse(content=html, status_code=200, headers=headers)


@router.post("/invidious/disconnect")
async def disconnect_invidious_account() -> dict[str, bool]:
    try:
        assert_learning_surface("watching")
        owner_id = current_owner_id()
        ok = await disconnect_account(owner_id)
        return {"ok": ok}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/invidious/home")
async def get_invidious_home(
    tab: str = Query(default="", description="Feed tab name: Popular, Trending, Subscriptions, Playlists, History"),
) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        owner_id = current_owner_id()
        return await get_invidious_home_feed(owner_id, tab=tab)
    except Exception as exc:
        raise _error(exc) from exc


# Video learning material endpoints

@router.get("/youtube-session/status")
async def get_youtube_session_status() -> dict[str, Any]:
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
async def connect_youtube_session(payload: YouTubeConnectRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        owner_id = current_owner_id()
        if payload.material_id:
            get_timed_media_store().get(payload.material_id)
        HostChromeSessionStore.enable(owner_id)
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
async def disconnect_youtube_session() -> dict[str, bool]:
    try:
        assert_learning_surface("watching")
        HostChromeSessionStore.delete(current_owner_id())
        return {"ok": True}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/resolve")
async def resolve_video(payload: ResolveRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        material = await YouTubeResolver().resolve(payload.url, language=payload.language)
        if not (material.get("transcript") or {}).get("cues"):
            fetch = await get_subtitle_prefetch_service().enqueue(
                current_owner_id(), str(material.get("material_id") or ""), get_timed_media_store()
            )
            transcript = material.setdefault("transcript", {})
            if isinstance(transcript, dict):
                transcript["fetch"] = fetch
        return _public_material(material)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/materials/{material_id}")
async def get_video_material(material_id: str) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        material = get_timed_media_store().get(material_id)
        if not (material.get("transcript") or {}).get("cues"):
            await get_subtitle_prefetch_service().enqueue(current_owner_id(), material_id, get_timed_media_store())
            material = get_timed_media_store().get(material_id)
        return _public_material(material)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/materials/{material_id}/subtitles.vtt")
async def get_video_subtitles(material_id: str) -> Response:
    try:
        assert_learning_surface("watching")
        material = get_timed_media_store().get(material_id)
        return Response(
            content=_material_vtt(material),
            media_type="text/vtt",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/subtitle-prefetch", status_code=202)
async def request_subtitle_prefetch(material_id: str) -> JSONResponse:
    try:
        assert_learning_surface("watching")
        fetch = await get_subtitle_prefetch_service().enqueue(current_owner_id(), material_id, get_timed_media_store(), manual=True)
        return JSONResponse(status_code=202, content={"fetch": fetch})
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/transcript-jobs", status_code=202)
async def create_transcript_job(material_id: str, payload: TranscriptJobRequest) -> JSONResponse:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        material = store.get(material_id)
        duration = int(material.get("source", {}).get("duration_seconds") or 0)
        if duration > MAX_JOB_DURATION_SECONDS:
            raise TimedMediaError("Audio preprocessing is limited to four hours per video.")
        root_key = str(store.root)
        active_jobs = sum(1 for key, task in _JOBS.items() if not task.done() and _JOB_ROOTS.get(key) == root_key)
        if active_jobs >= MAX_ACTIVE_TRANSCRIPT_JOBS_PER_USER:
            raise TimedMediaError("Too many transcript jobs are already running for this user.")
        job_id = hashlib.sha256(f"{material_id}-{datetime.now(timezone.utc).timestamp()}".encode()).hexdigest()[:32]
        _write_job(store, job_id, material_id=material_id, status="queued", progress=0, language=payload.language)
        task = asyncio.create_task(_run_transcript_job(job_id, material_id, payload.language, store))
        _JOBS[job_id] = task
        _JOB_ROOTS[job_id] = root_key

        def _forget(_task: asyncio.Task[None]) -> None:
            _JOBS.pop(job_id, None)
            _JOB_ROOTS.pop(job_id, None)

        task.add_done_callback(_forget)
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": "queued"})
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/transcript-jobs/{job_id}")
async def get_transcript_job(job_id: str) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        return _read_job(get_timed_media_store(), job_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.put("/materials/{material_id}/position")
async def save_video_position(material_id: str, payload: PositionRequest) -> dict[str, float]:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        with store.lock(material_id):
            material = store.get(material_id)
            material.setdefault("learning", {})["last_position"] = payload.time_seconds
            store.save(material)
        return {"time_seconds": payload.time_seconds}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/watch-progress")
async def record_video_watch_progress(material_id: str, payload: WatchProgressRequest) -> dict[str, Any]:
    """Update position and sync watched status to Invidious history once cumulative playback threshold is met."""
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        with store.lock(material_id):
            material = store.get(material_id)
            learning = material.setdefault("learning", {})
            learning["last_position"] = payload.time_seconds
            prev_cumulative = float(learning.get("cumulative_played_seconds") or 0.0)
            new_cumulative = max(prev_cumulative, payload.cumulative_played_seconds)
            learning["cumulative_played_seconds"] = new_cumulative

            duration = float(material.get("source", {}).get("duration_seconds") or 0)
            threshold = min(30.0, max(5.0, 0.10 * duration)) if duration > 0 else 30.0

            already_synced = bool(learning.get("invidious_history_synced"))
            synced_now = False

            if new_cumulative >= threshold and not already_synced:
                owner_id = current_owner_id()
                video_id = str(material.get("source", {}).get("video_id") or "")
                if video_id and InvidiousTokenStore.has_token(owner_id):
                    ok, reason = await sync_watch_history(owner_id, video_id)
                    if ok:
                        learning["invidious_history_synced"] = True
                        synced_now = True
                    elif reason == "history_disabled":
                        learning["invidious_history_synced"] = False

            store.save(material)
        return {
            "time_seconds": payload.time_seconds,
            "cumulative_played_seconds": new_cumulative,
            "synced_to_invidious": already_synced or synced_now,
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/notes", status_code=201)
async def add_video_note(material_id: str, payload: NoteRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        with store.lock(material_id):
            material = store.get(material_id)
            note = {
                "note_id": hashlib.sha256(
                    f"{material_id}-{datetime.now(timezone.utc).timestamp()}".encode()
                ).hexdigest()[:24],
                "text": payload.text.strip(),
                "time_seconds": payload.time_seconds,
                "quote": payload.quote.strip(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if not note["text"]:
                raise TimedMediaError("A video note cannot be empty.")
            notes = material.setdefault("learning", {}).setdefault("notes", [])
            if not isinstance(notes, list):
                notes = []
                material["learning"]["notes"] = notes
            notes.append(note)
            material["learning"]["notes"] = notes[-500:]
            store.save(material)
        return note
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/marks", status_code=201)
async def add_video_mark(material_id: str, payload: MarkCreateRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        with store.lock(material_id):
            material = store.get(material_id)
            mark = create_mark(material, payload.model_dump())
            store.save(material)
        return mark
    except Exception as exc:
        raise _error(exc) from exc


@router.patch("/materials/{material_id}/marks/{mark_id}")
async def patch_video_mark(material_id: str, mark_id: str, payload: MarkPatchRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        fields = payload.model_dump(exclude_unset=True)
        with store.lock(material_id):
            material = store.get(material_id)
            mark = update_mark(material, mark_id, fields)
            store.save(material)
        return mark
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/materials/{material_id}/marks/{mark_id}")
async def remove_video_mark(material_id: str, mark_id: str) -> dict[str, bool]:
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        with store.lock(material_id):
            material = store.get(material_id)
            delete_mark(material, mark_id)
            store.save(material)
        return {"ok": True}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/publish-to-kb")
async def publish_video_to_kb(material_id: str, payload: PublishToKbRequest) -> dict[str, Any]:
    """Manually publish or update one personal-KB learning note for this video."""
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        material = store.get(material_id)
        result = await publish_material_to_kb(material, kb_name=payload.kb_name)
        store.save(result["material"])
        return {
            "material": _public_material(result["material"]),
            "kb_name": result["kb_name"],
            "kb_id": result["kb_id"],
            "path": result["path"],
            "content_hash": result["content_hash"],
            "updated": result["updated"],
            "published_at": result["published_at"],
            "kb_publish": learning_publish_state(result["material"]),
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/create-book")
async def create_book_from_video(material_id: str, payload: CreateBookFromVideoRequest) -> dict[str, Any]:
    """Create an interactive Book grounded on this video's marks and published note."""
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        material = store.get(material_id)
        metadata = material.get("metadata") if isinstance(material.get("metadata"), dict) else {}
        title = str(metadata.get("title") or material.get("source", {}).get("video_id") or material_id)
        kb_name = payload.kb_name or "default"
        if payload.publish or learning_publish_state(material) is None:
            published = await publish_material_to_kb(material, kb_name=kb_name)
            material = published["material"]
            store.save(material)
            kb_name = published["kb_name"]
        else:
            state = learning_publish_state(material) or {}
            kb_name = str(state.get("kb_name") or kb_name)
        intent = (payload.user_intent or "").strip() or (
            f"Build an interactive learning book from my Immersive Watching notes on '{title}'. "
            "Prefer the video transcript and private marks as source truth. "
            "Preserve timestamp jump-backs to Immersive Watching. "
            "Use the full Book toolkit (sections, quizzes, flash cards, timelines, figures, "
            "concept graphs, interactive blocks, code, deep dives, and animations when helpful). "
            "Animations are supplementary; never block the rest of the book if animation generation fails."
        )
        from deeptutor.book.engine import get_book_engine

        engine = get_book_engine()
        book, proposal = await engine.create_book(
            user_intent=intent,
            knowledge_bases=[kb_name],
            timed_media_ids=[material_id],
            language=payload.language or "en",
            depth=payload.depth or "standard",
        )
        return {
            "book": book.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
            "material": _public_material(material),
            "kb_publish": learning_publish_state(material),
        }
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/materials/{material_id}/mark-suggestions")
async def suggest_video_marks(material_id: str, payload: MarkSuggestionRequest) -> dict[str, Any]:
    try:
        assert_learning_surface("watching")
        material = get_timed_media_store().get(material_id)
        suggestions = await suggest_marks(material, payload.time_seconds)
        return {"suggestions": suggestions}
    except Exception as exc:
        raise _error(exc) from exc


@router.api_route("/materials/{material_id}/stream/{format_id}", methods=["GET", "HEAD"])
async def stream_video(material_id: str, format_id: str, request: Request):
    try:
        assert_learning_surface("watching")
        store = get_timed_media_store()
        material = store.get(material_id)
        format_row = _format_for(material, format_id)
        if request.method == "HEAD":
            headers = _stream_headers(format_row)
            return Response(status_code=200, headers=headers)
        return await _open_stream(store, material, format_id, request)
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc


async def _run_transcript_job(job_id: str, material_id: str, language: str, store: TimedMediaStore) -> None:
    _write_job(store, job_id, status="running", progress=5)
    material = store.get(material_id)
    source_url = str(material.get("source", {}).get("url") or "")
    try:
        outcome = await asyncio.wait_for(
            learn_video(
                source_url,
                max_chars=200_000,
                generate_transcript_if_missing=True,
                subtitle_language=language,
                state_dir=store.root,
            ),
            timeout=ASR_JOB_TIMEOUT_SECONDS,
        )
        if not outcome.ok or not outcome.transcript:
            raise TimedMediaError(outcome.error or "The speech-to-text provider returned no transcript.")
        material["transcript"] = {"language": outcome.subtitle_language or language or "auto", "source": "stt", "cues": outcome.transcript}
        from deeptutor.video_learning.service import build_segments

        material["segments"] = build_segments(outcome.transcript)
        store.save(material)
        _write_job(store, job_id, status="completed", progress=100, material_id=material_id)
    except asyncio.CancelledError:
        _write_job(store, job_id, status="cancelled", progress=0)
        raise
    except Exception as exc:
        _write_job(store, job_id, status="failed", progress=0, error=str(exc))


def _format_for(material: dict[str, Any], format_id: str) -> dict[str, Any]:
    formats = material.get("playback", {}).get("formats", {})
    row = formats.get(format_id) if isinstance(formats, dict) else None
    if not isinstance(row, dict) or not str(row.get("url") or ""):
        raise TimedMediaNotFound("The requested video format is unavailable.")
    parsed = urlparse(str(row["url"]))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TimedMediaError("The stored video stream URL is invalid.")
    configured = str(load_integrations_settings().get("invidious_base_url") or "")
    _validate_stream_host(
        parsed.hostname,
        urlparse(configured).hostname or "",
        scheme=parsed.scheme,
    )
    return row


def _stream_headers(row: dict[str, Any]) -> dict[str, str]:
    headers = {"Accept-Ranges": "bytes", "Content-Type": str(row.get("mime_type") or "video/mp4")}
    length = int(row.get("content_length") or 0)
    if length > 0:
        headers["Content-Length"] = str(length)
    return headers


async def _open_stream(store: TimedMediaStore, material: dict[str, Any], format_id: str, request: Request):
    row = _format_for(material, format_id)
    response = await _upstream_stream(material, row, request.headers.get("range"))
    if response.status_code in {401, 403}:
        await response.aclose()
        await response.extensions.get("_client_close", _noop_async)()
        material = await YouTubeResolver().refresh_formats(material)
        store.save(material)
        row = _format_for(material, format_id)
        response = await _upstream_stream(material, row, request.headers.get("range"))
    if response.status_code >= 400:
        await response.aclose()
        await response.extensions.get("_client_close", _noop_async)()
        raise TimedMediaError(f"The upstream video stream returned HTTP {response.status_code}.")

    client = response.extensions.get("_client")

    async def close() -> None:
        await response.aclose()
        if client is not None:
            await client.aclose()

    headers = _stream_headers(row)
    for key in ("content-length", "content-range", "content-type", "accept-ranges", "etag", "last-modified"):
        if response.headers.get(key):
            headers[key.title()] = response.headers[key]
    return StreamingResponse(response.aiter_bytes(), status_code=response.status_code, headers=headers, background=BackgroundTask(close))


async def _upstream_stream(material: dict[str, Any], row: dict[str, Any], range_header: str | None) -> httpx.Response:
    url = str(row.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise TimedMediaError("The stored video stream URL is invalid.")
    base = str(load_integrations_settings().get("invidious_base_url") or "")
    _validate_stream_host(parsed.hostname, urlparse(base).hostname or "")
    client = httpx.AsyncClient(timeout=STREAM_TIMEOUT_SECONDS, follow_redirects=False)
    headers = {"User-Agent": "DeepTutor/1.0", "Accept": "video/mp4"}
    if range_header:
        headers["Range"] = range_header
    try:
        current = url
        for _ in range(MAX_STREAM_REDIRECTS + 1):
            parsed = urlparse(current)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise TimedMediaError("The stored video stream URL is invalid.")
            _validate_stream_host(parsed.hostname, urlparse(base).hostname or "", scheme=parsed.scheme)
            upstream = await client.send(client.build_request("GET", current, headers=headers), stream=True)
            if upstream.is_redirect:
                location = upstream.headers.get("location")
                await upstream.aclose()
                if not location:
                    raise TimedMediaError("The upstream video stream returned an invalid redirect.")
                current = urljoin(current, location)
                continue
            final_url = str(upstream.url or current)
            final_parsed = urlparse(final_url)
            _validate_stream_host(
                final_parsed.hostname or "",
                urlparse(base).hostname or "",
                scheme=final_parsed.scheme,
            )
            upstream.extensions["_client"] = client
            upstream.extensions["_client_close"] = client.aclose
            return upstream
        raise TimedMediaError("The upstream video stream returned too many redirects.")
    except Exception:
        await client.aclose()
        raise


async def _noop_async() -> None:
    return None


def _validate_stream_host(host: str, configured_host: str, *, scheme: str = "https") -> None:
    lowered = host.lower().rstrip(".")
    configured = configured_host.lower().rstrip(".")
    if lowered == configured or lowered.endswith(".googlevideo.com") or lowered.endswith(".googleusercontent.com"):
        if scheme != "https" and not _is_local_host(lowered):
            raise TimedMediaError("The video stream must use HTTPS outside the local network.")
        return
    if _is_local_host(lowered):
        return
    raise TimedMediaError("The video stream resolved outside the configured media providers.")


__all__ = ["router"]
