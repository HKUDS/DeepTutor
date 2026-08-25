"""Video-page learning extraction for the chat ``web_fetch`` tool.

Bilibili uses its public metadata and subtitle JSON APIs. YouTube uses the
optional ``youtube-transcript-api`` package first and a configured Invidious
instance as the network fallback. Neither path downloads a complete video.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from uuid import uuid4

import httpx

from deeptutor.services.file_io import atomic_write_json
from deeptutor.tools.web_fetch import _is_disallowed_host

VideoProvider = Literal["bilibili", "youtube"]

DEFAULT_TIMEOUT_S = 15.0
DEFAULT_USER_AGENT = "DeepTutor/1.0 (+https://hkuds.dev/deeptutor)"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_INVIDIOUS_REDIRECTS = 3

_BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)
_AVID_RE = re.compile(r"(av\d+)", re.IGNORECASE)
_SUBTITLE_LANGUAGE_PRIORITY = ("zh-CN", "ai-zh", "zh-Hans")


@dataclass(frozen=True)
class VideoLearningOutcome:
    ok: bool = False
    provider: VideoProvider = "bilibili"
    markdown: str = ""
    url: str = ""
    title: str = ""
    author: str = ""
    duration_seconds: int = 0
    subtitle_language: str = ""
    transcript_source: str = ""
    entry_time_seconds: int = 0
    context_start_seconds: int = 0
    context_end_seconds: int = 0
    chapters: list[dict[str, Any]] = field(default_factory=list)
    preprocessing: bool = False
    preprocessing_status: str = ""
    job_id: str = ""
    truncated: bool = False
    error: str = ""
    transcript: list[dict[str, Any]] = field(default_factory=list)


_PREPARE_TASKS: dict[tuple[Path, str], asyncio.Task[None]] = {}


def detect_video_provider(url: str) -> VideoProvider | None:
    """Return the reserved video provider for a URL, or ``None``."""
    parsed = urlparse((url or "").strip().strip("`\"'"))
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path or ""
    if host == "b23.tv" and path.strip("/"):
        return "bilibili"
    if host.endswith(".bilibili.com") or host == "bilibili.com":
        return "bilibili" if "/video/" in path else None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        return (
            "youtube"
            if path == "/watch"
            or path.startswith(("/watch/", "/shorts/", "/live/", "/embed/"))
            else None
        )
    if host == "youtu.be":
        return "youtube" if path.strip("/") else None
    return None


async def learn_video(
    url: str,
    *,
    max_chars: int,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    user_agent: str = DEFAULT_USER_AGENT,
    client_factory: Any = None,
    host_validator: Any = None,
    generate_transcript_if_missing: bool = False,
    subtitle_language: str = "",
    timestamp_context_seconds: int = 60,
    state_dir: Path | str | None = None,
) -> VideoLearningOutcome:
    """Fetch a video's metadata and transcript as learning markdown."""
    provider = detect_video_provider(url)
    if provider == "youtube":
        validator = host_validator or _is_disallowed_host
        factory = client_factory or _default_client_factory
        try:
            async with factory(timeout=timeout_s, user_agent=user_agent) as client:
                return await _learn_youtube(
                    client,
                    url,
                    max_chars=max_chars,
                    timeout_s=timeout_s,
                    user_agent=user_agent,
                    validator=validator,
                    client_factory=factory,
                    generate_transcript_if_missing=generate_transcript_if_missing,
                    subtitle_language=subtitle_language,
                    timestamp_context_seconds=timestamp_context_seconds,
                    state_dir=state_dir,
                )
        except httpx.HTTPError as exc:
            return VideoLearningOutcome(provider="youtube", url=url, error=f"Network error: {exc}")
        except (ValueError, KeyError, TypeError) as exc:
            return VideoLearningOutcome(provider="youtube", url=url, error=f"Invalid video data: {exc}")
        except Exception as exc:  # pragma: no cover - defensive provider boundary
            return VideoLearningOutcome(provider="youtube", url=url, error=f"Unexpected video failure: {exc}")
    if provider != "bilibili":
        return VideoLearningOutcome(provider="bilibili", error="Unsupported video URL.")

    validator = host_validator or _is_disallowed_host
    factory = client_factory or _default_client_factory
    try:
        async with factory(timeout=timeout_s, user_agent=user_agent) as client:
            return await _learn_bilibili(
                client,
                url,
                max_chars=max_chars,
                validator=validator,
                user_agent=user_agent,
                client_factory=factory,
                generate_transcript_if_missing=generate_transcript_if_missing,
                state_dir=state_dir,
            )
    except httpx.HTTPError as exc:
        return VideoLearningOutcome(provider="bilibili", url=url, error=f"Network error: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        return VideoLearningOutcome(provider="bilibili", url=url, error=f"Invalid video data: {exc}")
    except Exception as exc:  # pragma: no cover - defensive boundary for provider changes
        return VideoLearningOutcome(provider="bilibili", url=url, error=f"Unexpected video failure: {exc}")


@dataclass(frozen=True)
class _YouTubeRequest:
    video_id: str
    canonical_url: str
    entry_time_seconds: int = 0


async def _learn_youtube(
    client: Any,
    url: str,
    *,
    max_chars: int,
    timeout_s: float,
    user_agent: str,
    validator: Any,
    client_factory: Any,
    generate_transcript_if_missing: bool,
    subtitle_language: str,
    timestamp_context_seconds: int,
    state_dir: Path | str | None,
) -> VideoLearningOutcome:
    request = _parse_youtube_url(url)
    metadata: dict[str, Any] = {}
    transcript_segments: list[dict[str, Any]] = []
    transcript_language = ""
    transcript_source = ""
    errors: list[str] = []

    invidious_base = _invidious_base_url()
    if invidious_base:
        try:
            invidious_metadata = await _invidious_video_json(
                client,
                invidious_base,
                request.video_id,
            )
            metadata = _merge_youtube_metadata(metadata, invidious_metadata)
            if not transcript_segments:
                transcript_segments, transcript_language = await _invidious_transcript(
                    client,
                    invidious_base,
                    request.video_id,
                    metadata=invidious_metadata,
                    preferred_language=subtitle_language,
                )
                if transcript_segments:
                    transcript_source = "invidious"
        except Exception as exc:
            errors.append(f"invidious: {exc}")

    if not transcript_segments:
        try:
            transcript_segments, transcript_language = await _youtube_transcript_api(
                request.video_id, preferred_language=subtitle_language
            )
            if transcript_segments:
                transcript_source = "youtube-transcript-api"
        except Exception as exc:
            errors.append(f"youtube-transcript-api: {exc}")

    if not metadata:
        try:
            metadata = await _youtube_ytdlp_metadata(url, timeout_s=timeout_s)
        except Exception as exc:
            errors.append(f"yt-dlp: {exc}")

    if not transcript_segments:
        prepared = await _prepare_youtube_transcript(
            request,
            metadata=metadata,
            client=client,
            invidious_base=invidious_base,
            client_factory=client_factory,
            timeout_s=timeout_s,
            user_agent=user_agent,
            generate_transcript_if_missing=generate_transcript_if_missing,
            state_dir=state_dir,
        )
        if prepared is not None:
            return prepared

    if not transcript_segments:
        detail = "YouTube subtitles were unavailable."
        if not invidious_base:
            detail += " Configure INVIDIOUS_BASE_URL or install the video-learning extra."
        detail += " Set generate_transcript_if_missing=true to submit audio-only ASR."
        if errors:
            detail += f" Diagnostics: {'; '.join(errors[:2])}."
        return VideoLearningOutcome(
            provider="youtube",
            url=request.canonical_url,
            title=str(metadata.get("title") or ""),
            author=str(metadata.get("author") or metadata.get("uploader") or ""),
            duration_seconds=_metadata_duration(metadata),
            entry_time_seconds=request.entry_time_seconds,
            error=detail,
        )

    transcript_segments = _normalize_transcript_segments(transcript_segments)
    duration = _metadata_duration(metadata)
    context_start, context_end = _context_window(
        transcript_segments,
        entry_time_seconds=request.entry_time_seconds,
        radius_seconds=timestamp_context_seconds,
        duration_seconds=duration,
    )
    selected = transcript_segments
    if request.entry_time_seconds:
        selected = [
            row
            for row in transcript_segments
            if context_start <= row["start"] <= context_end
        ]
    transcript_text = _format_transcript_segments(selected)
    chapters = _normalize_chapters(metadata.get("chapters"))
    markdown = _format_youtube_markdown(
        title=str(metadata.get("title") or request.video_id),
        author=str(metadata.get("author") or metadata.get("uploader") or ""),
        url=request.canonical_url,
        duration_seconds=duration,
        language=transcript_language,
        source=transcript_source,
        entry_time_seconds=request.entry_time_seconds,
        chapters=chapters,
        transcript=transcript_text,
    )
    truncated = len(markdown) > max_chars
    if truncated:
        markdown = markdown[:max_chars].rstrip() + "\n…[truncated]"
    return VideoLearningOutcome(
        provider="youtube",
        ok=True,
        markdown=markdown,
        url=request.canonical_url,
        title=str(metadata.get("title") or request.video_id),
        author=str(metadata.get("author") or metadata.get("uploader") or ""),
        duration_seconds=duration,
        subtitle_language=transcript_language,
        transcript_source=transcript_source,
        entry_time_seconds=request.entry_time_seconds,
        context_start_seconds=context_start,
        context_end_seconds=context_end,
        chapters=chapters,
        transcript=transcript_segments,
        truncated=truncated,
    )


def _parse_youtube_url(url: str) -> _YouTubeRequest:
    parsed = urlparse((url or "").strip().strip("`\"'"))
    host = (parsed.hostname or "").lower().rstrip(".")
    query = parse_qs(parsed.query)
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = query.get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = parsed.path.split("/", 2)[2]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        raise ValueError("unsupported or invalid YouTube URL")
    raw_time = query.get("t", query.get("start", ["0"]))[0]
    entry_time = _parse_timestamp(raw_time)
    canonical_query = {"t": str(entry_time)} if entry_time else {}
    canonical = urlunparse(
        ("https", "youtu.be", f"/{video_id}", "", urlencode(canonical_query), "")
    )
    return _YouTubeRequest(video_id, canonical, entry_time)


def _parse_timestamp(value: str) -> int:
    raw = str(value or "").strip().lower()
    if raw.isdigit():
        return max(0, int(raw))
    matches = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw)
    if not matches or not any(matches.groups()):
        return 0
    hours, minutes, seconds = (int(part or 0) for part in matches.groups())
    return max(0, hours * 3600 + minutes * 60 + seconds)


