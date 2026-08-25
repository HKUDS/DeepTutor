"""Persist Invidious video markers as DeepTutor Notebook records."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

from deeptutor.services.notebook import NotebookManager, RecordType, get_notebook_manager

VIDEO_LEARNING_NOTEBOOK_NAME = "Video Learning"
VIDEO_NOTE_TYPE = RecordType.VIDEO_NOTE.value


def format_position_label(position_ms: int) -> str:
    total = max(0, int(position_ms) // 1000)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def source_url(instance_origin: str, video_id: str, position_ms: int = 0) -> str:
    origin = (instance_origin or "").rstrip("/")
    if not origin or not video_id:
        return ""
    query = {"v": video_id}
    if position_ms > 0:
        query["t"] = f"{max(0, int(position_ms) // 1000)}s"
    return f"{origin}/watch?{urlencode(query)}"


def ensure_video_learning_notebook(manager: NotebookManager | None = None) -> dict[str, Any]:
    mgr = manager or get_notebook_manager()
    for row in mgr.list_notebooks():
        if row.get("unreadable"):
            continue
        if str(row.get("name") or "") == VIDEO_LEARNING_NOTEBOOK_NAME:
            detail = mgr.get_notebook(str(row["id"]))
            if detail:
                return detail
    return mgr.create_notebook(
        name=VIDEO_LEARNING_NOTEBOOK_NAME,
        description="Timestamped notes captured from Invidious remote learning",
        color="#EF4444",
        icon="video",
    )


def resolve_target_notebook(
    notebook_id: str | None,
    *,
    manager: NotebookManager | None = None,
) -> dict[str, Any]:
    mgr = manager or get_notebook_manager()
    if notebook_id:
        notebook = mgr.get_notebook(notebook_id)
        if not notebook:
            raise LookupError("Notebook not found.")
        return notebook
    return ensure_video_learning_notebook(mgr)


def _record_to_note(notebook_id: str, record: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    created_at = record.get("created_at")
    updated_at = metadata.get("updated_at", created_at)
    return {
        "notebook_id": notebook_id,
        "record_id": str(record.get("id") or ""),
        "video_id": str(metadata.get("video_id") or ""),
        "title": str(record.get("title") or metadata.get("video_title") or ""),
        "position_ms": int(metadata.get("position_ms") or 0),
        "body": str(record.get("output") or ""),
        "source": str(metadata.get("source") or "invidious"),
        "instance_origin": str(metadata.get("instance_origin") or ""),
        "source_url": str(metadata.get("source_url") or ""),
        "created_at": created_at,
        "updated_at": updated_at,
        "metadata": metadata,
    }


def list_video_notes(
    video_id: str,
    *,
    notebook_id: str | None = None,
    manager: NotebookManager | None = None,
) -> list[dict[str, Any]]:
    mgr = manager or get_notebook_manager()
    video_id = (video_id or "").strip()
    notes: list[dict[str, Any]] = []
    notebooks = []
    if notebook_id:
        notebook = mgr.get_notebook(notebook_id)
        if notebook:
            notebooks = [notebook]
    else:
        notebooks = [
            nb
            for row in mgr.list_notebooks()
            if not row.get("unreadable")
            for nb in [mgr.get_notebook(str(row["id"]))]
            if nb
        ]
    for notebook in notebooks:
        nb_id = str(notebook.get("id") or "")
        for record in notebook.get("records") or []:
            if str(record.get("type") or "") != VIDEO_NOTE_TYPE:
                continue
            metadata = record.get("metadata") or {}
            if str(metadata.get("video_id") or "") != video_id:
                continue
            notes.append(_record_to_note(nb_id, record))
    notes.sort(key=lambda item: (int(item["position_ms"]), str(item.get("created_at") or "")))
    return notes


def create_video_note(
    *,
    video_id: str,
    position_ms: int,
    body: str,
    title: str = "",
    instance_origin: str = "",
    source: str = "invidious",
    notebook_id: str | None = None,
    manager: NotebookManager | None = None,
) -> dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise ValueError("Note body is required.")
    video_id = (video_id or "").strip()
    if not video_id:
        raise ValueError("video_id is required.")
    position_ms = max(0, int(position_ms))
    mgr = manager or get_notebook_manager()
    notebook = resolve_target_notebook(notebook_id, manager=mgr)
    video_title = (title or "").strip() or video_id
    stamp = format_position_label(position_ms)
    record_title = f"{stamp} · {video_title}"
    metadata = {
        "video_id": video_id,
        "video_title": video_title,
        "instance_origin": instance_origin or "",
        "position_ms": position_ms,
        "source": source or "invidious",
        "source_url": source_url(instance_origin, video_id, position_ms),
    }
    result = mgr.add_record(
        notebook_ids=[str(notebook["id"])],
        record_type=RecordType.VIDEO_NOTE,
        title=record_title,
        user_query=f"Video marker at {stamp}",
        output=body,
        summary=body.splitlines()[0][:180],
        metadata=metadata,
    )
    record = result["record"]
    # Enum may serialize as enum; normalize for response helpers.
    if hasattr(record.get("type"), "value"):
        record = {**record, "type": record["type"].value}
    return _record_to_note(str(notebook["id"]), record)


def update_video_note(
    notebook_id: str,
    record_id: str,
    body: str,
    *,
    manager: NotebookManager | None = None,
) -> dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise ValueError("Note body is required.")
    mgr = manager or get_notebook_manager()
    existing = mgr.get_record(notebook_id, record_id)
    if not existing or str(existing.get("type") or "") != VIDEO_NOTE_TYPE:
        raise LookupError("Note not found.")
    metadata = dict(existing.get("metadata") or {})
    metadata["updated_at"] = time.time()
    updated = mgr.update_record(
        notebook_id,
        record_id,
        output=body,
        summary=body.splitlines()[0][:180],
        metadata=metadata,
    )
    if not updated:
        raise LookupError("Note not found.")
    return _record_to_note(notebook_id, updated)


def delete_video_note(
    notebook_id: str,
    record_id: str,
    *,
    manager: NotebookManager | None = None,
) -> bool:
    mgr = manager or get_notebook_manager()
    existing = mgr.get_record(notebook_id, record_id)
    if not existing or str(existing.get("type") or "") != VIDEO_NOTE_TYPE:
        return False
    return bool(mgr.remove_record(notebook_id, record_id))
