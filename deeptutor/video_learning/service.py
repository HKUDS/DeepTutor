"""YouTube-backed timed media materials for Immersive Watching.

The service keeps only metadata, captions, learning segments and short-lived
stream descriptors. It never writes a complete video to the workspace. The
configured Invidious instance is the primary provider; optional Python
packages are consulted only when the instance cannot provide a transcript or
metadata.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
from html import unescape
import ipaddress
import json
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx

from deeptutor.multi_user.paths import get_current_path_service
from deeptutor.services.file_io import atomic_write_json
from deeptutor.tools.web_fetch import _is_disallowed_host

MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MAX_TRANSCRIPT_CUES = 20_000
MAX_SEGMENT_SECONDS = 90
MIN_SEGMENT_SECONDS = 20
STREAM_TIMEOUT_SECONDS = 30.0
MAX_INVIDIOUS_REDIRECTS = 3
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
TAILSCALE_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


class TimedMediaError(RuntimeError):
    """A user-facing timed media failure."""


class TimedMediaNotFound(TimedMediaError):
    """A material does not belong to the current user."""


@dataclass(frozen=True, slots=True)
class YouTubeRequest:
    video_id: str
    canonical_url: str
    entry_time_seconds: int = 0


def parse_youtube_url(value: str) -> YouTubeRequest:
    parsed = urlparse((value or "").strip().strip("`\"'"))
    if parsed.scheme not in {"http", "https"}:
        raise TimedMediaError("YouTube URL must use http or https.")
    host = (parsed.hostname or "").lower().rstrip(".")
    query = parse_qs(parsed.query)
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = query.get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = parsed.path.split("/", 2)[2]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise TimedMediaError("Unsupported or invalid YouTube URL.")
    entry = parse_timestamp(query.get("t", query.get("start", ["0"]))[0])
    canonical_query = {"t": str(entry)} if entry else {}
    canonical = urlunparse(("https", "youtu.be", f"/{video_id}", "", urlencode(canonical_query), ""))
    return YouTubeRequest(video_id=video_id, canonical_url=canonical, entry_time_seconds=entry)


def parse_timestamp(value: Any) -> int:
    raw = str(value or "").strip().lower()
    if raw.isdigit():
        return max(0, int(raw))
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw)
    if not match or not any(match.groups()):
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return max(0, hours * 3600 + minutes * 60 + seconds)


def format_timestamp(seconds: float | int) -> str:
    total = max(0, int(float(seconds or 0)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def normalize_cues(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows[:MAX_TRANSCRIPT_CUES]:
        if isinstance(row, dict):
            snippet = row.get("snippet")
            merged = row | snippet if isinstance(snippet, dict) else row
        else:
            merged = {
                "start": getattr(row, "start", 0),
                "duration": getattr(row, "duration", 0),
                "text": getattr(row, "text", ""),
            }
        text = unescape(str(merged.get("text") or merged.get("content") or "")).strip()
        if not text:
            continue
        try:
            start = max(0.0, float(merged.get("start") or merged.get("from") or merged.get("startMs", 0) / 1000))
            end = float(merged.get("end") or merged.get("to") or merged.get("endMs", 0) / 1000)
            if end <= start:
                end = start + float(merged.get("duration") or merged.get("durationMs", 0) / 1000 or 0)
        except (TypeError, ValueError):
            continue
        result.append({"start": start, "end": max(start, end), "text": text})
    return result


def build_segments(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine tiny subtitle cues into stable 20-90 second learning units."""
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for cue in cues:
        if current is None:
            current = {"start": cue["start"], "end": cue["end"], "text": cue["text"]}
            continue
        gap = max(0.0, float(cue["start"]) - float(current["end"]))
        length = float(cue["end"]) - float(current["start"])
        sentence_end = str(current["text"]).rstrip().endswith((".", "!", "?", "。", "！", "？"))
        if length < MAX_SEGMENT_SECONDS and gap <= 4 and not (length >= MIN_SEGMENT_SECONDS and sentence_end):
            current["end"] = cue["end"]
            current["text"] = f'{current["text"]} {cue["text"]}'.strip()
        else:
            segments.append(current)
            current = {"start": cue["start"], "end": cue["end"], "text": cue["text"]}
    if current is not None:
        segments.append(current)
    for locator, segment in enumerate(segments, start=1):
        segment["locator"] = locator
    return segments