async def _youtube_transcript_api(
    video_id: str,
    *,
    preferred_language: str,
) -> tuple[list[dict[str, Any]], str]:
    languages = [preferred_language] if preferred_language else ["zh-CN", "zh-Hans", "zh", "en"]

    def fetch() -> tuple[Any, str]:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            result = api.fetch(video_id, languages=languages)
            language = str(getattr(result, "language_code", "") or preferred_language)
            return list(result), language
        rows = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        return rows, preferred_language or ""

    rows, language = await asyncio.to_thread(fetch)
    return _normalize_transcript_segments(rows), language


async def _youtube_ytdlp_metadata(url: str, *, timeout_s: float) -> dict[str, Any]:
    def extract() -> dict[str, Any]:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "ignoreconfig": True,
            "cachedir": False,
            "socket_timeout": max(1, int(timeout_s)),
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
        return info if isinstance(info, dict) else {}

    return await asyncio.to_thread(extract)


def _invidious_base_url() -> str:
    from deeptutor.services.config.runtime_settings import load_integrations_settings

    return str(load_integrations_settings().get("invidious_base_url") or "").strip().rstrip("/")


async def _invidious_video_json(
    client: Any,
    base_url: str,
    video_id: str,
    *,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    suffix = f"?{urlencode(query)}" if query else ""
    payload = await _invidious_request(
        client,
        f"{base_url}/api/v1/videos/{video_id}{suffix}",
    )
    return payload if isinstance(payload, dict) else {}


async def _invidious_transcript(
    client: Any,
    base_url: str,
    video_id: str,
    *,
    metadata: dict[str, Any],
    preferred_language: str,
) -> tuple[list[dict[str, Any]], str]:
    captions = metadata.get("captions") or []
    if not isinstance(captions, list):
        captions = []
    selected = _select_youtube_caption(captions, preferred_language)
    if not selected:
        return [], ""
    language = str(selected.get("languageCode") or selected.get("language_code") or "")
    params = {"lang": language} if language else {}
    if selected.get("autoGenerated") or selected.get("auto_generated"):
        params["autogen"] = ""
    query = urlencode(params, doseq=True)
    transcript_url = f"{base_url}/api/v1/transcripts/{video_id}"
    if query:
        transcript_url += f"?{query}"
    try:
        payload = await _invidious_request(client, transcript_url)
        rows = payload.get("transcript", payload) if isinstance(payload, dict) else payload
        normalized = _normalize_transcript_segments(rows)
        if normalized:
            return normalized, language
    except Exception:
        pass
    captions_url = f"{base_url}/api/v1/captions/{video_id}?{query}" if query else f"{base_url}/api/v1/captions/{video_id}"
    response = await _invidious_raw_request(client, captions_url)
    text = response.decode("utf-8", errors="replace")
    return _parse_webvtt(text), language


async def _invidious_request(client: Any, url: str) -> Any:
    response = await _invidious_get(client, url)
    return response.json()


async def _invidious_raw_request(client: Any, url: str) -> bytes:
    response = await _invidious_get(client, url)
    content = getattr(response, "content", b"")
    if len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("Invidious captions exceeded the 2 MB safety cap")
    return content


async def _invidious_get(client: Any, url: str) -> Any:
    current = url
    origin = urlparse(url).netloc.lower()
    for _ in range(MAX_INVIDIOUS_REDIRECTS + 1):
        response = await client.get(current, follow_redirects=False)
        final_url = str(getattr(response, "url", "") or current)
        if urlparse(final_url).netloc.lower() != origin:
            raise ValueError("Invidious redirected outside the configured instance")
        if getattr(response, "is_redirect", False):
            location = response.headers.get("location")
            if hasattr(response, "aclose"):
                await response.aclose()
            if not location:
                raise ValueError("Invidious returned an invalid redirect")
            current = urljoin(current, location)
            if urlparse(current).netloc.lower() != origin:
                raise ValueError("Invidious redirected outside the configured instance")
            continue
        _ensure_http_success(response, "Fetch Invidious data")
        return response
    raise ValueError("Invidious returned too many redirects")


def _merge_youtube_metadata(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(fallback)
    result.update({key: value for key, value in primary.items() if value not in (None, "", [], {})})
    if "author" not in result and fallback.get("author"):
        result["author"] = fallback["author"]
    return result


def _select_youtube_caption(captions: list[Any], preferred_language: str) -> dict[str, Any] | None:
    rows = [row for row in captions if isinstance(row, dict)]
    priorities = [preferred_language] if preferred_language else ["zh-CN", "zh-Hans", "zh", "en"]
    for language in priorities:
        row = next(
            (item for item in rows if str(item.get("languageCode") or item.get("language_code") or "") == language),
            None,
        )
        if row:
            return row
    manual = next((row for row in rows if not row.get("autoGenerated") and not row.get("auto_generated")), None)
    return manual or (rows[0] if rows else None)


def _metadata_duration(metadata: dict[str, Any]) -> int:
    try:
        return int(float(metadata.get("duration") or metadata.get("lengthSeconds") or 0))
    except (TypeError, ValueError):
        return 0


def _context_window(
    segments: list[dict[str, Any]],
    *,
    entry_time_seconds: int,
    radius_seconds: int,
    duration_seconds: int,
) -> tuple[int, int]:
    if not entry_time_seconds:
        return 0, duration_seconds
    radius = min(300, max(15, int(radius_seconds or 60)))
    start = max(0, entry_time_seconds - radius)
    end = entry_time_seconds + radius
    if duration_seconds:
        end = min(duration_seconds, end)
    if segments:
        end = max(end, int(max(row["end"] for row in segments if row["start"] <= entry_time_seconds) if any(row["start"] <= entry_time_seconds for row in segments) else end))
    return start, end


def _normalize_chapters(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0, int(float(item.get("start_time") or item.get("startTime") or item.get("start") or 0)))
        except (TypeError, ValueError):
            continue
        rows.append({"start": start, "title": str(item.get("title") or "")})
    return rows


def _format_youtube_markdown(
    *,
    title: str,
    author: str,
    url: str,
    duration_seconds: int,
    language: str,
    source: str,
    entry_time_seconds: int,
    chapters: list[dict[str, Any]],
    transcript: str,
) -> str:
    metadata = [f"# {title}", "", f"- Source: {url}"]
    if author:
        metadata.append(f"- Channel: {author}")
    if duration_seconds:
        metadata.append(f"- Duration: {_format_duration(duration_seconds)}")
    if entry_time_seconds:
        metadata.append(
            f"- Current position: [{_format_timestamp(entry_time_seconds)}]({url})"
        )
    if language:
        metadata.append(f"- Subtitle language: {language}")
    if source:
        metadata.append(f"- Transcript source: {source}")
    if chapters:
        metadata.extend(["", "## Chapters", ""])
        metadata.extend(
            f"- [{_format_timestamp(row['start'])}]({url.split('?')[0]}?t={row['start']}) {row['title']}"
            for row in chapters
            if row["title"]
        )
    metadata.extend(["", "## Transcript", "", transcript])
    return "\n".join(metadata)


def _parse_webvtt(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?m)^(?P<start>\d{2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}(?::\d{2})?[.,]\d{3}).*\n(?P<body>.*?)(?=\n\s*\n|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        body = re.sub(r"<[^>]+>", "", match.group("body")).strip().replace("\n", " ")
        if body:
            rows.append({"start": _vtt_timestamp(match.group("start")), "end": _vtt_timestamp(match.group("end")), "text": body})
    return rows


def _vtt_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def _prepare_youtube_transcript(
    request: _YouTubeRequest,
    *,
    metadata: dict[str, Any],
    client: Any,
    invidious_base: str,
    client_factory: Any,
    timeout_s: float,
    user_agent: str,
    generate_transcript_if_missing: bool,
    state_dir: Path | str | None,
) -> VideoLearningOutcome | None:
    state = _load_video_state(request.canonical_url, state_dir)
    if state.get("status") == "succeeded" and state.get("segments"):
        return _generated_youtube_outcome(
            request,
            metadata=metadata,
            segments=state.get("segments"),
            job_id=str(state.get("job_id") or ""),
        )
    task_key = (_resolved_state_dir(state_dir), _state_key(request.canonical_url))
    active = _PREPARE_TASKS.get(task_key)
    if state.get("status") in {"queued", "running"} and active is not None and not active.done():
        return VideoLearningOutcome(
            provider="youtube",
            ok=True,
            url=request.canonical_url,
            title=str(metadata.get("title") or request.video_id),
            author=str(metadata.get("author") or metadata.get("uploader") or ""),
            duration_seconds=_metadata_duration(metadata),
            entry_time_seconds=request.entry_time_seconds,
            preprocessing=True,
            preprocessing_status=str(state.get("status")),
            job_id=str(state.get("job_id") or ""),
        )
    if not generate_transcript_if_missing:
        return None
    job_id = str(state.get("job_id") or uuid4().hex)
    _save_video_state(
        request.canonical_url,
        state_dir,
        job_id=job_id,
        status="queued",
        progress=0,
        message="YouTube audio transcript queued",
    )
    task = asyncio.create_task(
        _run_youtube_transcript_preparation(
            request,
            metadata=metadata,
            invidious_base=invidious_base,
            client_factory=client_factory,
            timeout_s=timeout_s,
            user_agent=user_agent,
            state_dir=state_dir,
        )
    )
    _PREPARE_TASKS[task_key] = task
    return VideoLearningOutcome(
        provider="youtube",
        ok=True,
        url=request.canonical_url,
        title=str(metadata.get("title") or request.video_id),
        author=str(metadata.get("author") or metadata.get("uploader") or ""),
        duration_seconds=_metadata_duration(metadata),
        entry_time_seconds=request.entry_time_seconds,
        preprocessing=True,
        preprocessing_status="queued",
        job_id=job_id,
    )


async def _run_youtube_transcript_preparation(
    request: _YouTubeRequest,
    *,
    metadata: dict[str, Any],
    invidious_base: str,
    client_factory: Any,
    timeout_s: float,
    user_agent: str,
    state_dir: Path | str | None,
) -> None:
    task_key = (_resolved_state_dir(state_dir), _state_key(request.canonical_url))
    state = _load_video_state(request.canonical_url, state_dir)
    job_id = str(state.get("job_id") or uuid4().hex)
    try:
        _save_video_state(
            request.canonical_url,
            state_dir,
            job_id=job_id,
            status="running",
            progress=10,
            message="Resolving YouTube audio-only stream",
        )
        resolved_metadata = dict(metadata)
        async with client_factory(timeout=timeout_s, user_agent=user_agent) as client:
            try:
                resolved_metadata = _merge_youtube_metadata(
                    resolved_metadata,
                    await _youtube_ytdlp_metadata(request.canonical_url, timeout_s=timeout_s),
                )
            except Exception:
                pass
            if invidious_base and not resolved_metadata.get("adaptiveFormats"):
                try:
                    resolved_metadata = _merge_youtube_metadata(
                        resolved_metadata,
                        await _invidious_video_json(
                            client,
                            invidious_base,
                            request.video_id,
                            query={"local": "true"},
                        ),
                    )
                except Exception:
                    pass
            audio_url = _select_youtube_audio_url(resolved_metadata, invidious_base)
            _save_video_state(
                request.canonical_url,
                state_dir,
                job_id=job_id,
                status="running",
                progress=35,
                message="Reading audio-only stream without saving media",
            )
            audio, content_type = await _read_youtube_audio(client, audio_url)
            _save_video_state(
                request.canonical_url,
                state_dir,
                job_id=job_id,
                status="running",
                progress=60,
                message="Transcribing temporary audio",
                audio_bytes=len(audio),
            )
            segments = await _transcribe_audio_segments(
                audio,
                duration_seconds=_metadata_duration(resolved_metadata),
                content_type=content_type,
            )
        if not segments:
            raise ValueError("speech-to-text provider returned no transcript")
        document = _transcript_document(
            request.canonical_url,
            duration_seconds=_metadata_duration(resolved_metadata),
            video_id=request.video_id,
            video_id_kind="youtube",
            cid=0,
            page=1,
            segments=segments,
            provider="youtube",
        )
        _save_video_state(
            request.canonical_url,
            state_dir,
            job_id=job_id,
            status="succeeded",
            progress=100,
            message="YouTube audio transcript ready",
            segments=document["segments"],
            transcript=document,
            transcript_source="stt",
            finished_at=_now(),
        )
    except asyncio.CancelledError:
        _save_video_state(
            request.canonical_url,
            state_dir,
            job_id=job_id,
            status="cancelled",
            message="YouTube transcript preprocessing cancelled",
            finished_at=_now(),
        )
        raise
    except Exception as exc:
        _save_video_state(
            request.canonical_url,
            state_dir,
            job_id=job_id,
            status="failed",
            message="YouTube transcript preprocessing failed",
            error=str(exc),
            finished_at=_now(),
        )
    finally:
        _PREPARE_TASKS.pop(task_key, None)


def _select_youtube_audio_url(metadata: dict[str, Any], invidious_base: str) -> str:
    formats = metadata.get("formats") or metadata.get("adaptiveFormats") or []
    if not isinstance(formats, list):
        raise ValueError("YouTube returned no audio-only stream")
    candidates: list[tuple[float, str, str]] = []
    for item in formats:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("baseUrl") or item.get("base_url") or "")
        if not url:
            continue
        vcodec = str(item.get("vcodec") or "none")
        acodec = str(item.get("acodec") or item.get("mimeType") or "")
        if vcodec != "none" and "video/" in acodec:
            continue
        if vcodec != "none" and item.get("height"):
            continue
        try:
            bitrate = float(item.get("abr") or item.get("audioBitrate") or item.get("bitrate") or 0)
        except (TypeError, ValueError):
            bitrate = 0
        content_type = str(item.get("mimeType") or "audio/mpeg").split(";", 1)[0]
        candidates.append((bitrate, url, content_type))
    if not candidates:
        raise ValueError("YouTube returned no audio-only stream")
    _, raw_url, content_type = min(candidates, key=lambda row: row[0])
    url = f"https:{raw_url}" if raw_url.startswith("//") else raw_url
    parsed = urlparse(url)
    configured_host = (urlparse(invidious_base).netloc or "").lower()
    host = (parsed.hostname or "").lower()
    allowed = host == configured_host or host.endswith(".googlevideo.com") or host.endswith(".googleusercontent.com")
    if parsed.scheme != "https" or not allowed:
        raise ValueError("YouTube returned an unsafe audio URL")
    return url


async def _read_youtube_audio(client: Any, url: str) -> tuple[bytes, str]:
    current = url
    allowed_origin = (urlparse(url).hostname or "").lower()
    for _ in range(MAX_INVIDIOUS_REDIRECTS + 1):
        parsed = urlparse(current)
        if not _is_allowed_youtube_media_host(parsed.hostname or "", allowed_origin):
            raise ValueError("YouTube audio URL is outside its allowed domains")
        async with client.stream("GET", current, follow_redirects=False) as response:
            if getattr(response, "is_redirect", False):
                location = response.headers.get("location")
                if not location:
                    raise ValueError("YouTube returned an invalid audio redirect")
                current = urljoin(current, location)
                continue
            _ensure_http_success(response, "Fetch YouTube audio")
            final_host = (urlparse(str(getattr(response, "url", "") or current)).hostname or "").lower()
            if not _is_allowed_youtube_media_host(final_host, allowed_origin):
                raise ValueError("YouTube redirected audio outside its allowed domains")
            content_length = str(response.headers.get("content-length") or "")
            if content_length.isdigit() and int(content_length) > MAX_AUDIO_BYTES:
                raise ValueError("YouTube audio exceeds the 32 MB no-download preprocessing cap")
            content_type = str(response.headers.get("content-type") or "audio/mp4").split(";", 1)[0]
            if not content_type.startswith("audio/"):
                raise ValueError("YouTube returned a non-audio stream for ASR")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_AUDIO_BYTES:
                    raise ValueError("YouTube audio exceeds the 32 MB no-download preprocessing cap")
                chunks.append(chunk)
            audio = b"".join(chunks)
            if not audio:
                raise ValueError("YouTube returned empty audio")
            return audio, content_type
    raise ValueError("YouTube returned too many audio redirects")


def _is_allowed_youtube_media_host(host: str, configured_host: str) -> bool:
    lowered = host.lower().rstrip(".")
    return lowered == configured_host or lowered.endswith(".googlevideo.com") or lowered.endswith(".googleusercontent.com")


def _generated_youtube_outcome(
    request: _YouTubeRequest,
    *,
    metadata: dict[str, Any],
    segments: Any,
    job_id: str,
) -> VideoLearningOutcome:
    normalized = _normalize_transcript_segments(segments)
    markdown = _format_youtube_markdown(
        title=str(metadata.get("title") or request.video_id),
        author=str(metadata.get("author") or metadata.get("uploader") or ""),
        url=request.canonical_url,
        duration_seconds=_metadata_duration(metadata),
        language="auto",
        source="stt",
        entry_time_seconds=request.entry_time_seconds,
        chapters=_normalize_chapters(metadata.get("chapters")),
        transcript=_format_transcript_segments(normalized),
    )
    return VideoLearningOutcome(
        provider="youtube",
        ok=True,
        markdown=markdown,
        url=request.canonical_url,
        title=str(metadata.get("title") or request.video_id),
        author=str(metadata.get("author") or metadata.get("uploader") or ""),
        duration_seconds=_metadata_duration(metadata),
        subtitle_language="auto",
        transcript_source="stt",
        entry_time_seconds=request.entry_time_seconds,
        job_id=job_id,
        transcript=normalized,
    )


async def _learn_bilibili(
    client: Any,
    url: str,
    *,
    max_chars: int,
    validator: Any,
    user_agent: str,
    client_factory: Any,
    generate_transcript_if_missing: bool,
    state_dir: Path | str | None,
) -> VideoLearningOutcome:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.bilibili.com/",
    }
    canonical_url, video_id = await _canonical_bilibili_url(client, url, headers, validator)
    metadata = await _bilibili_json(
        client,
        f"https://api.bilibili.com/x/web-interface/view?{video_id.kind}={video_id.value}",
        headers,
        validator,
    )
    data = _dict(metadata.get("data"))
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("video has no title")

    cid, page_label, page_duration = _select_bilibili_page(canonical_url, data)
    player = await _bilibili_json(
        client,
        "https://api.bilibili.com/x/player/v2?"
        f"{video_id.kind}={video_id.value}&cid={cid}",
        headers,
        validator,
    )
    player_data = _dict(player.get("data"))
    subtitle = _select_bilibili_subtitle(_dict(player_data.get("subtitle")).get("subtitles"))
    if subtitle is None:
        prepared = await _prepared_bilibili_transcript(
            canonical_url,
            metadata=data,
            page_label=page_label,
            page_duration=page_duration,
            max_chars=max_chars,
            client_factory=client_factory,
            host_validator=validator,
            generate_transcript_if_missing=generate_transcript_if_missing,
            state_dir=state_dir,
        )
        if prepared is not None:
            return prepared
        state = _load_video_state(canonical_url, state_dir)
        error = (
            "Bilibili exposed no subtitle for this video. Learning requires an "
            "uploader-provided or AI subtitle that is visible without credentials."
            " Submit it again with generate_transcript_if_missing=true to preprocess audio."
        )
        if state.get("status") == "failed":
            error += f" Previous preprocessing failed: {state.get('error') or 'unknown error'}."
        return VideoLearningOutcome(
            provider="bilibili",
            url=canonical_url,
            title=title,
            author=str(_dict(data.get("owner")).get("name") or ""),
            duration_seconds=page_duration or int(data.get("duration") or 0),
            job_id=str(state.get("job_id") or ""),
            error=error,
        )

    subtitle_url = _safe_bilibili_url(str(subtitle.get("subtitle_url") or ""), validator)
    subtitle_payload = await _bilibili_json(client, subtitle_url, headers, validator)
    transcript_segments = _normalize_transcript_segments(subtitle_payload.get("body"))
    transcript = _format_transcript_segments(transcript_segments)
    if not transcript:
        return VideoLearningOutcome(
            provider="bilibili",
            url=canonical_url,
            title=title,
            error="Bilibili returned an empty subtitle.",
        )

    author = str(_dict(data.get("owner")).get("name") or "")
    duration = page_duration or int(data.get("duration") or 0)
    language = str(subtitle.get("lan") or subtitle.get("lan_doc") or "")
    markdown = _format_video_markdown(
        title=title,
        author=author,
        url=canonical_url,
        duration_seconds=duration,
        page_label=page_label,
        language=language,
        description=str(data.get("desc") or "").strip(),
        transcript=transcript,
    )
    truncated = False
    if len(markdown) > max_chars:
        markdown = markdown[:max_chars].rstrip() + "\n…[truncated]"
        truncated = True
    return VideoLearningOutcome(
        provider="bilibili",
        ok=True,
        markdown=markdown,
        url=canonical_url,
        title=title,
        author=author,
        duration_seconds=duration,
        subtitle_language=language,
        transcript=transcript_segments,
        truncated=truncated,
    )


async def _prepared_bilibili_transcript(
    canonical_url: str,
    *,
    metadata: dict[str, Any],
    page_label: str,
    page_duration: int,
    max_chars: int,
    client_factory: Any,
    host_validator: Any,
    generate_transcript_if_missing: bool,
    state_dir: Path | str | None,
) -> VideoLearningOutcome | None:
    state = _load_video_state(canonical_url, state_dir)
    if state.get("status") == "succeeded" and state.get("segments"):
        return _generated_video_outcome(
            canonical_url,
            metadata=metadata,
            page_label=page_label,
            page_duration=page_duration,
            segments=state.get("segments"),
            max_chars=max_chars,
            job_id=str(state.get("job_id") or ""),
        )

    task_key = (_resolved_state_dir(state_dir), _state_key(canonical_url))
    active = _PREPARE_TASKS.get(task_key)
    if state.get("status") in {"queued", "running"} and active is not None and not active.done():
        return VideoLearningOutcome(
            provider="bilibili",
            ok=True,
            url=canonical_url,
            title=str(metadata.get("title") or ""),
            author=str(_dict(metadata.get("owner")).get("name") or ""),
            duration_seconds=page_duration or int(metadata.get("duration") or 0),
            subtitle_language="auto",
            preprocessing=True,
            preprocessing_status="running" if state.get("status") == "running" else "queued",
            job_id=str(state.get("job_id") or ""),
        )

    if not generate_transcript_if_missing:
        return None
    if state.get("status") in {"queued", "running"}:
        state = _save_video_state(
            canonical_url,
            state_dir,
            status="interrupted",
            error="Preprocessing was interrupted by a server restart.",
            finished_at=_now(),
        )

    job_id = f"video-transcript-{uuid4().hex[:16]}"
    state = _save_video_state(
        canonical_url,
        state_dir,
        job_id=job_id,
        status="queued",
        provider="bilibili",
        title=str(metadata.get("title") or ""),
        page_label=page_label,
        created_at=_now(),
        started_at="",
        finished_at="",
        error=None,
    )
    _PREPARE_TASKS[task_key] = asyncio.create_task(
        _run_transcript_preparation(
            canonical_url,
            job_id=job_id,
            client_factory=client_factory,
            host_validator=host_validator,
            state_dir=state_dir,
        )
    )
    return VideoLearningOutcome(
        provider="bilibili",
        ok=True,
        url=canonical_url,
        title=str(metadata.get("title") or ""),
        author=str(_dict(metadata.get("owner")).get("name") or ""),
        duration_seconds=page_duration or int(metadata.get("duration") or 0),
        subtitle_language="auto",
        preprocessing=True,
        preprocessing_status="queued",
        job_id=job_id,
    )


async def _run_transcript_preparation(
    canonical_url: str,
    *,
    job_id: str,
    client_factory: Any,
    host_validator: Any,
    state_dir: Path | str | None,
) -> None:
    task_key = (_resolved_state_dir(state_dir), _state_key(canonical_url))
    try:
        _save_video_state(
            canonical_url,
            state_dir,
            job_id=job_id,
            status="running",
            started_at=_now(),
            progress=2,
            message="Resolving Bilibili audio track",
        )
        parsed = urlparse(canonical_url)
        video_id = _bilibili_video_id(parsed.path)
        if video_id is None:
            raise ValueError("canonical Bilibili URL has no video id")
        query = parse_qs(parsed.query)
        page = int(query.get("p", ["1"])[0])
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.bilibili.com/",
        }
        async with client_factory(timeout=DEFAULT_TIMEOUT_S, user_agent=DEFAULT_USER_AGENT) as client:
            metadata = await _bilibili_json(
                client,
                f"https://api.bilibili.com/x/web-interface/view?{video_id.kind}={video_id.value}",
                headers,
                host_validator,
            )
            data = _dict(metadata.get("data"))
            cid, _page_label, duration = _select_bilibili_page(canonical_url, data)
            _save_video_state(
                canonical_url,
                state_dir,
                job_id=job_id,
                status="running",
                progress=20,
                message="Fetching audio-only stream",
                duration_seconds=duration,
                video_id=video_id.value,
                video_id_kind=video_id.kind,
                cid=cid,
                page=page,
            )
            play = await _bilibili_json(
                client,
                "https://api.bilibili.com/x/player/playurl?"
                f"{video_id.kind}={video_id.value}&cid={cid}&fnval=16",
                headers,
                host_validator,
            )
            audio_url = _select_bilibili_audio_url(_dict(play.get("data")).get("dash"), host_validator)
            audio, content_type = await _read_bilibili_audio(
                client,
                audio_url,
                headers,
                validator=host_validator,
            )
            _save_video_state(
                canonical_url,
                state_dir,
                job_id=job_id,
                status="running",
                progress=55,
                message="Transcribing audio without saving media",
                audio_bytes=len(audio),
            )
            segments = await _transcribe_audio_segments(
                audio,
                duration_seconds=duration,
                content_type=content_type,
            )
            if not segments:
                raise ValueError("speech-to-text provider returned no transcript")
            transcript_document = _transcript_document(
                canonical_url,
                duration_seconds=duration,
                video_id=video_id.value,
                video_id_kind=video_id.kind,
                cid=cid,
                page=page,
                segments=segments,
            )
            _save_video_state(
                canonical_url,
                state_dir,
                job_id=job_id,
                status="succeeded",
                progress=100,
                message="Audio transcript ready",
                segments=transcript_document["segments"],
                transcript=transcript_document,
                transcript_source="stt",
                finished_at=_now(),
            )
    except asyncio.CancelledError:
        _save_video_state(
            canonical_url,
            state_dir,
            job_id=job_id,
            status="cancelled",
            message="Transcript preprocessing cancelled",
            finished_at=_now(),
        )
        raise
    except Exception as exc:
        _save_video_state(
            canonical_url,
            state_dir,
            job_id=job_id,
            status="failed",
            message="Transcript preprocessing failed",
            error=str(exc),
            finished_at=_now(),
        )
    finally:
        _PREPARE_TASKS.pop(task_key, None)


