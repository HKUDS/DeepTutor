"""Stable workspace and immutable presentation value objects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class WorkspaceError(ValueError):
    """A workspace path, binding, or operation is not allowed."""


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    workspace_id: str
    root: Path
    display_name: str
    is_default: bool = False
    locked: bool = False

    def public_dict(self, *, security_level: str, status: str = "ready") -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "path": str(self.root),
            "display_name": self.display_name,
            "is_default": self.is_default,
            "locked": self.locked,
            "status": status,
            "security_level": security_level,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceItem:
    workspace_id: str
    workspace_item_id: str
    relative_path: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    url: str
    title: str = ""
    caption: str = ""
    generated: bool = False
    data_workspace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