class TimedMediaStore:
    """Atomic, user-scoped JSON store for timed media materials."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or get_current_path_service().get_workspace_feature_dir("timed_media")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, material_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{16,64}", material_id or ""):
            raise TimedMediaNotFound("Timed media material was not found.")
        return self.root / f"{material_id}.json"

    def get(self, material_id: str) -> dict[str, Any]:
        path = self._path(material_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise TimedMediaNotFound("Timed media material was not found.") from exc
        if not isinstance(data, dict) or data.get("type") != "timed_media":
            raise TimedMediaNotFound("Timed media material was not found.")
        return data

    def save(self, material: dict[str, Any]) -> dict[str, Any]:
        material_id = str(material.get("material_id") or "")
        path = self._path(material_id)
        material["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(path, material)
        return material

    @contextmanager
    def lock(self, material_id: str):
        """Serialize writers for one material across local processes."""
        material_id = str(material_id or "")
        if not re.fullmatch(r"[0-9a-f]{16,64}", material_id):
            raise TimedMediaNotFound("Timed media material was not found.")
        lock_root = self.root / ".locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        with (lock_root / f"{material_id}.lock").open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def find_by_video_id(self, video_id: str) -> dict[str, Any] | None:
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("type") != "timed_media":
                continue
            source = data.get("source") if isinstance(data.get("source"), dict) else {}
            if str(source.get("video_id") or "") == video_id:
                return data
        return None

    def create(self, material: dict[str, Any]) -> dict[str, Any]:
        material = dict(material)
        if not str(material.get("material_id") or ""):
            material["material_id"] = hashlib.sha256(
                f'{material.get("source", {}).get("video_id", "")}-{datetime.now(timezone.utc).timestamp()}'.encode()
            ).hexdigest()[:32]
        material.setdefault("version", 1)
        material.setdefault("type", "timed_media")
        material.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        return self.save(material)


def get_timed_media_store() -> TimedMediaStore:
    return TimedMediaStore()


def ensure_remote_material(video_id: str, *, title: str = "", duration_seconds: float = 0) -> dict[str, Any]:
    """Get or create an owner-scoped material for a feed-launched Invidious video."""
    video_id = video_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise TimedMediaError("Invalid Invidious video ID.")
    store = get_timed_media_store()
    existing = store.find_by_video_id(video_id)
    if existing is not None:
        return existing

    material_id = hashlib.sha256(f"invidious-remote-{video_id}".encode()).hexdigest()[:32]
    duration = max(0.0, float(duration_seconds or 0))
    title = str(title or video_id).strip() or video_id
    with store.lock(material_id):
        try:
            return store.get(material_id)
        except TimedMediaNotFound:
            material = {
                "version": 1,
                "type": "timed_media",
                "material_id": material_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": {
                    "provider": "youtube",
                    "video_id": video_id,
                    "url": f"https://youtu.be/{video_id}",
                    "entry_time_seconds": 0,
                    "duration_seconds": duration,
                },
                "metadata": {
                    "title": title,
                    "author": "",
                    "duration_seconds": duration,
                    "chapters": [],
                },
                "transcript": {"language": "", "source": "", "cues": []},
                "segments": [],
                "playback": {
                    "formats": {},
                    "official_url": f"https://youtu.be/{video_id}",
                },
                "learning": {"last_position": 0, "notes": [], "questions": [], "marks": []},
            }
            return store.save(material)


class YouTubeResolver:
    """Resolve metadata, captions and short-lived playback URLs through Invidious."""

    def __init__(self, *, base_url: str | None = None, timeout: float = 15.0) -> None:
        if base_url is None:
            from deeptutor.services.config.runtime_settings import load_integrations_settings

            base_url = str(load_integrations_settings().get("invidious_base_url") or "")
        self.base_url = _validate_instance_url(base_url)
        self.timeout = timeout

    def resolve_url(self, url: str) -> YouTubeRequest:
        """Normalize a YouTube URL without performing a network request."""
        return parse_youtube_url(url)

    async def get_metadata(self, video_id: str) -> dict[str, Any]:
        """Return metadata from the configured Invidious instance."""
        _validate_video_id(video_id)
        if not self.base_url:
            return {}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            payload = await self._json(client, f"{self.base_url}/api/v1/videos/{video_id}")
        return payload if isinstance(payload, dict) else {}

    async def get_transcript(
        self,
        video_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        """Return normalized cues, language, and the provider name."""
        _validate_video_id(video_id)
        if not self.base_url:
            return await self._optional_transcript(video_id)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            if metadata is None:
                metadata = await self._json(client, f"{self.base_url}/api/v1/videos/{video_id}")
            return await self._transcript(client, video_id, metadata or {})

    async def get_playback_formats(
        self,
        video_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return compatible muxed MP4 descriptors without downloading media."""
        _validate_video_id(video_id)
        if metadata is None:
            metadata = await self.get_metadata(video_id)
        return _formats(metadata.get("formatStreams")) or _formats(metadata.get("formats"), yt_dlp=True)

    async def get_storyboard(
        self,
        video_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Return storyboard descriptors only; frames are not fetched in V1."""
        _validate_video_id(video_id)
        if metadata is None:
            metadata = await self.get_metadata(video_id)
        return metadata.get("storyboards") or metadata.get("storyboard") or []

    async def get_audio_source(
        self,
        video_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return an audio-only descriptor for an explicit ASR job."""
        _validate_video_id(video_id)
        if metadata is None:
            metadata = await self.get_metadata(video_id)
        rows = metadata.get("adaptiveFormats") or metadata.get("formats") or []
        if not isinstance(rows, list):
            return None
        candidates = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("type") or row.get("mimeType") or "").startswith("audio/")
            and row.get("url")
        ]
        return min(candidates, key=lambda row: float(row.get("bitrate") or row.get("audioBitrate") or 0)) if candidates else None

    async def resolve(
        self,
        url: str,
        *,
        language: str = "",
        store: TimedMediaStore | None = None,
    ) -> dict[str, Any]:
        request = parse_youtube_url(url)
        metadata: dict[str, Any] = {}
        cues: list[dict[str, Any]] = []
        language = language.strip()
        transcript_source = ""
        if self.base_url:
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                    response = await self._json(client, f"{self.base_url}/api/v1/videos/{request.video_id}")
                    if isinstance(response, dict):
                        metadata = response
                        cues, language, transcript_source = await self._transcript(
                            client,
                            request.video_id,
                            metadata,
                            preferred_language=language,
                        )
            except (TimedMediaError, httpx.HTTPError):
                metadata = {}
        if not metadata or not _formats(metadata.get("formatStreams")):
            optional = await _optional_ytdlp_metadata(request.canonical_url)
            metadata = _merge_metadata(metadata, optional)
        if not cues:
            cues, language, transcript_source = await self._optional_transcript(
                request.video_id,
                preferred_language=language,
            )
        if not metadata:
            raise TimedMediaError("Video metadata is unavailable. Configure Invidious or install the video-learning extra.")
        duration = _duration(metadata)
        segments = build_segments(cues)
        formats = _formats(metadata.get("formatStreams")) or _formats(metadata.get("formats"), yt_dlp=True)
        if not formats:
            raise TimedMediaError("Invidious returned no compatible muxed MP4 stream. Open the video in YouTube instead.")
        playback = {item["format_id"]: item for item in formats}
        material = {
            "version": 1,
            "type": "timed_media",
            "material_id": "",
            "source": {
                "provider": "youtube",
                "video_id": request.video_id,
                "url": request.canonical_url.split("?", 1)[0],
                "entry_time_seconds": request.entry_time_seconds,
                "duration_seconds": duration,
            },
            "metadata": {
                "title": str(metadata.get("title") or request.video_id),
                "author": str(metadata.get("author") or ""),
                "duration_seconds": duration,
                "chapters": _chapters(metadata.get("chapters")),
                "thumbnails": metadata.get("videoThumbnails") or metadata.get("thumbnails") or [],
                "storyboards": metadata.get("storyboards") or metadata.get("storyboard") or [],
            },
            "transcript": {"language": language, "source": transcript_source, "cues": cues},
            "segments": segments,
            "playback": {
                "formats": playback,
                "official_url": f"https://youtu.be/{request.video_id}?t={request.entry_time_seconds}" if request.entry_time_seconds else f"https://youtu.be/{request.video_id}",
            },
            "learning": {"last_position": request.entry_time_seconds, "notes": [], "questions": [], "marks": []},
        }
        target_store = store or get_timed_media_store()
        existing = target_store.find_by_video_id(request.video_id)
        material_id = str(
            (existing or {}).get("material_id")
            or hashlib.sha256(f"youtube-resolve-{request.video_id}".encode()).hexdigest()[:32]
        )
        with target_store.lock(material_id):
            try:
                saved = target_store.get(material_id)
            except TimedMediaNotFound:
                saved = material
                saved["material_id"] = material_id
                saved.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            # Resolution enriches provider data but must not reset learning state. This
            # also unifies feed-launched remote materials with Watch-resolved materials.
            saved["source"] = material["source"]
            saved["metadata"] = material["metadata"]
            saved["transcript"] = material["transcript"]
            saved["segments"] = material["segments"]
            saved["playback"] = material["playback"]
            return target_store.save(saved)

    async def refresh_formats(self, material: dict[str, Any]) -> dict[str, Any]:
        video_id = str(material.get("source", {}).get("video_id") or "")
        if not video_id:
            raise TimedMediaError("Timed media material has no YouTube video id.")
        metadata: dict[str, Any] = {}
        if self.base_url:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await self._json(client, f"{self.base_url}/api/v1/videos/{video_id}")
                if isinstance(response, dict):
                    metadata = response
        if not metadata:
            metadata = await _optional_ytdlp_metadata(str(material.get("source", {}).get("url") or ""))
        formats = _formats(metadata.get("formatStreams")) or _formats(metadata.get("formats"), yt_dlp=True)
        if not formats:
            raise TimedMediaError("Invidious returned no compatible MP4 stream.")
        material.setdefault("playback", {})["formats"] = {item["format_id"]: item for item in formats}
        return material

    async def _json(self, client: httpx.AsyncClient, url: str) -> Any:
        response = await self._get(client, url)
        payload = response.json()
        return payload

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        current = url
        for _ in range(MAX_INVIDIOUS_REDIRECTS + 1):
            response = await client.get(current, follow_redirects=False)
            final_url = str(response.url or current)
            _ensure_same_host(self.base_url, final_url)
            if response.is_redirect:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise TimedMediaError("Invidious returned an invalid redirect.")
                current = urljoin(current, location)
                _ensure_same_host(self.base_url, current)
                continue
            _ensure_response(response)
            return response
        raise TimedMediaError("Invidious returned too many redirects.")

    async def _transcript(
        self,
        client: httpx.AsyncClient,
        video_id: str,
        metadata: dict[str, Any],
        *,
        preferred_language: str = "",
    ) -> tuple[list[dict[str, Any]], str, str]:
        captions = metadata.get("captions") if isinstance(metadata.get("captions"), list) else []
        selected = _select_caption(captions, preferred_language)
        if selected:
            language = str(selected.get("languageCode") or selected.get("language_code") or "")
            label = str(selected.get("label") or "")
            query = (
                urlencode({"lang": language})
                if language
                else urlencode({"label": label})
                if label
                else ""
            )
            try:
                payload = await self._json(client, f"{self.base_url}/api/v1/transcripts/{video_id}{f'?{query}' if query else ''}")
                rows = payload.get("transcript", payload) if isinstance(payload, dict) else payload
                cues = normalize_cues(rows)
                if cues:
                    return cues, language, "invidious"
            except (TimedMediaError, httpx.HTTPError, ValueError):
                pass
            response = await self._get(client, f"{self.base_url}/api/v1/captions/{video_id}{f'?{query}' if query else ''}")
            if len(response.content) > MAX_TRANSCRIPT_BYTES:
                raise TimedMediaError("YouTube transcript exceeded the safety limit.")
            cues = normalize_cues(parse_webvtt(response.text))
            if cues:
                return cues, language, "invidious"
        return await self._optional_transcript(video_id, preferred_language=preferred_language)

    async def _optional_transcript(
        self,
        video_id: str,
        *,
        preferred_language: str = "",
    ) -> tuple[list[dict[str, Any]], str, str]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            return [], "", ""

        def fetch() -> tuple[list[dict[str, Any]], str]:
            api = YouTubeTranscriptApi()
            languages = [preferred_language] if preferred_language else ["zh-CN", "zh-Hans", "zh", "en"]
            if hasattr(api, "fetch"):
                result = api.fetch(video_id, languages=languages)
                return normalize_cues(list(result)), str(getattr(result, "language_code", "") or "")
            return normalize_cues(YouTubeTranscriptApi.get_transcript(video_id, languages=languages)), ""

        try:
            cues, language = await asyncio.to_thread(fetch)
        except Exception:
            return [], "", ""
        return cues, language, "youtube-transcript-api" if cues else ""


