"""Unified URL and media ingestion for Immersive Reading.

Imports always create a durable catalog row first, then move through processing
to ready/failed. API callers can therefore return immediately and poll REST;
the same service is also directly awaitable in tests and CLI integrations.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
import hashlib
import logging
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from deeptutor.reading.catalog_models import (
    IngestionStatus,
    MaterialRecord,
    SourceKind,
)
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.extract import split_markdown_by_headings
from deeptutor.reading.models import OutlineEntry, ReadingError, UnitReference
from deeptutor.reading.store import ReadingStore, content_hash
from deeptutor.services.web_source.markdown import strip_leading_snapshot_provenance
from deeptutor.services.web_source.snapshot_assets import (
    ImageFetcher,
    localize_snapshot_images,
)
from deeptutor.tools.web_fetch import FetchOutcome, fetch_url_as_markdown

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_BILIBILI_HOSTS = {
    "bilibili.com",
    "www.bilibili.com",
    "m.bilibili.com",
    "player.bilibili.com",
    "b23.tv",
}
_BILIBILI_ID = re.compile(r"^BV[0-9A-Za-z]{10}$", re.IGNORECASE)
_AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".webm"}
MAX_TRANSCRIPT_CUES = 20_000
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024
MIN_SEGMENT_SECONDS = 20
MAX_SEGMENT_SECONDS = 90
TRANSCRIPT_UNAVAILABLE_TEXT = "[Transcript unavailable for this video.]"


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class YouTubeRequest:
    video_id: str
    canonical_url: str
    entry_time_seconds: int = 0


@dataclass(frozen=True, slots=True)
class BilibiliRequest:
    bvid: str
    canonical_url: str
    page_number: int = 1
    entry_time_seconds: int = 0


@dataclass(frozen=True, slots=True)
class BilibiliMedia:
    title: str
    cover_url: str
    duration_seconds: float
    page_number: int
    cid: int
    segments: list[TranscriptSegment]
    chapters: list[TranscriptSegment]


WebFetcher = Callable[..., Awaitable[FetchOutcome]]
YouTubeLoader = Callable[
    [str, Sequence[str]],
    Awaitable[tuple[str, str, list[TranscriptSegment]]],
]
BilibiliLoader = Callable[
    [str, Sequence[str]],
    Awaitable[BilibiliMedia],
]
MediaChunker = Callable[[Path], Awaitable[list[tuple[float, float, bytes]]]]
Transcriber = Callable[..., Awaitable[str]]


def url_material_id(url: str) -> str:
    """The content id a URL import lands on.

    Duplicate detection has to answer "do I already have this link?" before the
    fetch, so the derivation lives here rather than inside the queueing path
    that used it.
    """
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


class ReadingIngestionService:
    def __init__(
        self,
        reading_store: ReadingStore | None = None,
        catalog: ReadingCatalogStore | None = None,
        *,
        web_fetcher: WebFetcher = fetch_url_as_markdown,
        youtube_loader: YouTubeLoader | None = None,
        bilibili_loader: BilibiliLoader | None = None,
        media_chunker: MediaChunker | None = None,
        transcriber: Transcriber | None = None,
        image_fetcher: ImageFetcher | None = None,
    ) -> None:
        self.catalog = catalog or ReadingCatalogStore()
        self.reading_store = reading_store or ReadingStore(self.catalog.root)
        self._web_fetcher = web_fetcher
        self._youtube_loader = youtube_loader or _load_youtube_captions
        self._bilibili_loader = bilibili_loader or _load_bilibili_media
        self._media_chunker = media_chunker or _chunk_media_audio
        self._image_fetcher = image_fetcher
        if transcriber is None:
            from deeptutor.services.voice import transcribe_audio

            transcriber = transcribe_audio
        self._transcriber = transcriber

    def queue_url(self, url: str, *, title: str = "") -> MaterialRecord:
        normalized = normalize_url(url)
        if youtube_video_id(normalized):
            source_kind = SourceKind.YOUTUBE
        elif bilibili_video_id(normalized):
            source_kind = SourceKind.BILIBILI
        else:
            source_kind = SourceKind.WEB
        material_id = url_material_id(normalized)
        fallback_title = title.strip() or (urlparse(normalized).hostname or "Web source")
        return self.catalog.upsert_material(
            content_id=material_id,
            material_id=material_id,
            filename=f"{material_id}.url",
            title=fallback_title,
            source_kind=source_kind,
            source_url=normalized,
            mime="text/html" if source_kind is SourceKind.WEB else "text/vtt",
            render_mode=(
                "video" if source_kind in {SourceKind.YOUTUBE, SourceKind.BILIBILI} else "text"
            ),
            status=IngestionStatus.QUEUED,
        )

    async def process_url(
        self, material_id: str, *, preferred_languages: Sequence[str] = ("zh-CN", "zh", "en")
    ) -> MaterialRecord:
        record = self.catalog.get_material(material_id)
        if record is None or not record.source_url:
            raise ReadingError(f"queued URL material {material_id!r} not found")
        self.catalog.update_material_status(material_id, IngestionStatus.PROCESSING, progress=10)
        try:
            if record.source_kind is SourceKind.YOUTUBE:
                return await self._process_youtube(record, preferred_languages)
            if record.source_kind is SourceKind.BILIBILI:
                return await self._process_bilibili(record, preferred_languages)
            return await self._process_web(record)
        except Exception as exc:
            logger.exception(
                "Reading URL ingestion failed for material %s (%s)",
                material_id,
                record.source_kind.value,
            )
            code = {
                SourceKind.YOUTUBE: "youtube_transcript_failed",
                SourceKind.BILIBILI: "bilibili_metadata_failed",
            }.get(record.source_kind, "web_fetch_failed")
            return self.catalog.update_material_status(
                material_id,
                IngestionStatus.FAILED,
                error_code=code,
                error_detail=str(exc),
            )

    async def retry(self, material_id: str) -> MaterialRecord:
        record = self.catalog.get_material(material_id)
        if record is None:
            raise ReadingError(f"material {material_id!r} not found")
        if record.source_kind in {
            SourceKind.WEB,
            SourceKind.YOUTUBE,
            SourceKind.BILIBILI,
        }:
            return await self.process_url(material_id)
        raise ReadingError("uploaded media must be selected again to retry")

    async def _process_web(self, record: MaterialRecord) -> MaterialRecord:
        outcome = await self._web_fetcher(record.source_url, max_chars=500_000)
        if not outcome.ok:
            raise ReadingError(outcome.error or "web source could not be fetched")
        source_url = outcome.url or record.source_url
        markdown = strip_leading_snapshot_provenance(outcome.markdown)
        markdown, assets = await localize_snapshot_images(
            markdown,
            record.material_id,
            fetcher=self._image_fetcher,
        )
        units, outline = split_markdown_by_headings(markdown)
        if not units:
            raise ReadingError("web source contained no readable article text")
        self.reading_store.ingest_units(
            record.material_id,
            filename=f"{record.material_id}.md",
            units=units,
            unit="section",
            title=outcome.title or record.title,
            mime="text/markdown",
            extractor="safe-web-fetch",
            content_format="web_markdown",
            source_type="url_snapshot",
            source_url=source_url,
            assets=assets,
            # An empty outline means the page had only its synthetic title (or
            # no headings), so ReadingStore deliberately retains its existing
            # first-line fallback for unstructured web content.
            outline=outline or None,
        )
        return self.catalog.upsert_material(
            content_id=record.content_id,
            material_id=record.material_id,
            filename=f"{record.material_id}.md",
            title=outcome.title or record.title,
            source_kind=SourceKind.WEB,
            source_url=source_url,
            mime="text/markdown",
            render_mode="text",
            status=IngestionStatus.READY,
        )

    async def _process_youtube(
        self, record: MaterialRecord, preferred_languages: Sequence[str]
    ) -> MaterialRecord:
        title, cover_url, segments = await self._youtube_loader(
            record.source_url, preferred_languages
        )
        segments = [row for row in segments if row.text.strip()]
        # Playback is useful even when YouTube exposes no captions.  Keep the
        # material openable and make the lack of grounding explicit instead of
        # failing the whole import.  The capability recognizes this extractor
        # and refuses transcript-backed claims; the UI hides this sentinel.
        stored_segments = segments or [
            TranscriptSegment(
                float(parse_youtube_url(record.source_url).entry_time_seconds),
                float(parse_youtube_url(record.source_url).entry_time_seconds),
                TRANSCRIPT_UNAVAILABLE_TEXT,
            )
        ]
        self.reading_store.ingest_units(
            record.material_id,
            filename=f"youtube-{youtube_video_id(record.source_url)}.vtt",
            units=[row.text for row in stored_segments],
            unit="segment",
            title=title or record.title,
            mime="text/vtt",
            extractor="youtube-captions" if segments else "youtube-no-captions",
            render_mode="video",
            outline=[
                OutlineEntry(locator=index, title=_clock(row.start_seconds))
                for index, row in enumerate(stored_segments, start=1)
            ],
            unit_refs=[
                UnitReference(
                    locator=index,
                    source_href=f"#t={int(row.start_seconds)}",
                    title=_clock(row.start_seconds),
                )
                for index, row in enumerate(stored_segments, start=1)
            ],
        )
        return self.catalog.upsert_material(
            content_id=record.content_id,
            material_id=record.material_id,
            filename=f"youtube-{youtube_video_id(record.source_url)}.vtt",
            title=title or record.title,
            source_kind=SourceKind.YOUTUBE,
            source_url=record.source_url,
            mime="text/vtt",
            render_mode="video",
            cover_url=cover_url,
            status=IngestionStatus.READY,
        )

    async def _process_bilibili(
        self, record: MaterialRecord, preferred_languages: Sequence[str]
    ) -> MaterialRecord:
        request = parse_bilibili_url(record.source_url)
        media = await self._bilibili_loader(record.source_url, preferred_languages)
        segments = [row for row in media.segments if row.text.strip()]
        chapters = [row for row in media.chapters if row.text.strip()]
        if segments:
            stored_segments = segments
            extractor = "bilibili-subtitles"
            outline_titles = [_clock(row.start_seconds) for row in stored_segments]
        elif chapters:
            stored_segments = [
                TranscriptSegment(
                    row.start_seconds,
                    row.end_seconds,
                    f"Chapter marker: {row.text}. Spoken transcript unavailable.",
                )
                for row in chapters
            ]
            extractor = "bilibili-chapters-only"
            outline_titles = [row.text for row in chapters]
        else:
            stored_segments = [
                TranscriptSegment(
                    float(request.entry_time_seconds),
                    float(request.entry_time_seconds),
                    TRANSCRIPT_UNAVAILABLE_TEXT,
                )
            ]
            extractor = "bilibili-no-subtitles"
            outline_titles = [_clock(request.entry_time_seconds)]

        filename = f"bilibili-{request.bvid}-p{media.page_number}.vtt"
        self.reading_store.ingest_units(
            record.material_id,
            filename=filename,
            units=[row.text for row in stored_segments],
            unit="segment",
            title=media.title or record.title,
            mime="text/vtt",
            extractor=extractor,
            render_mode="video",
            outline=[
                OutlineEntry(locator=index, title=outline_titles[index - 1])
                for index in range(1, len(stored_segments) + 1)
            ],
            unit_refs=[
                UnitReference(
                    locator=index,
                    source_href=f"#t={int(row.start_seconds)}",
                    title=outline_titles[index - 1],
                )
                for index, row in enumerate(stored_segments, start=1)
            ],
        )
        return self.catalog.upsert_material(
            content_id=record.content_id,
            material_id=record.material_id,
            filename=filename,
            title=media.title or record.title,
            source_kind=SourceKind.BILIBILI,
            source_url=record.source_url,
            mime="text/vtt",
            render_mode="video",
            cover_url=media.cover_url,
            duration_seconds=media.duration_seconds,
            status=IngestionStatus.READY,
        )

    async def import_media(
        self,
        source: Path | str,
        *,
        filename: str | None = None,
        language: str | None = None,
    ) -> MaterialRecord:
        path = Path(source)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ReadingError(f"{path.name}: could not be read ({exc})") from exc
        if not raw:
            raise ReadingError(f"{path.name} is empty")
        display_name = (filename or path.name).strip() or path.name
        material_id = content_hash(raw)
        suffix = Path(display_name).suffix.lower()
        is_audio = suffix in _AUDIO_SUFFIXES and suffix != ".webm"
        kind = SourceKind.AUDIO if is_audio else SourceKind.VIDEO
        render_mode = "audio" if is_audio else "video"
        mime = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
        self.catalog.upsert_material(
            content_id=material_id,
            material_id=material_id,
            filename=display_name,
            title=Path(display_name).stem,
            source_kind=kind,
            mime=mime,
            render_mode=render_mode,
            status=IngestionStatus.QUEUED,
        )
        self.catalog.update_material_status(material_id, IngestionStatus.PROCESSING, progress=15)
        try:
            chunks = await self._media_chunker(path)
            segments: list[TranscriptSegment] = []
            for index, (start, end, audio) in enumerate(chunks, start=1):
                text = await self._transcriber(
                    audio,
                    filename=f"{Path(display_name).stem}-{index:04d}.mp3",
                    content_type="audio/mpeg",
                    language=language,
                )
                if text.strip():
                    segments.append(TranscriptSegment(start, end, text.strip()))
                progress = 15 + round(index / max(1, len(chunks)) * 70)
                self.catalog.update_material_status(
                    material_id, IngestionStatus.PROCESSING, progress=progress
                )
            if not segments:
                raise ReadingError("media transcription returned no readable text")
            self.reading_store.ingest_units(
                material_id,
                filename=display_name,
                units=[row.text for row in segments],
                unit="segment",
                title=Path(display_name).stem,
                mime=mime,
                extractor="configured-stt",
                render_mode=render_mode,
                raw_data=raw,
                outline=[
                    OutlineEntry(locator=index, title=_clock(row.start_seconds))
                    for index, row in enumerate(segments, start=1)
                ],
                unit_refs=[
                    UnitReference(
                        locator=index,
                        source_href=f"#t={int(row.start_seconds)}",
                        title=_clock(row.start_seconds),
                    )
                    for index, row in enumerate(segments, start=1)
                ],
            )
            return self.catalog.upsert_material(
                content_id=material_id,
                material_id=material_id,
                filename=display_name,
                title=Path(display_name).stem,
                source_kind=kind,
                mime=mime,
                render_mode=render_mode,
                status=IngestionStatus.READY,
            )
        except Exception as exc:
            logger.exception("Reading media ingestion failed for material %s", material_id)
            self.catalog.update_material_status(
                material_id,
                IngestionStatus.FAILED,
                error_code="media_transcription_failed",
                error_detail=str(exc),
            )
            raise


def normalize_url(url: str) -> str:
    value = (url or "").strip().strip("`\"'")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ReadingError("URL must use http:// or https:// and include a host")
    if (parsed.hostname or "").lower().rstrip(".") in _YOUTUBE_HOSTS:
        return parse_youtube_url(value).canonical_url
    if (parsed.hostname or "").lower().rstrip(".") in _BILIBILI_HOSTS:
        return parse_bilibili_url(value).canonical_url
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )


def youtube_video_id(url: str) -> str | None:
    try:
        return parse_youtube_url(url).video_id
    except ReadingError:
        return None


def bilibili_video_id(url: str) -> str | None:
    try:
        return parse_bilibili_url(url).bvid
    except ReadingError:
        return None


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
    """Parse every native YouTube URL shape accepted by the player.

    Tracking parameters are deliberately dropped.  A stable canonical URL
    deduplicates watch/Shorts/Live/embed links for the same video while keeping
    an explicit entry timestamp.
    """

    parsed = urlparse((value or "").strip().strip("`\"'"))
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ReadingError("YouTube URL must use HTTP or HTTPS")
    host = (parsed.hostname or "").lower().rstrip(".")
    query = parse_qs(parsed.query)
    candidate = ""
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            candidate = query.get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            parts = parsed.path.split("/", 2)
            candidate = parts[2].split("/", 1)[0] if len(parts) > 2 else ""
    if not _YOUTUBE_ID.fullmatch(candidate):
        raise ReadingError("Unsupported or invalid YouTube URL")
    entry = parse_timestamp(query.get("t", query.get("start", ["0"]))[0])
    canonical_query = urlencode({"t": entry}) if entry else ""
    canonical = urlunparse(("https", "youtu.be", f"/{candidate}", "", canonical_query, ""))
    return YouTubeRequest(candidate, canonical, entry)


def parse_bilibili_url(value: str) -> BilibiliRequest:
    """Parse official Bilibili video and player URLs without tracking data."""

    parsed = urlparse((value or "").strip().strip("`\"'"))
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ReadingError("Bilibili URL must use HTTP or HTTPS")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _BILIBILI_HOSTS:
        raise ReadingError("Unsupported or invalid Bilibili URL")
    query = parse_qs(parsed.query)
    candidate = ""
    if host == "player.bilibili.com" and parsed.path.rstrip("/") == "/player.html":
        candidate = query.get("bvid", [""])[0]
    elif host == "b23.tv":
        candidate = parsed.path.strip("/").split("/", 1)[0]
    else:
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", parsed.path, re.IGNORECASE)
        candidate = match.group(1) if match else ""
    if not _BILIBILI_ID.fullmatch(candidate):
        raise ReadingError("Unsupported or invalid Bilibili URL")
    # The BV prefix is case-sensitive in public links; normalize it while
    # preserving the opaque payload exactly as supplied by Bilibili.
    candidate = f"BV{candidate[2:]}"
    try:
        page = max(1, int(query.get("p", query.get("page", ["1"]))[0] or 1))
    except (TypeError, ValueError):
        page = 1
    entry = parse_timestamp(query.get("t", query.get("start", ["0"]))[0])
    canonical_query: dict[str, int] = {}
    if page > 1:
        canonical_query["p"] = page
    if entry:
        canonical_query["t"] = entry
    canonical = urlunparse(
        (
            "https",
            "www.bilibili.com",
            f"/video/{candidate}/",
            "",
            urlencode(canonical_query),
            "",
        )
    )
    return BilibiliRequest(candidate, canonical, page, entry)


def normalize_transcript_segments(rows: Sequence[Any]) -> list[TranscriptSegment]:
    """Normalize caption providers under a bounded storage budget."""

    result: list[TranscriptSegment] = []
    total_bytes = 0
    for row in list(rows)[:MAX_TRANSCRIPT_CUES]:
        if isinstance(row, dict):
            text = str(row.get("text") or row.get("content") or "").strip()
            start = row.get("start", row.get("from", 0))
            end = row.get("end", row.get("to", 0))
            duration = row.get("duration", 0)
        else:
            text = str(getattr(row, "text", "") or "").strip()
            start = getattr(row, "start", 0)
            end = getattr(row, "end", 0)
            duration = getattr(row, "duration", 0)
        if not text:
            continue
        encoded = text.encode("utf-8")
        if total_bytes + len(encoded) > MAX_TRANSCRIPT_BYTES:
            break
        try:
            start_value = max(0.0, float(start or 0))
            end_value = float(end or 0)
            if end_value <= start_value:
                end_value = start_value + max(0.0, float(duration or 0))
        except (TypeError, ValueError):
            continue
        result.append(TranscriptSegment(start_value, max(start_value, end_value), text))
        total_bytes += len(encoded)
    return result


def build_transcript_segments(cues: Sequence[TranscriptSegment]) -> list[TranscriptSegment]:
    """Merge subtitle flashes into stable 20–90 second learning units."""

    merged: list[TranscriptSegment] = []
    current: TranscriptSegment | None = None
    for cue in cues:
        if current is None:
            current = cue
            continue
        gap = max(0.0, cue.start_seconds - current.end_seconds)
        length = cue.end_seconds - current.start_seconds
        sentence_end = current.text.rstrip().endswith((".", "!", "?", "。", "！", "？"))
        if (
            length < MAX_SEGMENT_SECONDS
            and gap <= 4
            and not (length >= MIN_SEGMENT_SECONDS and sentence_end)
        ):
            current = TranscriptSegment(
                current.start_seconds,
                cue.end_seconds,
                f"{current.text} {cue.text}".strip(),
            )
        else:
            merged.append(current)
            current = cue
    if current is not None:
        merged.append(current)
    return merged


async def _load_youtube_captions(
    url: str, languages: Sequence[str]
) -> tuple[str, str, list[TranscriptSegment]]:
    video_id = youtube_video_id(url)
    if not video_id:
        raise ReadingError("invalid YouTube URL")

    def fetch_rows() -> list[Any]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError:
            # Native playback is independent from transcript extraction.  A
            # lean CLI/server install may omit this optional dependency; treat
            # that exactly like a video with no public captions so the material
            # still opens and the UI explains the grounding limitation.
            return []
        api = YouTubeTranscriptApi()
        try:
            if hasattr(api, "fetch"):
                return list(api.fetch(video_id, languages=list(languages)))
            return list(YouTubeTranscriptApi.get_transcript(video_id, languages=list(languages)))
        except Exception:
            # Captions can be disabled, unavailable in the preferred language,
            # region-blocked, or temporarily rejected by YouTube. None of those
            # should turn a valid native player into a failed reading source.
            return []

    rows = await asyncio.to_thread(fetch_rows)
    segments = build_transcript_segments(normalize_transcript_segments(rows))

    title = "YouTube video"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            )
            if response.is_success:
                title = str(response.json().get("title") or title)
    except Exception:
        pass
    cover = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return title, cover, segments


async def _load_bilibili_media(url: str, languages: Sequence[str]) -> BilibiliMedia:
    """Load public metadata, subtitles, and chapters for an official BV URL.

    Playback itself stays on Bilibili's documented external player. All API
    destinations below are fixed, and the only response-provided URL we fetch
    is restricted to Bilibili's subtitle CDN.
    """

    request = parse_bilibili_url(url)
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - server installs include httpx
        raise ReadingError("Bilibili import requires httpx") from exc

    headers = {
        "Accept": "application/json",
        "Referer": request.canonical_url,
        "User-Agent": "Mozilla/5.0 DeepTutor/ImmersiveReading",
    }
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        headers=headers,
    ) as client:
        view_response = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": request.bvid},
        )
        view = _bilibili_api_data(view_response, "video metadata")
        pages = view.get("pages") if isinstance(view.get("pages"), list) else []
        if not pages:
            raise ReadingError("Bilibili returned no playable pages")
        page_index = min(request.page_number, len(pages)) - 1
        page = pages[page_index] if isinstance(pages[page_index], dict) else {}
        try:
            cid = int(page.get("cid") or 0)
        except (TypeError, ValueError):
            cid = 0
        if cid <= 0:
            raise ReadingError("Bilibili returned an invalid page identifier")
        resolved_page = page_index + 1
        try:
            duration = max(0.0, float(page.get("duration") or view.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0.0
        title = str(view.get("title") or "Bilibili video").strip()
        part = str(page.get("part") or "").strip()
        if len(pages) > 1 and part and part != title:
            title = f"{title} · P{resolved_page} {part}"
        cover = str(view.get("pic") or "").strip()
        if cover.startswith("http://"):
            cover = f"https://{cover.removeprefix('http://')}"
        elif cover.startswith("//"):
            cover = f"https:{cover}"

        player_response = await client.get(
            "https://api.bilibili.com/x/player/v2",
            params={"bvid": request.bvid, "cid": cid},
        )
        player = _bilibili_api_data(player_response, "player metadata")
        chapters = build_transcript_segments(
            normalize_transcript_segments(player.get("view_points") or [])
        )
        subtitle_root = player.get("subtitle")
        subtitle_rows = (
            subtitle_root.get("subtitles")
            if isinstance(subtitle_root, dict) and isinstance(subtitle_root.get("subtitles"), list)
            else []
        )
        segments: list[TranscriptSegment] = []
        subtitle = _preferred_bilibili_subtitle(subtitle_rows, languages)
        if subtitle:
            subtitle_url = str(subtitle.get("subtitle_url") or "").strip()
            if subtitle_url.startswith("//"):
                subtitle_url = f"https:{subtitle_url}"
            subtitle_parsed = urlparse(subtitle_url)
            subtitle_host = (subtitle_parsed.hostname or "").lower().rstrip(".")
            if subtitle_parsed.scheme == "https" and (
                subtitle_host == "hdslb.com" or subtitle_host.endswith(".hdslb.com")
            ):
                subtitle_response = await client.get(subtitle_url)
                if len(subtitle_response.content) > MAX_TRANSCRIPT_BYTES * 2:
                    raise ReadingError("Bilibili subtitle response exceeded the size limit")
                subtitle_response.raise_for_status()
                subtitle_payload = subtitle_response.json()
                body = (
                    subtitle_payload.get("body")
                    if isinstance(subtitle_payload, dict)
                    and isinstance(subtitle_payload.get("body"), list)
                    else []
                )
                segments = build_transcript_segments(normalize_transcript_segments(body))

    return BilibiliMedia(
        title=title,
        cover_url=cover,
        duration_seconds=duration,
        page_number=resolved_page,
        cid=cid,
        segments=segments,
        chapters=chapters,
    )


def _bilibili_api_data(response: Any, label: str) -> dict[str, Any]:
    if len(response.content) > MAX_TRANSCRIPT_BYTES * 2:
        raise ReadingError(f"Bilibili {label} response exceeded the size limit")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or int(payload.get("code") or 0) != 0:
        message = (
            str(payload.get("message") or "request failed")
            if isinstance(payload, dict)
            else "invalid response"
        )
        raise ReadingError(f"Bilibili {label} failed: {message}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ReadingError(f"Bilibili {label} returned invalid data")
    return data


def _preferred_bilibili_subtitle(
    rows: Sequence[Any], languages: Sequence[str]
) -> dict[str, Any] | None:
    candidates = [row for row in rows if isinstance(row, dict)]
    if not candidates:
        return None
    preferences = [str(value).lower().replace("_", "-") for value in languages]

    def score(row: dict[str, Any]) -> tuple[int, int]:
        language = str(row.get("lan") or "").lower().replace("_", "-")
        for index, preference in enumerate(preferences):
            if language == preference:
                return (index, 0)
            if language.split("-", 1)[0] == preference.split("-", 1)[0]:
                return (index, 1)
        return (len(preferences), 2)

    return min(candidates, key=score)


async def _chunk_media_audio(path: Path) -> list[tuple[float, float, bytes]]:
    if shutil.which("ffmpeg") is None:
        raise ReadingError("Video transcription requires ffmpeg on the server")

    def run() -> list[tuple[float, float, bytes]]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="dt-reading-audio-"))
        try:
            pattern = tmp_dir / "chunk-%04d.mp3"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "segment",
                "-segment_time",
                "600",
                "-c:a",
                "libmp3lame",
                str(pattern),
            ]
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=3600, check=False
            )
            if completed.returncode != 0:
                raise ReadingError(completed.stderr.strip() or "ffmpeg could not read this media")
            files = sorted(tmp_dir.glob("chunk-*.mp3"))
            return [
                (float(index * 600), float((index + 1) * 600), chunk.read_bytes())
                for index, chunk in enumerate(files)
                if chunk.stat().st_size
            ]
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return await asyncio.to_thread(run)


def _clock(seconds: float) -> str:
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


__all__ = [
    "BilibiliMedia",
    "BilibiliRequest",
    "ReadingIngestionService",
    "TranscriptSegment",
    "TRANSCRIPT_UNAVAILABLE_TEXT",
    "YouTubeRequest",
    "build_transcript_segments",
    "bilibili_video_id",
    "normalize_url",
    "normalize_transcript_segments",
    "parse_timestamp",
    "parse_bilibili_url",
    "parse_youtube_url",
    "youtube_video_id",
]