async def _canonical_bilibili_url(
    client: Any,
    url: str,
    headers: dict[str, str],
    validator: Any,
) -> tuple[str, "_VideoId"]:
    parsed = urlparse(url)
    video_id = _bilibili_video_id(parsed.path)
    host = (parsed.hostname or "").lower().rstrip(".")
    if video_id is not None and host.endswith(".bilibili.com"):
        return _normalize_bilibili_url(url, video_id), video_id

    response = await client.get(url, headers=headers, follow_redirects=True)
    _ensure_http_success(response, "Resolve Bilibili short URL")
    final_url = str(response.url)
    final_parsed = urlparse(final_url)
    final_host = (final_parsed.hostname or "").lower().rstrip(".")
    final_id = _bilibili_video_id(final_parsed.path)
    if not final_host.endswith(".bilibili.com") or final_id is None:
        raise ValueError("short URL did not resolve to a Bilibili video page")
    if validator(final_host):
        raise ValueError("Bilibili redirected to a blocked host")
    return _normalize_bilibili_url(final_url, final_id), final_id


@dataclass(frozen=True)
class _VideoId:
    kind: str
    value: str


def _bilibili_video_id(path: str) -> _VideoId | None:
    bvid = _BVID_RE.search(path)
    if bvid:
        return _VideoId("bvid", bvid.group(1))
    avid = _AVID_RE.search(path)
    if avid:
        return _VideoId("aid", avid.group(1).removeprefix("av"))
    return None


