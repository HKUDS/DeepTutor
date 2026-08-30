"""User-scoped Partner profile drafts produced by the chat engine.

Drafts are deliberately separate from live Partner configuration.  The model
may propose a complete profile, but only the authenticated user's explicit
confirmation promotes it into a real Partner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import threading
from typing import Any
from uuid import uuid4

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import get_current_path_service

_SAFE_ID = re.compile(r"^[a-f0-9]{32}$")
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(resolved, threading.Lock())


@dataclass(slots=True)
class PartnerDraft:
    draft_id: str
    owner_id: str
    name: str
    description: str
    soul: str
    language: str = ""
    emoji: str = ""
    color: str = ""
    enabled_tools: list[str] | None = None
    builtin_tools: list[str] | None = None
    mcp_tools: list[str] | None = field(default_factory=list)
    status: str = "pending"
    created_at: str = ""
    created_partner_id: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PartnerDraftStore:
    """Small atomic JSON store rooted in the current human user's workspace."""

    @property
    def root(self) -> Path:
        path = get_current_path_service().get_user_root() / "partner_drafts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(self, profile: dict[str, Any]) -> PartnerDraft:
        draft = PartnerDraft(
            draft_id=uuid4().hex,
            owner_id=get_current_user().id,
            name=_text(profile.get("name"), 80),
            description=_text(profile.get("description"), 500),
            soul=_text(profile.get("soul"), 20_000),
            language=_text(profile.get("language"), 16),
            emoji=_text(profile.get("emoji"), 16),
            color=_color(profile.get("color")),
            enabled_tools=_string_list(profile.get("enabled_tools")),
            builtin_tools=_string_list(profile.get("builtin_tools")),
            mcp_tools=_string_list(profile.get("mcp_tools"), default=[]),
            created_at=datetime.now(UTC).isoformat(),
        )
        if not draft.name:
            raise ValueError("A Partner draft needs a name.")
        if not draft.soul:
            raise ValueError("A Partner draft needs a non-empty soul profile.")
        self.save(draft)
        return draft

    def get(self, draft_id: str) -> PartnerDraft | None:
        path = self._path(draft_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            draft = PartnerDraft(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if draft.owner_id != get_current_user().id:
            return None
        return draft

    def save(self, draft: PartnerDraft) -> None:
        if draft.owner_id != get_current_user().id:
            raise PermissionError("Partner draft belongs to another user.")
        path = self._path(draft.draft_id)
        tmp = path.with_suffix(".tmp")
        with _lock_for(path):
            tmp.write_text(
                json.dumps(draft.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)

    def mark_created(self, draft: PartnerDraft, partner_id: str) -> PartnerDraft:
        draft.status = "created"
        draft.created_partner_id = partner_id
        self.save(draft)
        return draft

    def _path(self, draft_id: str) -> Path:
        normalized = str(draft_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            raise ValueError("Invalid Partner draft id.")
        return self.root / f"{normalized}.json"


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _color(value: Any) -> str:
    color = _text(value, 16)
    if not color:
        return ""
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return color.lower()
    return ""


def _string_list(value: Any, *, default: list[str] | None = None) -> list[str] | None:
    if value is None:
        return default
    if not isinstance(value, list):
        return default
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:100]


__all__ = ["PartnerDraft", "PartnerDraftStore"]
