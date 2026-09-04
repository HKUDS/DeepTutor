"""Authenticated Immersive Watching and administrator provider settings."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
import httpx
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from deeptutor.multi_user.paths import current_owner_id
from deeptutor.services.notebook.service import NotebookCorruptedError
from deeptutor.video_learning import (
    TimedMediaError,
    TimedMediaNotFound,
    get_timed_media_store,
    invidious_account,
    load_video_learning_settings,
    material_with_playback,
    refresh_invidious_transcript,
    resolve_material,
    save_video_learning_settings,
    test_invidious_connection,
)
from deeptutor.video_learning import notes as video_notes

router = APIRouter()
settings_router = APIRouter()
STREAM_TIMEOUT_SECONDS = 30.0
MAX_STREAM_REDIRECTS = 3
RANGE_HEADER_RE = re.compile(r"^bytes=(?:[0-9]+-[0-9]*|-[0-9]+)$")


class ResolveRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    language: str = Field(default="", max_length=32)
    provider_override: str | None = Field(default=None, max_length=32)


class ProgressRequest(BaseModel):
    time_seconds: float = Field(ge=0, le=24 * 60 * 60)
    duration_seconds: float = Field(default=0, ge=0, le=24 * 60 * 60)


class CreateVideoNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    time_seconds: float = Field(ge=0, le=24 * 60 * 60)


class UpdateVideoNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)


class YouTubeSettings(BaseModel):
    transcript_provider: str = Field(default="youtube_transcript_api", max_length=64)


class InvidiousSettings(BaseModel):
    api_base_url: str = Field(default="", max_length=2048)
    public_base_url: str = Field(default="", max_length=2048)


class VideoLearningSettingsRequest(BaseModel):
    version: int = 1
    default_provider: str = Field(default="youtube", max_length=32)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)
    invidious: InvidiousSettings = Field(default_factory=InvidiousSettings)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TimedMediaNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TimedMediaError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Video learning could not complete the request.")


def _note_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotebookCorruptedError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "notebook_unreadable",
                "notebook_id": exc.notebook_id,
                "message": str(exc),
            },
        )
    return _http_error(exc)


@settings_router.get("")
async def get_video_learning_settings() -> dict[str, Any]:
    return load_video_learning_settings()


@settings_router.put("")
async def update_video_learning_settings(payload: VideoLearningSettingsRequest) -> dict[str, Any]:
    try:
        return save_video_learning_settings(payload.model_dump())
    except Exception as exc:
        raise _http_error(exc) from exc


@settings_router.post("/test-invidious")
async def test_invidious(payload: VideoLearningSettingsRequest) -> dict[str, Any]:
    try:
        return await test_invidious_connection(payload.model_dump())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/invidious/account/authorize")
async def authorize_invidious_account() -> dict[str, str]:
    try:
        url = invidious_account.begin_invidious_account_authorization(
            owner_id=current_owner_id(),
            redirect_uri=invidious_account.invidious_redirect_uri(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return {"authorize_url": url}


@router.get("/invidious/account/callback")
async def invidious_account_callback(token: str = "", state: str = "") -> JSONResponse:
    try:
        status = await invidious_account.complete_invidious_account_authorization(
            owner_id=current_owner_id(),
            state=state,
            token=token,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return JSONResponse(status, headers={"Cache-Control": "no-store"})


@router.get("/invidious/account/status")
async def get_invidious_account_status() -> dict[str, Any]:
    return invidious_account.invidious_account_status(current_owner_id())


@router.post("/invidious/account/disconnect")
async def disconnect_invidious_account() -> dict[str, Any]:
    try:
        return await invidious_account.disconnect_invidious_account(owner_id=current_owner_id())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials/resolve")
async def resolve_video(payload: ResolveRequest) -> dict[str, Any]:
    try:
        if payload.provider_override not in {None, "youtube", "invidious"}:
            raise TimedMediaError("Unsupported provider override.")
        return await resolve_material(
            payload.url,
            payload.language,
            provider_override=payload.provider_override,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}")
async def get_video_material(material_id: str) -> dict[str, Any]:
    try:
        return await material_with_playback(material_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/materials/{material_id}/transcript/refresh")
async def refresh_video_transcript(material_id: str) -> dict[str, Any]:
    try:
        return await refresh_invidious_transcript(material_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/materials/{material_id}/progress")
async def save_video_progress(material_id: str, payload: ProgressRequest) -> dict[str, float]:
    try:
        store = get_timed_media_store()
        with store.lock(material_id):
            material = store.get(material_id)
            known_duration = float(material.get("metadata", {}).get("duration_seconds") or 0)
            duration = known_duration or float(payload.duration_seconds or 0)
            position = min(payload.time_seconds, duration) if duration > 0 else payload.time_seconds
            material.setdefault("learning", {})["last_position"] = position
            if duration > 0:
                material.setdefault("metadata", {})["duration_seconds"] = duration
            store.save(material)
        return {"time_seconds": position, "duration_seconds": duration}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/materials/{material_id}/notes")
async def list_video_notes(material_id: str) -> list[dict[str, Any]]:
    try:
        return video_notes.list_notes(video_notes.get_notebook_manager(), material_id)
    except Exception as exc:
        raise _note_error(exc) from exc


@router.get("/materials/{material_id}/notes.md")
async def export_video_notes(material_id: str) -> Response:
    try:
        markdown = video_notes.export_notes(video_notes.get_notebook_manager(), material_id)
        return Response(
            markdown,
            media_type="text/markdown",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="video-notes.md"',
            },
        )
    except Exception as exc:
        raise _note_error(exc) from exc


@router.post("/materials/{material_id}/notes")
async def create_video_note(material_id: str, payload: CreateVideoNoteRequest) -> dict[str, Any]:
    try:
        return video_notes.create_note(
            video_notes.get_notebook_manager(),
            material_id,
            payload.body,
            payload.time_seconds,
        )
    except Exception as exc:
        raise _note_error(exc) from exc


@router.put("/materials/{material_id}/notes/{note_id}")
async def update_video_note(
    material_id: str, note_id: str, payload: UpdateVideoNoteRequest
) -> dict[str, Any]:
    try:
        return video_notes.update_note(
            video_notes.get_notebook_manager(), material_id, note_id, payload.body
        )
    except Exception as exc:
        raise _note_error(exc) from exc


@router.delete("/materials/{material_id}/notes/{note_id}")
async def delete_video_note(material_id: str, note_id: str) -> dict[str, str]:
    try:
        deleted = video_notes.delete_note(video_notes.get_notebook_manager(), material_id, note_id)
        return {"status": "deleted" if deleted else "missing"}
    except Exception as exc:
        raise _note_error(exc) from exc


def _vtt_timestamp(value: Any) -> str:
    milliseconds = int(round(max(0.0, float(value or 0)) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


@router.get("/materials/{material_id}/subtitles.vtt")
async def get_video_subtitles(material_id: str) -> Response:
    try:
        material = get_timed_media_store().get(material_id)
        cues = material.get("transcript", {}).get("cues") or []
        lines = ["WEBVTT", ""]
        for index, cue in enumerate(cues, start=1):
            if not isinstance(cue, dict) or not str(cue.get("text") or "").strip():
                continue
            text = " ".join(str(cue["text"]).split())
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            lines.extend(
                [
                    str(index),
                    f"{_vtt_timestamp(cue.get('start'))} --> {_vtt_timestamp(cue.get('end'))}",
                    text,
                    "",
                ]
            )
        return Response(
            "\n".join(lines), media_type="text/vtt", headers={"Cache-Control": "no-store"}
        )
    except Exception as exc:
        raise _http_error(exc) from exc


def _allowed_stream_url(value: str, invidious_base: str, public_base: str = "") -> str:
    absolute = urljoin(f"{invidious_base}/", value)
    parsed = urlparse(absolute)
    trusted_origins = [urlparse(invidious_base)]
    if public_base:
        trusted_origins.append(urlparse(public_base))
    try:
        parsed_port = parsed.port
        trusted_ports = [origin.port for origin in trusted_origins]
    except ValueError as exc:
        raise TimedMediaError("Invidious returned a stream URL with an invalid port.") from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise TimedMediaError("Invidious returned an invalid stream URL.")
    same_origin = any(
        host == (origin.hostname or "").lower().rstrip(".")
        and parsed.scheme == origin.scheme
        and parsed_port == trusted_port
        for origin, trusted_port in zip(trusted_origins, trusted_ports, strict=True)
    )
    google_media = (
        (host == "googlevideo.com" or host.endswith(".googlevideo.com"))
        and parsed.scheme == "https"
        and parsed_port in {None, 443}
    )
    if not same_origin and not google_media:
        raise TimedMediaError("Invidious returned a stream outside its allowed media hosts.")
    return absolute


async def _live_stream_url(material_id: str, format_id: str) -> tuple[str, str]:
    if not format_id.isdigit() or len(format_id) > 6:
        raise TimedMediaNotFound("Video format was not found.")
    material = get_timed_media_store().get(material_id)
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    video_id = str(source.get("video_id") or "")
    settings = load_video_learning_settings()
    base = settings["invidious"]["api_base_url"]
    configured_formats = material.get("provider_cache", {}).get("invidious_formats") or []
    if not base or not any(
        str(row.get("format_id") or "") == format_id for row in configured_formats
    ):
        raise TimedMediaError("Stream proxy is available only for an Invidious descriptor.")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.get(f"{base}/api/v1/videos/{video_id}")
    if response.status_code >= 400:
        raise TimedMediaError(f"Invidious request failed with HTTP {response.status_code}.")
    try:
        metadata = response.json()
    except ValueError as exc:
        raise TimedMediaError("Invidious returned invalid video metadata.") from exc
    if not isinstance(metadata, dict):
        raise TimedMediaError("Invidious returned invalid video metadata.")
    for row in metadata.get("formatStreams") or []:
        if isinstance(row, dict) and str(row.get("itag") or "") == format_id:
            mime = str(row.get("type") or "video/mp4").split(";", 1)[0]
            if mime != "video/mp4":
                raise TimedMediaError("Invidious changed the selected stream format.")
            return _allowed_stream_url(
                str(row.get("url") or ""),
                base,
                settings["invidious"]["public_base_url"],
            ), mime
    raise TimedMediaNotFound("Video format was not found.")


async def _open_upstream(
    url: str, mime: str, range_header: str | None
) -> tuple[httpx.AsyncClient, httpx.Response]:
    settings = load_video_learning_settings()
    base = settings["invidious"]["api_base_url"]
    public_base = settings["invidious"]["public_base_url"]
    client = httpx.AsyncClient(timeout=STREAM_TIMEOUT_SECONDS, follow_redirects=False)
    headers = {"User-Agent": "DeepTutor/1.0", "Accept": mime}
    if range_header:
        headers["Range"] = range_header
    current = url
    try:
        for _ in range(MAX_STREAM_REDIRECTS + 1):
            response = await client.send(
                client.build_request("GET", current, headers=headers), stream=True
            )
            if not response.is_redirect:
                return client, response
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                break
            current = _allowed_stream_url(urljoin(current, location), base, public_base)
    except Exception:
        await client.aclose()
        raise
    await client.aclose()
    raise TimedMediaError("Video stream returned too many redirects.")


@router.get(
    "/materials/{material_id}/stream/{format_id}",
    operation_id="stream_video_get",
)
@router.head(
    "/materials/{material_id}/stream/{format_id}",
    operation_id="stream_video_head",
)
async def stream_video(material_id: str, format_id: str, request: Request):
    try:
        range_header = request.headers.get("range")
        if range_header and not RANGE_HEADER_RE.fullmatch(range_header.strip()):
            raise HTTPException(status_code=416, detail="Only a single byte range is supported.")
        url, mime = await _live_stream_url(material_id, format_id)
        if request.method == "HEAD":
            return Response(
                status_code=200, headers={"Content-Type": mime, "Accept-Ranges": "bytes"}
            )
        client, response = await _open_upstream(url, mime, range_header)
        if response.status_code not in {200, 206}:
            status_code = response.status_code
            await response.aclose()
            await client.aclose()
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail="Upstream video stream failed.")
            raise HTTPException(
                status_code=502, detail="Upstream video stream returned an invalid status."
            )
        headers = {
            "Content-Type": response.headers.get("content-type", mime),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        }
        for key in ("content-length", "content-range", "etag", "last-modified"):
            if response.headers.get(key):
                headers[key.title()] = response.headers[key]

        async def close() -> None:
            await response.aclose()
            await client.aclose()

        return StreamingResponse(
            response.aiter_bytes(),
            status_code=response.status_code,
            headers=headers,
            background=BackgroundTask(close),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _http_error(exc) from exc


__all__ = ["router", "settings_router"]