def _normalize_bilibili_url(url: str, video_id: _VideoId) -> str:
    parsed = urlparse(url)
    page = parse_qs(parsed.query).get("p", ["1"])[0]
    suffix = f"?p={page}" if page != "1" else ""
    prefix = "av" if video_id.kind == "aid" else ""
    return f"https://www.bilibili.com/video/{prefix}{video_id.value}{suffix}"


def _select_bilibili_page(url: str, data: dict[str, Any]) -> tuple[int, str, int]:
    page_number = int(parse_qs(urlparse(url).query).get("p", ["1"])[0])
    pages = data.get("pages") or []
    if not isinstance(pages, list) or not pages:
        cid = int(data.get("cid") or 0)
        if cid <= 0:
            raise ValueError("video metadata has no cid")
        return cid, "P1", int(data.get("duration") or 0)
    if page_number < 1 or page_number > len(pages):
        raise ValueError(f"video has no page P{page_number}")
    page = _dict(pages[page_number - 1])
    cid = int(page.get("cid") or 0)
    if cid <= 0:
        raise ValueError(f"video page P{page_number} has no cid")
    duration = int(page.get("duration") or data.get("duration") or 0)
    return cid, str(page.get("part") or f"P{page_number}"), duration


def _resolved_state_dir(state_dir: Path | str | None) -> Path:
    if state_dir is not None:
        return Path(state_dir)
    from deeptutor.services.path_service import get_path_service

    return get_path_service().user_data_dir / "video_learning"