def _is_html_error_response(text: str) -> bool:
    stripped = text.lstrip().lower()
    return (
        stripped.startswith(("<!doctype html", "<html", "<head", "<?xml"))
        or "<title>sorry" in stripped
        or "google.com/sorry" in stripped
    )


def _rank_captions(captions: list[Any], preferred_language: str = "") -> list[dict[str, Any]]:
    rows = [row for row in captions if isinstance(row, dict)]
    if not rows:
        return []
    priorities = [preferred_language] if preferred_language else ["zh-CN", "zh-Hans", "zh", "en"]
    matched: list[dict[str, Any]] = []
    for language in priorities:
        for row in rows:
            if str(row.get("languageCode") or row.get("language_code") or "") == language and row not in matched:
                matched.append(row)
    for row in rows:
        if not row.get("autoGenerated") and not row.get("auto_generated") and row not in matched:
            matched.append(row)
    for row in rows:
        if row not in matched:
            matched.append(row)
    return matched

def parse_webvtt(text: str) -> list[dict[str, Any]]:
    timing = re.compile(
        r"^(?P<start>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+"
        r"(?P<end>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})(?:\s+.*)?$"
    )
    lines = text.splitlines()
    result: list[dict[str, Any]] = []
    has_rolling_timestamps = False
    index = 0
    while index < len(lines):
        match = timing.match(lines[index].strip())
        if not match:
            index += 1
            continue
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        body_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            body_lines.append(lines[index].strip())
            index += 1
        raw_body = "\n".join(body_lines)
        has_rolling_timestamps = has_rolling_timestamps or bool(
            re.search(r"<\d{2}:\d{2}(?::\d{2})?[.,]\d{3}>", raw_body)
        )
        body = unescape(re.sub(r"<[^>]+>", "", raw_body)).strip()
        if body:
            result.append(
                {
                    "start": _vtt_time(match.group("start")),
                    "end": _vtt_time(match.group("end")),
                    "text": body,
                }
            )
    if has_rolling_timestamps:
        return _normalize_rolling_vtt(result)
    return [{**cue, "text": " ".join(str(cue["text"]).splitlines())} for cue in result]


