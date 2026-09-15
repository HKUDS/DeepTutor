"""Compatibility migration from Immersive Watching to Immersive Reading.

TimedMedia remains the provider cache for old records; this module projects a
read-only copy into Reading's material, annotation, and workspace stores. It
never mutates the legacy JSON or Notebook records.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from typing import Any

from deeptutor.reading.catalog_models import IngestionStatus, SourceKind
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.ingestion import (
    TRANSCRIPT_UNAVAILABLE_TEXT,
    ReadingIngestionService,
    TranscriptSegment,
    build_transcript_segments,
    normalize_transcript_segments,
    normalize_url,
)
from deeptutor.reading.models import Annotation, ReadingPosition
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager, get_notebook_manager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning.service import TimedMediaStore, get_timed_media_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReadingMigrationResult:
    timed_media_id: str
    reading_workspace_id: str
    reading_material_id: str


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[: limit - 3].rstrip()}..."


def _legacy_source_url(material: dict[str, Any]) -> str:
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    candidate = str(source.get("url") or "").strip()
    if candidate:
        return candidate
    video_id = str(source.get("video_id") or "").strip()
    if video_id:
        return f"https://youtu.be/{video_id}"
    raise ValueError("legacy timed-media record has no source URL")


def _segment_locator(segments: list[TranscriptSegment], seconds: float) -> int:
    locator = 1
    for index, segment in enumerate(segments, start=1):
        if segment.start_seconds <= seconds + 0.05:
            locator = index
        elif segment.start_seconds > seconds + 0.05:
            break
    return locator


class WatchingToReadingMigration:
    def __init__(
        self,
        *,
        timed_media_store: TimedMediaStore | None = None,
        reading_store: ReadingStore | None = None,
        catalog: ReadingCatalogStore | None = None,
        notebook_manager: NotebookManager | None = None,
    ) -> None:
        self.timed_media_store = timed_media_store or get_timed_media_store()
        self.reading_store = reading_store or ReadingStore()
        self.catalog = catalog or ReadingCatalogStore(self.reading_store.root)
        self.notebook_manager = notebook_manager or get_notebook_manager()

    async def migrate(
        self,
        timed_media_id: str,
        *,
        session_id: str = "",
        session_title: str = "Imported video conversation",
    ) -> ReadingMigrationResult:
        legacy = self.timed_media_store.get(timed_media_id)
        source_url = normalize_url(_legacy_source_url(legacy))
        metadata = legacy.get("metadata") if isinstance(legacy.get("metadata"), dict) else {}
        transcript = legacy.get("transcript") if isinstance(legacy.get("transcript"), dict) else {}
        segments = build_transcript_segments(
            normalize_transcript_segments(transcript.get("cues") or [])
        )
        segments = segments or [TranscriptSegment(0.0, 0.0, TRANSCRIPT_UNAVAILABLE_TEXT)]
        title = _clip(metadata.get("title") or source_url, 500)
        cover_url = str(metadata.get("thumbnail_url") or "")
        duration = max(0.0, float(metadata.get("duration_seconds") or 0))

        async def cached_loader(_url: str, _languages) -> tuple[str, str, list[TranscriptSegment]]:
            return title, cover_url, segments

        ingestion = ReadingIngestionService(
            self.reading_store,
            self.catalog,
            youtube_loader=cached_loader,
        )
        queued = ingestion.queue_url(source_url, title=title)
        ready = await ingestion.process_url(queued.material_id)
        if ready.status is not IngestionStatus.READY:
            raise RuntimeError(ready.error_detail or "legacy timed media could not be imported")
        ready = self.catalog.upsert_material(
            content_id=ready.content_id,
            material_id=ready.material_id,
            filename=ready.filename,
            title=title,
            source_kind=SourceKind.YOUTUBE,
            source_url=source_url,
            mime=ready.mime,
            render_mode="video",
            cover_url=cover_url,
            duration_seconds=duration,
            status=IngestionStatus.READY,
        )

        workspace_id = (
            "rw_" + hashlib.sha256(f"legacy-watching:{timed_media_id}".encode()).hexdigest()[:24]
        )
        workspace = self.catalog.get_workspace(workspace_id)
        if workspace is None:
            workspace = self.catalog.create_workspace(
                title,
                [ready.material_id],
                description="Imported from Immersive Watching.",
                workspace_id=workspace_id,
            )
        else:
            workspace = self.catalog.add_material(
                workspace_id,
                ready.material_id,
                make_active=workspace.active_material_id is None,
            )

        if not self.reading_store.has_position(ready.material_id):
            self._copy_position(legacy, segments, ready.material_id, duration)
        self._copy_notes(timed_media_id, segments, ready.material_id)
        if session_id:
            self.catalog.attach_session(
                workspace_id,
                session_id,
                title=session_title or "Imported video conversation",
                active_material_id=ready.material_id,
            )
        return ReadingMigrationResult(timed_media_id, workspace_id, ready.material_id)

    def _copy_position(
        self,
        legacy: dict[str, Any],
        segments: list[TranscriptSegment],
        material_id: str,
        duration: float,
    ) -> None:
        learning = legacy.get("learning") if isinstance(legacy.get("learning"), dict) else {}
        seconds = max(0.0, float(learning.get("last_position") or 0))
        self.reading_store.save_position(
            material_id,
            ReadingPosition(
                locator=_segment_locator(segments, seconds),
                source_anchor=f"#t={int(seconds)}",
                percentage=min(1.0, seconds / duration) if duration > 0 else 0.0,
            ),
        )

    def _copy_notes(
        self,
        timed_media_id: str,
        segments: list[TranscriptSegment],
        material_id: str,
    ) -> None:
        existing_ids = {row.annotation_id for row in self.reading_store.annotations(material_id)}
        for note in video_notes.list_notes(self.notebook_manager, timed_media_id):
            annotation_id = (
                "legacy-video-" + hashlib.sha256(str(note["note_id"]).encode()).hexdigest()[:24]
            )
            if annotation_id in existing_ids:
                continue
            seconds = max(0.0, float(note.get("time_seconds") or 0))
            locator = _segment_locator(segments, seconds)
            segment = segments[locator - 1]
            self.reading_store.save_annotation(
                material_id,
                Annotation(
                    annotation_id=annotation_id,
                    locator=locator,
                    kind="note",
                    quote=_clip(segment.text, 2000),
                    note=str(note.get("body") or "").strip(),
                    source_anchor=f"#t={int(seconds)}",
                    author="user",
                    created_at=float(note.get("created_at") or 0),
                    updated_at=float(note.get("updated_at") or 0),
                ),
            )


__all__ = [
    "ReadingMigrationResult",
    "WatchingToReadingMigration",
]