def _state_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _state_path(url: str, state_dir: Path | str | None) -> Path:
    return _resolved_state_dir(state_dir) / f"{_state_key(url)}.json"


def _load_video_state(url: str, state_dir: Path | str | None) -> dict[str, Any]:
    try:
        payload = json.loads(_state_path(url, state_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_video_state(url: str, state_dir: Path | str | None, **fields: Any) -> dict[str, Any]:
    state = _load_video_state(url, state_dir)
    state.update(fields)
    state["url"] = url
    state["updated_at"] = _now()
    atomic_write_json(_state_path(url, state_dir), state)
    return state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generated_video_outcome(
    canonical_url: str,
    *,
    metadata: dict[str, Any],
    page_label: str,
    page_duration: int,
    segments: Any,
    max_chars: int,
    job_id: str,
) -> VideoLearningOutcome:
    transcript_segments = _normalize_transcript_segments(segments)
    transcript = _format_transcript_segments(transcript_segments)
    author = str(_dict(metadata.get("owner")).get("name") or "")
    duration = page_duration or int(metadata.get("duration") or 0)
    markdown = _format_video_markdown(
        title=str(metadata.get("title") or ""),
        author=author,
        url=canonical_url,
        duration_seconds=duration,
        page_label=page_label,
        language="auto",
        description=str(metadata.get("desc") or "").strip(),
        transcript=transcript,
    )
    truncated = len(markdown) > max_chars
    if truncated:
        markdown = markdown[:max_chars].rstrip() + "\n…[truncated]"
    return VideoLearningOutcome(
        provider="bilibili",
        ok=True,
        markdown=markdown,
        url=canonical_url,
        title=str(metadata.get("title") or ""),
        author=author,
        duration_seconds=duration,
        subtitle_language="auto",
        transcript=transcript_segments,
        job_id=job_id,
        truncated=truncated,
    )


def _select_bilibili_audio_url(dash: Any, validator: Any) -> str:
    audios = _dict(dash).get("audio")
    if not isinstance(audios, list) or not audios:
        raise ValueError("Bilibili returned no audio-only stream")
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in audios:
        entry = _dict(item)
        url = str(entry.get("baseUrl") or entry.get("base_url") or "").strip()
        if url:
            candidates.append((int(entry.get("bandwidth") or 0), entry | {"_url": url}))
    if not candidates:
        raise ValueError("Bilibili audio stream has no URL")
    raw = min(candidates, key=lambda item: item[0])[1]["_url"]
    url = f"https:{raw}" if raw.startswith("//") else raw
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not _is_bilibili_audio_host(host) or validator(host):
        raise ValueError("Bilibili returned an unsafe audio URL")
    return url


async def _read_bilibili_audio(
    client: Any,
    url: str,
    headers: dict[str, str],
    *,
    validator: Any,
) -> tuple[bytes, str]:
    chunks: list[bytes] = []
    total = 0
    async with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
        _ensure_http_success(response, "Fetch Bilibili audio")
        final_host = (
            urlparse(str(getattr(response, "url", "") or url)).hostname or ""
        ).lower().rstrip(".")
        if not _is_bilibili_audio_host(final_host) or validator(final_host):
            raise ValueError("Bilibili redirected audio outside its allowed CDN domains")
        content_length = str(response.headers.get("content-length") or "")
        if content_length.isdigit() and int(content_length) > MAX_AUDIO_BYTES:
            raise ValueError("Bilibili audio exceeds the 32 MB no-download preprocessing cap")
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                raise ValueError("Bilibili audio exceeds the 32 MB no-download preprocessing cap")
            chunks.append(chunk)
        content_type = str(response.headers.get("content-type") or "audio/mpeg").split(";")[0]

    audio = b"".join(chunks)
    if not audio:
        raise ValueError("Bilibili returned empty audio")
    return audio, content_type


async def _transcribe_audio_segments(
    audio: bytes,
    *,
    duration_seconds: int,
    content_type: str,
) -> list[dict[str, Any]]:
    from deeptutor.services.voice import transcribe_audio_segments

    filename = "audio.m4a" if "mp4" in content_type else "audio.webm"
    raw_segments = await transcribe_audio_segments(
        audio,
        filename=filename,
        content_type=content_type,
    )
    segments: list[dict[str, Any]] = []
    for raw in raw_segments:
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        try:
            start = max(0.0, float(raw.get("start") or 0))
            end = max(start, float(raw.get("end") or 0))
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        duration = end - start if end > start else max(0, duration_seconds)
        segments.append({"from": start, "duration": duration, "content": text})
    return segments


def _is_bilibili_audio_host(host: str) -> bool:
    return (
        host == "bilivideo.com"
        or host.endswith(".bilivideo.com")
        or host == "bilivideo.net"
        or host.endswith(".bilivideo.net")
    )


def _normalize_transcript_segments(segments: Any) -> list[dict[str, Any]]:
    if not isinstance(segments, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in segments:
        if isinstance(item, dict):
            entry = item
        else:
            entry = {
                "start": getattr(item, "start", 0),
                "duration": getattr(item, "duration", 0),
                "text": getattr(item, "text", ""),
            }
        snippet = entry.get("snippet")
        if isinstance(snippet, dict):
            entry = entry | snippet
        content = str(entry.get("content") or entry.get("text") or "").strip()
        if not content:
            continue
        try:
            start = max(
                0.0,
                float(
                    entry.get("from")
                    or entry.get("start")
                    or entry.get("startMs", 0) / 1000
                ),
            )
            end = float(
                entry.get("to")
                or entry.get("end")
                or entry.get("endMs", 0) / 1000
            )
            if end <= start:
                end = start + float(
                    entry.get("duration")
                    or entry.get("durationMs", 0) / 1000
                    or 0
                )
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        normalized.append({"start": start, "end": end, "text": content})
    for locator, segment in enumerate(normalized, start=1):
        segment["locator"] = locator
    return normalized


def _transcript_document(
    url: str,
    *,
    duration_seconds: int,
    video_id: str,
    video_id_kind: str,
    cid: int,
    page: int,
    segments: list[dict[str, Any]],
    provider: str = "bilibili",
) -> dict[str, Any]:
    return {
        "version": 1,
        "source": {
            "provider": provider,
            "url": url,
            "video_id": video_id,
            "video_id_kind": video_id_kind,
            "cid": cid,
            "page": page,
            "duration_seconds": duration_seconds,
        },
        "segments": _normalize_transcript_segments(segments),
    }


def _format_transcript_segments(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for entry in segments:
        start = max(0, int(float(entry.get("start") or 0)))
        hours, remainder = divmod(start, 3600)
        minutes, seconds = divmod(remainder, 60)
        stamp = f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        lines.append(f"[{stamp}] {entry.get('text', '')}")
    return "\n".join(lines)


def _format_timestamp(seconds: int | float) -> str:
    total = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, sec = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


def _select_bilibili_subtitle(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    subtitles = [item for item in value if isinstance(item, dict) and item.get("subtitle_url")]
    if not subtitles:
        return None
    for language in _SUBTITLE_LANGUAGE_PRIORITY:
        selected = next(
            (item for item in subtitles if str(item.get("lan") or "") == language),
            None,
        )
        if selected is not None:
            return selected
    return subtitles[0]


async def _bilibili_json(
    client: Any,
    url: str,
    headers: dict[str, str],
    validator: Any,
) -> dict[str, Any]:
    safe_url = _safe_bilibili_url(url, validator)
    async with client.stream(
        "GET", safe_url, headers=headers, follow_redirects=True
    ) as response:
        _ensure_http_success(response, "Fetch Bilibili video data")
        _safe_bilibili_url(str(getattr(response, "url", "") or safe_url), validator)
        body = await _read_bounded_response(response)
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Bilibili returned invalid JSON") from exc
    result = _dict(payload)
    if url.startswith("https://api.bilibili.com/") and int(result.get("code") or 0) != 0:
        message = str(result.get("message") or result.get("msg") or "unknown API error")
        raise ValueError(f"Bilibili API error: {message}")
    return result


def _ensure_http_success(response: Any, action: str) -> None:
    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 400:
        raise ValueError(f"{action} failed with HTTP {status}")


async def _read_bounded_response(response: Any) -> bytes:
    headers = getattr(response, "headers", {})
    content_length = str(headers.get("content-length") or "")
    if content_length.isdigit() and int(content_length) > MAX_RESPONSE_BYTES:
        raise ValueError("Bilibili response exceeded the 2 MB safety cap")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError("Bilibili response exceeded the 2 MB safety cap")
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_bilibili_url(raw_url: str, validator: Any) -> str:
    url = raw_url.strip()
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (
        host == "bilibili.com"
        or host.endswith(".bilibili.com")
        or host == "hdslb.com"
        or host.endswith(".hdslb.com")
    ):
        raise ValueError("Bilibili returned a subtitle URL outside its allowed domains")
    if validator(host):
        raise ValueError("Bilibili returned a subtitle URL on a blocked host")
    return url


def _format_video_markdown(
    *,
    title: str,
    author: str,
    url: str,
    duration_seconds: int,
    page_label: str,
    language: str,
    description: str,
    transcript: str,
) -> str:
    metadata = [f"# {title}", "", f"- Source: {url}"]
    if author:
        metadata.append(f"- Uploader: {author}")
    if duration_seconds:
        metadata.append(f"- Duration: {_format_duration(duration_seconds)}")
    if page_label:
        metadata.append(f"- Page: {page_label}")
    if language:
        metadata.append(f"- Subtitle language: {language}")
    parts = ["\n".join(metadata)]
    if description:
        parts.extend(["", "## Description", "", description])
    parts.extend(["", "## Transcript", "", transcript])
    return "\n".join(parts)


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, sec = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _default_client_factory(*, timeout: float, user_agent: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
    )


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_USER_AGENT",
    "VideoLearningOutcome",
    "detect_video_provider",
    "learn_video",
]
