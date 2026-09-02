"""Provider-neutral timed video learning for YouTube and Invidious."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from deeptutor.multi_user.paths import get_admin_path_service, get_current_path_service
from deeptutor.services.file_io import atomic_write_json

ProviderName = Literal["youtube", "invidious"]
MAX_TRANSCRIPT_CUES = 20_000
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MIN_SEGMENT_SECONDS = 20
MAX_SEGMENT_SECONDS = 90
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MATERIAL_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
WEBVTT_TIMING_RE = re.compile(
    r"^\s*(?P<start>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})(?:[ \t]+.*)?$"
)


class TimedMediaError(RuntimeError):
    """A user-facing timed media failure."""


class TimedMediaNotFound(TimedMediaError):
    """The requested material is absent from the current user's workspace."""


@dataclass(frozen=True, slots=True)
class YouTubeRequest:
    video_id: str
    canonical_url: str
    entry_time_seconds: int = 0


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    metadata: dict[str, Any]
    cues: list[dict[str, Any]]
    transcript_language: str = ""
    transcript_source: str = ""
    formats: list[dict[str, Any]] | None = None


DEFAULT_VIDEO_LEARNING_SETTINGS: dict[str, Any] = {
    "version": 1,
    "default_provider": "youtube",
    "youtube": {"transcript_provider": "youtube_transcript_api"},
    "invidious": {"api_base_url": "", "public_base_url": ""},
}


def parse_timestamp(value: Any) -> int:
    raw = str(value or "").strip().lower()
    if raw.isdigit():
        return max(0, int(raw))
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw)
    if not match or not any(match.groups()):
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return max(0, hours * 3600 + minutes * 60 + seconds)


def parse_youtube_url(value: str) -> YouTubeRequest:
    parsed = urlparse((value or "").strip().strip("`\"'"))
    if parsed.scheme not in {"http", "https"}:
        raise TimedMediaError("YouTube URL must use HTTP or HTTPS.")
    host = (parsed.hostname or "").lower().rstrip(".")
    query = parse_qs(parsed.query)
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = query.get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = parsed.path.split("/", 2)[2].split("/", 1)[0]
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise TimedMediaError("Unsupported or invalid YouTube URL.")
    entry = parse_timestamp(query.get("t", query.get("start", ["0"]))[0])
    canonical_query = urlencode({"t": entry}) if entry else ""
    canonical = urlunparse(("https", "youtu.be", f"/{video_id}", "", canonical_query, ""))
    return YouTubeRequest(video_id, canonical, entry)


