"""Persistent notes for timed-media learning materials."""

from __future__ import annotations

import time
from typing import Any

from deeptutor.services.notebook.service import (
    NotebookCorruptedError,
    NotebookManager,
    RecordType,
    get_notebook_manager,
)
from deeptutor.video_learning.service import (
    TimedMediaError,
    TimedMediaNotFound,
    get_timed_media_store,
)

NOTEBOOK_NAME = "Video Learning"
MAX_QUOTE_CHARS = 280


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds_part:02d}"
    return f"{minutes}:{seconds_part:02d}"


def _clip_text(value: Any, limit: int = MAX_QUOTE_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _segment_at(material: dict[str, Any], time_seconds: float) -> dict[str, Any] | None:
    segments = [row for row in material.get("segments") or [] if isinstance(row, dict)]
    if not segments:
        cues = [
            row for row in material.get("transcript", {}).get("cues") or [] if isinstance(row, dict)
        ]
        segments = [dict(row, locator=index) for index, row in enumerate(cues, start=1)]
    containing = [
        row
        for row in segments
        if float(row.get("start") or 0) <= time_seconds <= float(row.get("end") or 0)
    ]
    if containing:
        return containing[-1]
    preceding = [row for row in segments if float(row.get("start") or 0) <= time_seconds]
    return preceding[-1] if preceding else (segments[0] if segments else None)


def _is_material_note(record: dict[str, Any], material_id: str) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return (
        str(record.get("type") or "") == RecordType.VIDEO_LEARNING.value
        and str(metadata.get("material_id") or "") == material_id
    )


def _matching_records(
    manager: NotebookManager, material_id: str, note_id: str | None = None
) -> list[tuple[str, dict[str, Any]]]:
    for notebook in manager.list_notebooks():
        if notebook.get("unreadable"):
            manager.get_notebook(str(notebook.get("id") or ""))

    matches: list[tuple[str, dict[str, Any]]] = []
    for notebook in manager.list_notebooks():
        if notebook.get("unreadable"):
            continue
        notebook_id = str(notebook.get("id") or "")
        try:
            records = manager.get_records(notebook_id)
        except NotebookCorruptedError:
            continue
        for record in records:
            if not _is_material_note(record, material_id):
                continue
            if note_id is not None and str(record.get("id") or "") != note_id:
                continue
            matches.append((notebook_id, record))
    return matches


def _note(notebook_id: str, record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    updated_at = float(metadata.get("updated_at") or record.get("created_at") or 0)
    return {
        "notebook_id": notebook_id,
        "note_id": str(record.get("id") or ""),
        "material_id": str(metadata.get("material_id") or ""),
        "body": str(record.get("output") or ""),
        "time_seconds": float(metadata.get("time_seconds") or 0),
        "locator": int(metadata.get("locator") or 0),
        "quote": str(metadata.get("quote") or ""),
        "created_at": float(record.get("created_at") or 0),
        "updated_at": updated_at,
    }


def list_notes(manager: NotebookManager, material_id: str) -> list[dict[str, Any]]:
    get_timed_media_store().get(material_id)
    unique: dict[str, tuple[str, dict[str, Any]]] = {}
    for notebook_id, record in _matching_records(manager, material_id):
        unique.setdefault(str(record.get("id") or ""), (notebook_id, record))
    notes = [_note(notebook_id, record) for notebook_id, record in unique.values()]
    notes.sort(key=lambda row: (row["time_seconds"], row["created_at"], row["note_id"]))
    return notes


def export_notes(manager: NotebookManager, material_id: str) -> str:
    material = get_timed_media_store().get(material_id)
    notes = list_notes(manager, material_id)
    title = _clip_text(
        str(material.get("metadata", {}).get("title") or "Timed media").strip() or "Timed media",
        140,
    )
    lines = [f"# Video notes: {title}"]
    if not notes:
        lines.extend(["", "_No timestamped notes captured yet._"])
        return "\n".join(lines).strip() + "\n"

    for note in notes:
        lines.extend(
            (
                "",
                f"## {_format_time(note['time_seconds'])}",
                "",
                str(note.get("body") or "").strip(),
            )
        )
        quote = _clip_text(note.get("quote"))
        if quote:
            lines.extend(("", f"> {quote}"))
    return "\n".join(lines).strip() + "\n"


def create_note(
    manager: NotebookManager, material_id: str, body: str, time_seconds: float
) -> dict[str, Any]:
    clean_body = body.strip()
    if not clean_body:
        raise TimedMediaError("A timed-media note needs text.")
    material = get_timed_media_store().get(material_id)
    duration = float(material.get("metadata", {}).get("duration_seconds") or 0)
    if duration and time_seconds > duration:
        raise TimedMediaError("Timed-media note timestamp is beyond the material duration.")

    segment = _segment_at(material, time_seconds)
    quote = _clip_text(segment.get("text")) if segment else ""
    title = _clip_text(
        str(material.get("metadata", {}).get("title") or "Timed media").strip() or "Timed media",
        140,
    )
    notebook = manager.get_or_create_notebook(
        NOTEBOOK_NAME,
        description="Notes captured while learning with timed media.",
        color="#EF4444",
        icon="video",
    )
    now = time.time()
    result = manager.add_record(
        notebook_ids=[str(notebook["id"])],
        record_type=RecordType.VIDEO_LEARNING,
        title=f"{title} - {_format_time(time_seconds)}",
        summary=_clip_text(clean_body, 160),
        user_query=quote,
        output=clean_body,
        metadata={
            "material_id": material_id,
            "time_seconds": time_seconds,
            "locator": int(segment.get("locator") or 0) if segment else 0,
            "quote": quote,
            "updated_at": now,
        },
    )
    if not result.get("added_to_notebooks"):
        raise TimedMediaError("The Video Learning notebook could not be saved.")
    return _note(str(notebook["id"]), result["record"])


def update_note(
    manager: NotebookManager, material_id: str, note_id: str, body: str
) -> dict[str, Any]:
    clean_body = body.strip()
    if not clean_body:
        raise TimedMediaError("A timed-media note needs text.")
    get_timed_media_store().get(material_id)
    matches = _matching_records(manager, material_id, note_id)
    if not matches:
        raise TimedMediaNotFound("Timed-media note was not found.")
    now = time.time()
    updated: dict[str, Any] | None = None
    for notebook_id, record in matches:
        updated = manager.update_record(
            notebook_id,
            str(record.get("id") or ""),
            summary=_clip_text(clean_body, 160),
            output=clean_body,
            metadata={"updated_at": now},
        )
    if updated is None:
        raise TimedMediaNotFound("Timed-media note was not found.")
    return _note(matches[0][0], updated)


def delete_note(manager: NotebookManager, material_id: str, note_id: str) -> bool:
    get_timed_media_store().get(material_id)
    matches = _matching_records(manager, material_id, note_id)
    if not matches:
        raise TimedMediaNotFound("Timed-media note was not found.")
    removed = [
        manager.remove_record(notebook_id, str(record.get("id") or ""))
        for notebook_id, record in matches
    ]
    return any(removed)


__all__ = [
    "NOTEBOOK_NAME",
    "create_note",
    "delete_note",
    "export_notes",
    "get_notebook_manager",
    "list_notes",
    "update_note",
]
