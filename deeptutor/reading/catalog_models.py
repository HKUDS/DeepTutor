"""Typed records for the private Immersive Reading library.

The extracted source remains in :mod:`deeptutor.reading.store`. These records
describe how reusable sources are organised into reading workspaces, tabs, and
conversations. Keeping that distinction explicit prevents workspace UI state
from leaking into the content-addressed material store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SourceKind(str, Enum):
    FILE = "file"
    WEB = "web"
    VIDEO = "video"
    YOUTUBE = "youtube"
    BILIBILI = "bilibili"
    AUDIO = "audio"


class IngestionStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MaterialRecord:
    material_id: str
    content_id: str
    filename: str
    title: str
    source_kind: SourceKind
    source_url: str = ""
    mime: str = ""
    render_mode: str = "text"
    cover_url: str = ""
    duration_seconds: float = 0.0
    status: IngestionStatus = IngestionStatus.QUEUED
    progress: int = 0
    error_code: str = ""
    error_detail: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    last_opened_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "content_id": self.content_id,
            "filename": self.filename,
            "title": self.title,
            "source_kind": self.source_kind.value,
            "source_url": self.source_url,
            "mime": self.mime,
            "render_mode": self.render_mode,
            "cover_url": self.cover_url,
            "duration_seconds": self.duration_seconds,
            "status": self.status.value,
            "progress": self.progress,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_opened_at": self.last_opened_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceTab:
    material: MaterialRecord
    tab_order: int
    pinned: bool = False
    opened: bool = True
    added_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "material": self.material.to_dict(),
            "tab_order": self.tab_order,
            "pinned": self.pinned,
            "opened": self.opened,
            "added_at": self.added_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    workspace_id: str
    title: str
    description: str = ""
    active_material_id: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    tabs: tuple[WorkspaceTab, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "title": self.title,
            "description": self.description,
            "active_material_id": self.active_material_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tabs": [row.to_dict() for row in self.tabs],
        }


@dataclass(frozen=True, slots=True)
class ReadingSessionRecord:
    workspace_id: str
    session_id: str
    title: str
    active_material_id: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "title": self.title,
            "active_material_id": self.active_material_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


__all__ = [
    "IngestionStatus",
    "MaterialRecord",
    "ReadingSessionRecord",
    "SourceKind",
    "WorkspaceRecord",
    "WorkspaceTab",
]