def _validate_origin(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    try:
        parsed.port
    except ValueError as exc:
        raise TimedMediaError("Invidious URL contains an invalid port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise TimedMediaError("Invidious URL must be a plain HTTP(S) origin without credentials.")
    host = parsed.hostname.lower().rstrip(".")
    if parsed.scheme == "http" and not _is_local_host(host):
        raise TimedMediaError("A public Invidious instance must use HTTPS.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_local_host(host: str) -> bool:
    if host in {"localhost", "invidious", "host.docker.internal"} or host.endswith(
        (".local", ".ts.net")
    ):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def normalize_video_learning_settings(payload: Any) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    provider = str(raw.get("default_provider") or "youtube").strip().lower()
    if provider not in {"youtube", "invidious"}:
        raise TimedMediaError("Video learning provider must be 'youtube' or 'invidious'.")
    youtube = raw.get("youtube") if isinstance(raw.get("youtube"), dict) else {}
    transcript_provider = str(youtube.get("transcript_provider") or "youtube_transcript_api")
    if transcript_provider not in {"youtube_transcript_api", "none"}:
        raise TimedMediaError("Unsupported YouTube transcript provider.")
    invidious = raw.get("invidious") if isinstance(raw.get("invidious"), dict) else {}
    api_base = _validate_origin(invidious.get("api_base_url"))
    public_base = _validate_origin(invidious.get("public_base_url"))
    if provider == "invidious" and not api_base:
        raise TimedMediaError("Configure the Invidious API base URL before selecting it.")
    return {
        "version": 1,
        "default_provider": provider,
        "youtube": {"transcript_provider": transcript_provider},
        "invidious": {"api_base_url": api_base, "public_base_url": public_base},
    }


def video_learning_settings_path() -> Path:
    return get_admin_path_service().get_settings_file("video_learning")


def load_video_learning_settings() -> dict[str, Any]:
    path = video_learning_settings_path()
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_VIDEO_LEARNING_SETTINGS))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return normalize_video_learning_settings(payload)
    except (OSError, json.JSONDecodeError, TimedMediaError):
        return json.loads(json.dumps(DEFAULT_VIDEO_LEARNING_SETTINGS))


def save_video_learning_settings(payload: Any) -> dict[str, Any]:
    normalized = normalize_video_learning_settings(payload)
    atomic_write_json(video_learning_settings_path(), normalized)
    return normalized


def normalize_cues(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    total_bytes = 0
    for row in list(rows)[:MAX_TRANSCRIPT_CUES]:
        if isinstance(row, dict):
            merged = row
        else:
            merged = {
                "start": getattr(row, "start", 0),
                "duration": getattr(row, "duration", 0),
                "text": getattr(row, "text", ""),
            }
        text = str(merged.get("text") or merged.get("content") or "").strip()
        if not text:
            continue
        encoded = text.encode("utf-8")
        if total_bytes + len(encoded) > MAX_TRANSCRIPT_BYTES:
            break
        try:
            start = max(0.0, float(merged.get("start") or merged.get("from") or 0))
            end = float(merged.get("end") or merged.get("to") or 0)
            if end <= start:
                end = start + max(0.0, float(merged.get("duration") or 0))
        except (TypeError, ValueError):
            continue
        result.append({"start": start, "end": max(start, end), "text": text})
        total_bytes += len(encoded)
    return result


def build_segments(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for cue in cues:
        if current is None:
            current = dict(cue)
            continue
        gap = max(0.0, float(cue["start"]) - float(current["end"]))
        length = float(cue["end"]) - float(current["start"])
        sentence_end = str(current["text"]).rstrip().endswith((".", "!", "?", "。", "！", "？"))
        if (
            length < MAX_SEGMENT_SECONDS
            and gap <= 4
            and not (length >= MIN_SEGMENT_SECONDS and sentence_end)
        ):
            current["end"] = cue["end"]
            current["text"] = f"{current['text']} {cue['text']}".strip()
        else:
            segments.append(current)
            current = dict(cue)
    if current is not None:
        segments.append(current)
    for locator, segment in enumerate(segments, start=1):
        segment["locator"] = locator
    return segments


def parse_webvtt(text: str) -> list[dict[str, Any]]:
    """Parse Invidious WebVTT while tolerating malformed leading blanks.

    Some caption endpoints insert a whitespace-only line between a cue timing
    line and its payload. Treat those as leading padding, then collect all
    consecutive payload lines until the next blank separator or timing line.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        match = WEBVTT_TIMING_RE.match(lines[index])
        if match is None:
            index += 1
            continue

        index += 1
        body_lines: list[str] = []
        while index < len(lines):
            line = lines[index]
            if WEBVTT_TIMING_RE.match(line):
                break
            if not line.strip():
                index += 1
                if body_lines:
                    break
                continue
            body_lines.append(line)
            index += 1

        body = re.sub(r"<[^>]+>", "", "\n".join(body_lines))
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            result.append(
                {
                    "start": _vtt_time(match.group("start")),
                    "end": _vtt_time(match.group("end")),
                    "text": body,
                }
            )
    return result


def _vtt_time(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


class TimedMediaStore:
    """Atomic, user-scoped store that never persists media bytes or stream URLs."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root or get_current_path_service().get_workspace_feature_dir("timed_media")
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, material_id: str) -> Path:
        if not MATERIAL_ID_RE.fullmatch(material_id or ""):
            raise TimedMediaNotFound("Timed media material was not found.")
        return self.root / f"{material_id}.json"

    def get(self, material_id: str) -> dict[str, Any]:
        try:
            payload = json.loads(self._path(material_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise TimedMediaNotFound("Timed media material was not found.") from exc
        if not isinstance(payload, dict) or payload.get("type") != "timed_media":
            raise TimedMediaNotFound("Timed media material was not found.")
        return payload

    def save(self, material: dict[str, Any]) -> dict[str, Any]:
        payload = dict(material)
        payload.pop("playback", None)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(self._path(str(payload.get("material_id") or "")), payload)
        return payload

    @contextmanager
    def lock(self, material_id: str):
        if not MATERIAL_ID_RE.fullmatch(material_id or ""):
            raise TimedMediaNotFound("Timed media material was not found.")
        lock_root = self.root / ".locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        # Binary + msvcrt on Windows (fcntl is Unix-only). Mirror
        # ``codex_auth.storage`` so importing this module does not break
        # ``deeptutor start`` on Windows (#1140 / #1143).
        with (lock_root / f"{material_id}.lock").open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def get_timed_media_store() -> TimedMediaStore:
    return TimedMediaStore()


def material_id_for(video_id: str) -> str:
    return hashlib.sha256(f"youtube-resolve-{video_id}".encode()).hexdigest()[:32]


async def _youtube_transcript(
    video_id: str, language: str
) -> tuple[list[dict[str, Any]], str, str]:
    settings = load_video_learning_settings()
    if settings["youtube"]["transcript_provider"] == "none":
        return [], "", "disabled"
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return [], "", "dependency_missing"

    def fetch() -> tuple[list[dict[str, Any]], str]:
        languages = [language] if language else ["zh-CN", "zh-Hans", "zh", "en"]
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            response = api.fetch(video_id, languages=languages)
            return normalize_cues(list(response)), str(getattr(response, "language_code", "") or "")
        return normalize_cues(
            YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        ), language

    try:
        cues, resolved_language = await asyncio.to_thread(fetch)
    except Exception:
        return [], "", "unavailable"
    return cues, resolved_language, "youtube_transcript_api" if cues else "unavailable"


async def _youtube_metadata(request: YouTubeRequest) -> dict[str, Any]:
    endpoint = "https://www.youtube.com/oembed"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(
                endpoint, params={"url": request.canonical_url, "format": "json"}
            )
            if response.status_code != 200:
                return {}
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


def _caption_choice(rows: Any, language: str) -> dict[str, Any] | None:
    captions = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    priorities = [language] if language else ["zh-CN", "zh-Hans", "zh", "en"]
    for preferred in priorities:
        found = next(
            (
                row
                for row in captions
                if str(row.get("languageCode") or row.get("language_code") or "") == preferred
            ),
            None,
        )
        if found:
            return found
    return next(
        (row for row in captions if not (row.get("autoGenerated") or row.get("auto_generated"))),
        None,
    ) or (captions[0] if captions else None)


async def _youtube_resolution(request: YouTubeRequest, language: str) -> ProviderResolution:
    metadata = await _youtube_metadata(request)
    cues, transcript_language, transcript_source = await _youtube_transcript(
        request.video_id, language
    )
    return ProviderResolution(metadata, cues, transcript_language, transcript_source, [])


async def _invidious_metadata(
    client: httpx.AsyncClient, base: str, video_id: str
) -> dict[str, Any]:
    response = await client.get(f"{base}/api/v1/videos/{video_id}")
    if response.status_code >= 400:
        raise TimedMediaError(f"Invidious request failed with HTTP {response.status_code}.")
    try:
        metadata = response.json()
    except ValueError as exc:
        raise TimedMediaError("Invidious returned invalid video metadata.") from exc
    if not isinstance(metadata, dict):
        raise TimedMediaError("Invidious returned invalid video metadata.")
    return metadata


async def _invidious_transcript(
    client: httpx.AsyncClient,
    base: str,
    video_id: str,
    captions: Any,
    language: str,
    *,
    raise_on_failure: bool = False,
) -> tuple[list[dict[str, Any]], str, str]:
    caption = _caption_choice(captions, language)
    if not caption:
        return [], "", "unavailable"

    label = str(caption.get("label") or "")
    transcript_language = str(
        caption.get("languageCode") or caption.get("language_code") or language
    )
    caption_response = await client.get(
        f"{base}/api/v1/captions/{video_id}",
        params={"label": label} if label else {},
    )
    if caption_response.status_code >= 400:
        if raise_on_failure:
            raise TimedMediaError(
                f"Invidious captions request failed with HTTP {caption_response.status_code}."
            )
        return [], transcript_language, "unavailable"
    if len(caption_response.content) > MAX_TRANSCRIPT_BYTES:
        if raise_on_failure:
            raise TimedMediaError("Invidious captions exceeded the safety limit.")
        return [], transcript_language, "unavailable"

    cues = normalize_cues(parse_webvtt(caption_response.text))
    return cues, transcript_language, "invidious" if cues else "unavailable"


async def _invidious_resolution(request: YouTubeRequest, language: str) -> ProviderResolution:
    settings = load_video_learning_settings()
    base = settings["invidious"]["api_base_url"]
    if not base:
        raise TimedMediaError("Invidious is not configured.")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        metadata = await _invidious_metadata(client, base, request.video_id)
        cues, transcript_language, transcript_source = await _invidious_transcript(
            client, base, request.video_id, metadata.get("captions"), language
        )
        formats: list[dict[str, Any]] = []
        for row in metadata.get("formatStreams") or []:
            if not isinstance(row, dict):
                continue
            mime = str(row.get("type") or "").split(";", 1)[0]
            itag = str(row.get("itag") or "")
            if mime != "video/mp4" or not re.fullmatch(r"[0-9]{1,6}", itag):
                continue
            formats.append(
                {
                    "format_id": itag,
                    "mime_type": mime,
                    "quality": str(row.get("qualityLabel") or row.get("quality") or ""),
                }
            )
        if not formats:
            raise TimedMediaError("Invidious returned no compatible MP4 stream.")
        return ProviderResolution(
            metadata,
            cues,
            transcript_language,
            transcript_source,
            formats,
        )


PROVIDER_RESOLVERS: dict[
    ProviderName,
    Callable[[YouTubeRequest, str], Awaitable[ProviderResolution]],
] = {
    "youtube": lambda request, language: _youtube_resolution(request, language),
    "invidious": lambda request, language: _invidious_resolution(request, language),
}


async def resolve_material(
    url: str,
    language: str = "",
    provider_override: ProviderName | None = None,
) -> dict[str, Any]:
    request = parse_youtube_url(url)
    settings = load_video_learning_settings()
    store = get_timed_media_store()
    material_id = material_id_for(request.video_id)
    provider = provider_override or settings["default_provider"]
    resolution = await PROVIDER_RESOLVERS[provider](request, language)
    metadata = resolution.metadata
    cues = resolution.cues
    transcript_language = resolution.transcript_language
    transcript_source = resolution.transcript_source
    formats = resolution.formats or []
    try:
        existing = store.get(material_id)
    except TimedMediaNotFound:
        existing = {}
    duration = int(
        float(
            metadata.get("lengthSeconds")
            or existing.get("metadata", {}).get("duration_seconds")
            or 0
        )
    )
    learning: dict[str, Any] = (
        existing["learning"]
        if isinstance(existing.get("learning"), dict)
        else {"last_position": request.entry_time_seconds}
    )
    learning.setdefault("last_position", request.entry_time_seconds)
    material = {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "created_at": existing.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "youtube",
            "video_id": request.video_id,
            "url": f"https://youtu.be/{request.video_id}",
            "entry_time_seconds": request.entry_time_seconds,
        },
        "metadata": {
            "title": str(
                metadata.get("title")
                or existing.get("metadata", {}).get("title")
                or request.video_id
            ),
            "author": str(
                metadata.get("author_name")
                or metadata.get("author")
                or existing.get("metadata", {}).get("author")
                or ""
            ),
            "duration_seconds": duration,
            "thumbnail_url": str(metadata.get("thumbnail_url") or ""),
        },
        "transcript": {
            "status": "ready" if cues else "unavailable",
            "reason": "" if cues else transcript_source,
            "language": transcript_language,
            "source": transcript_source,
            "cues": cues,
        },
        "segments": build_segments(cues),
        "learning": learning,
        "provider_cache": {"invidious_formats": formats} if formats else {},
    }
    with store.lock(material_id):
        # Network resolution happens outside the file lock. Re-read only the
        # mutable learning state so a concurrent progress save cannot be lost.
        try:
            latest = store.get(material_id)
        except TimedMediaNotFound:
            latest = {}
        if isinstance(latest.get("learning"), dict):
            material["learning"] = latest["learning"]
        store.save(material)
    return public_material(material, provider=provider)


async def material_with_playback(material_id: str) -> dict[str, Any]:
    material = get_timed_media_store().get(material_id)
    provider = load_video_learning_settings()["default_provider"]
    if provider == "invidious" and not material.get("provider_cache", {}).get("invidious_formats"):
        source = material.get("source") if isinstance(material.get("source"), dict) else {}
        request = parse_youtube_url(str(source.get("url") or ""))
        resolution = await PROVIDER_RESOLVERS["invidious"](request, "")
        metadata = resolution.metadata
        cues = resolution.cues
        transcript_language = resolution.transcript_language
        formats = resolution.formats or []
        material["metadata"] = {
            **(material.get("metadata") or {}),
            "title": str(
                metadata.get("title")
                or material.get("metadata", {}).get("title")
                or request.video_id
            ),
            "author": str(
                metadata.get("author") or material.get("metadata", {}).get("author") or ""
            ),
            "duration_seconds": int(
                float(
                    metadata.get("lengthSeconds")
                    or material.get("metadata", {}).get("duration_seconds")
                    or 0
                )
            ),
        }
        if cues:
            material["transcript"] = {
                "status": "ready",
                "reason": "",
                "language": transcript_language,
                "source": "invidious",
                "cues": cues,
            }
            material["segments"] = build_segments(cues)
        material["provider_cache"] = {"invidious_formats": formats}
        get_timed_media_store().save(material)
    return public_material(material, provider=provider)


async def refresh_invidious_transcript(material_id: str) -> dict[str, Any]:
    """Refresh one stored material's captions without changing its playback state."""
    store = get_timed_media_store()
    material = store.get(material_id)
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    video_id = str(source.get("video_id") or "")
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise TimedMediaNotFound("Timed media material was not found.")
    if not material.get("provider_cache", {}).get("invidious_formats"):
        raise TimedMediaError("Invidious playback is not available for this material.")

    settings = load_video_learning_settings()
    base = settings["invidious"]["api_base_url"]
    if not base:
        raise TimedMediaError("Invidious is not configured.")
    transcript = material.get("transcript") if isinstance(material.get("transcript"), dict) else {}
    language = str(transcript.get("language") or "")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        metadata = await _invidious_metadata(client, base, video_id)
        cues, transcript_language, transcript_source = await _invidious_transcript(
            client,
            base,
            video_id,
            metadata.get("captions"),
            language,
            raise_on_failure=True,
        )

    refreshed_transcript = {
        "status": "ready" if cues else "unavailable",
        "reason": "" if cues else transcript_source,
        "language": transcript_language,
        "source": transcript_source,
        "cues": cues,
    }
    with store.lock(material_id):
        latest = store.get(material_id)
        latest["transcript"] = refreshed_transcript
        latest["segments"] = build_segments(cues)
        saved = store.save(latest)
    return public_material(saved, provider="invidious")


def public_material(material: dict[str, Any], *, provider: str) -> dict[str, Any]:
    payload = {key: value for key, value in material.items() if key != "provider_cache"}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    learning = payload.get("learning") if isinstance(payload.get("learning"), dict) else {}
    start = float(learning.get("last_position") or source.get("entry_time_seconds") or 0)
    video_id = str(source.get("video_id") or "")
    if provider == "invidious":
        formats = material.get("provider_cache", {}).get("invidious_formats") or []
        best = formats[0] if formats else {}
        revision = str(material.get("updated_at") or "")
        subtitles_url = f"/api/video-learning/materials/{payload['material_id']}/subtitles.vtt"
        if revision:
            subtitles_url = f"{subtitles_url}?{urlencode({'revision': revision})}"
        payload["playback"] = {
            "provider": "invidious",
            "kind": "html5",
            "format_id": str(best.get("format_id") or ""),
            "mime_type": str(best.get("mime_type") or "video/mp4"),
            "stream_url": f"/api/video-learning/materials/{payload['material_id']}/stream/{best.get('format_id', '')}",
            "subtitles_url": subtitles_url,
            "start_seconds": start,
        }
    else:
        payload["playback"] = {
            "provider": "youtube",
            "kind": "youtube_iframe",
            "video_id": video_id,
            "start_seconds": start,
        }
    return payload


async def test_invidious_connection(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = normalize_video_learning_settings(settings or load_video_learning_settings())
    base = payload["invidious"]["api_base_url"]
    if not base:
        return {"ok": False, "message": "Invidious API base URL is not configured."}
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.get(f"{base}/api/v1/stats")
        return {"ok": response.status_code == 200, "message": f"HTTP {response.status_code}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "message": str(exc)}


__all__ = [
    "DEFAULT_VIDEO_LEARNING_SETTINGS",
    "PROVIDER_RESOLVERS",
    "ProviderResolution",
    "TimedMediaError",
    "TimedMediaNotFound",
    "TimedMediaStore",
    "build_segments",
    "get_timed_media_store",
    "load_video_learning_settings",
    "material_with_playback",
    "normalize_cues",
    "normalize_video_learning_settings",
    "parse_timestamp",
    "parse_webvtt",
    "parse_youtube_url",
    "public_material",
    "refresh_invidious_transcript",
    "resolve_material",
    "save_video_learning_settings",
    "test_invidious_connection",
]