def _normalize_rolling_vtt(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse YouTube's 10 ms echo cues without changing ordinary VTT."""
    result: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        lines = _unique_caption_lines(str(cue["text"]))
        text = " ".join(lines)
        duration = float(cue["end"]) - float(cue["start"])
        next_text = _collapse_repeated_lines(str(cues[index + 1]["text"])) if index + 1 < len(cues) else ""
        if duration <= 0.05 and next_text and _rolling_text_contains(next_text, text):
            continue
        if result and len(lines) > 1 and _rolling_text_contains(str(result[-1]["text"]), lines[0]):
            text = " ".join(lines[1:])
        if not text:
            continue
        normalized = {**cue, "text": text}
        if result and _normalized_caption_text(result[-1]["text"]) == _normalized_caption_text(text):
            result[-1]["end"] = max(float(result[-1]["end"]), float(cue["end"]))
            continue
        result.append(normalized)
    return result


def _collapse_repeated_lines(text: str) -> str:
    return " ".join(_unique_caption_lines(text))


def _unique_caption_lines(text: str) -> list[str]:
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return lines
    collapsed: list[str] = []
    for line in lines:
        if collapsed and _normalized_caption_text(collapsed[-1]) == _normalized_caption_text(line):
            continue
        collapsed.append(line)
    return collapsed


def _normalized_caption_text(text: str) -> str:
    return " ".join(unescape(str(text)).split()).casefold()


def _rolling_text_contains(container: str, value: str) -> bool:
    container_normalized = _normalized_caption_text(container)
    value_normalized = _normalized_caption_text(value)
    return bool(value_normalized) and (
        container_normalized.startswith(value_normalized)
        or container_normalized.endswith(value_normalized)
        or value_normalized in container_normalized
    )


def _vtt_time(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _validate_instance_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise TimedMediaError("Invidious base URL must be a plain HTTP(S) origin.")
    host = parsed.hostname.lower().rstrip(".")
    if parsed.scheme != "https" and not _is_local_host(host):
        raise TimedMediaError("A public Invidious instance must use HTTPS.")
    if _is_disallowed_host(host) and not _is_local_host(host):
        raise TimedMediaError("Invidious base URL resolves to a private host.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_local_host(host: str) -> bool:
    if host in {"localhost", "invidious", "host.docker.internal"}:
        return True
    if host.endswith(".local") or host.endswith(".ts.net"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local or address in TAILSCALE_CGNAT_NET


def _ensure_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise TimedMediaError(f"Invidious request failed with HTTP {response.status_code}.")


def _ensure_same_host(expected: str, actual: str) -> None:
    if urlparse(expected).netloc.lower() != urlparse(actual).netloc.lower():
        raise TimedMediaError("Invidious redirected outside the configured instance.")


def _duration(metadata: dict[str, Any]) -> int:
    try:
        return int(float(metadata.get("lengthSeconds") or metadata.get("duration") or 0))
    except (TypeError, ValueError):
        return 0


def _validate_video_id(video_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise TimedMediaError("Invalid YouTube video id.")


async def download_ytdlp_subtitle(video_id: str, *, preferred_language: str = "") -> tuple[list[dict[str, Any]], str, str]:
    """Fetch only captions through yt-dlp and the host Chrome cookie store."""
    _validate_video_id(video_id)
    languages = [preferred_language] if preferred_language else []
    languages.extend(language for language in ("en-orig", "en", "zh-Hans", "zh-CN", "zh") if language not in languages)

    def fetch() -> tuple[list[dict[str, Any]], str, str]:
        try:
            import yt_dlp
        except ImportError:
            return [], "", "dependency_unavailable"
        with tempfile.TemporaryDirectory(prefix="deeptutor-youtube-subs-") as directory:
            root = Path(directory)
            options = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "ignoreconfig": True,
                "cachedir": False,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": languages,
                "subtitlesformat": "vtt",
                "outtmpl": str(root / "subtitle.%(ext)s"),
                "paths": {"home": str(root)},
                "cookiesfrombrowser": ("chrome",),
            }
            try:
                with yt_dlp.YoutubeDL(options) as downloader:
                    downloader.download([f"https://www.youtube.com/watch?v={video_id}"])
            except Exception as exc:
                message = str(exc).lower()
                if any(marker in message for marker in ("sign in", "cookies", "login", "authentication")):
                    return [], "", "auth_required"
                return [], "", "unavailable"
            for candidate in sorted(root.glob("subtitle.*.vtt")):
                try:
                    if candidate.stat().st_size > MAX_TRANSCRIPT_BYTES:
                        continue
                    cues = normalize_cues(parse_webvtt(candidate.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
                if cues:
                    return cues, candidate.stem.rsplit(".", 1)[-1], "youtube-chrome"
            return [], "", "unavailable"

    return await asyncio.to_thread(fetch)


def _select_caption(captions: list[Any], preferred_language: str = "") -> dict[str, Any] | None:
    rows = [row for row in captions if isinstance(row, dict)]
    priorities = [preferred_language] if preferred_language else ["zh-CN", "zh-Hans", "zh", "en"]
    for language in priorities:
        found = next((row for row in rows if str(row.get("languageCode") or row.get("language_code") or "") == language), None)
        if found:
            return found
    return next((row for row in rows if not row.get("autoGenerated") and not row.get("auto_generated")), None) or (rows[0] if rows else None)


def _formats(value: Any, *, yt_dlp: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("type") or item.get("mimeType") or "").split(";", 1)[0]
        if yt_dlp and not mime:
            mime = "video/mp4" if str(item.get("ext") or "") == "mp4" else ""
        url = str(item.get("url") or "").strip()
        if yt_dlp and (str(item.get("vcodec") or "none") == "none" or str(item.get("acodec") or "none") == "none"):
            continue
        if mime != "video/mp4" or not url or not url.startswith(("https://", "http://")):
            continue
        format_id = str(item.get("itag") or item.get("format_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", format_id):
            format_id = hashlib.sha256(url.encode()).hexdigest()[:12]
        base_format_id = format_id
        suffix = 2
        while format_id in seen_ids:
            format_id = f"{base_format_id}-{suffix}"
            suffix += 1
        seen_ids.add(format_id)
        result.append({
            "format_id": format_id,
            "url": url,
            "mime_type": mime,
            "quality": str(item.get("qualityLabel") or item.get("quality") or ""),
            "content_length": int(item.get("clen") or 0) if str(item.get("clen") or "").isdigit() else 0,
        })
    result.sort(key=lambda row: _quality_rank(row["quality"]), reverse=True)
    return result


async def _optional_ytdlp_metadata(url: str) -> dict[str, Any]:
    if not url:
        return {}

    def extract() -> dict[str, Any]:
        try:
            import yt_dlp
        except ImportError:
            return {}
        options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "ignoreconfig": True, "cachedir": False}
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                data = downloader.extract_info(url, download=False)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    return await asyncio.to_thread(extract)


def _merge_metadata(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(fallback)
    result.update({key: value for key, value in primary.items() if value not in (None, "", [], {})})
    return result


def _quality_rank(value: str) -> int:
    match = re.search(r"(\d+)p", value)
    return int(match.group(1)) if match else 0


def _chapters(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for row in value:
        if not isinstance(row, dict):
            continue
        try:
            start = int(float(row.get("startTime") or row.get("start_time") or row.get("start") or 0))
        except (TypeError, ValueError):
            continue
        result.append({"start": max(0, start), "title": str(row.get("title") or "")})
    return result


# Public names keep the provider boundary explicit for future Bilibili and
# local-media adapters while the V1 implementation remains Invidious-backed.
InvidiousAdapter = YouTubeResolver
YouTubeProvider = YouTubeResolver


__all__ = [
    "TimedMediaError",
    "TimedMediaNotFound",
    "TimedMediaStore",
    "InvidiousAdapter",
    "YouTubeProvider",
    "YouTubeRequest",
    "YouTubeResolver",
    "build_segments",
    "format_timestamp",
    "get_timed_media_store",
    "normalize_cues",
    "parse_timestamp",
    "parse_webvtt",
    "parse_youtube_url",
]
