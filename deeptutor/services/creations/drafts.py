"""User-scoped drafts produced by create mode's ``propose_creation`` tool.

Modelled closely on :mod:`deeptutor.services.partners.drafts`: a draft is
deliberately separate from the real Skill/Persona it may become. Only the
authenticated user's explicit Approve, through the ``/api/creations`` router,
writes anything through ``SkillService``/``PersonaService``.
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
class CreationDraft:
    draft_id: str
    owner_id: str
    kind: str
    session_id: str
    name: str
    description: str
    content: str
    tags: list[str] = field(default_factory=list)
    references: list[dict[str, str]] = field(default_factory=list)
    status: str = "pending"  # "pending" | "created"
    created_name: str = ""
    replaced: bool = False
    created_at: str = ""
    approved_at: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """What the draft card renders: references projected to path + size."""
        data = asdict(self)
        data["references"] = [
            {"path": ref.get("path", ""), "size": len(str(ref.get("content", "")).encode("utf-8"))}
            for ref in self.references
        ]
        return data


class CreationDraftStore:
    """Small atomic JSON store rooted in the current human user's workspace."""

    @property
    def root(self) -> Path:
        path = get_current_path_service().get_user_root() / "creation_drafts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(
        self,
        *,
        kind: str,
        session_id: str,
        name: str,
        description: str,
        content: str,
        tags: list[str] | None = None,
        references: list[dict[str, str]] | None = None,
    ) -> CreationDraft:
        draft = CreationDraft(
            draft_id=uuid4().hex,
            owner_id=get_current_user().id,
            kind=str(kind or ""),
            session_id=str(session_id or ""),
            name=str(name or ""),
            description=str(description or ""),
            content=str(content or ""),
            tags=list(tags or []),
            references=list(references or []),
            created_at=datetime.now(UTC).isoformat(),
        )
        if not draft.kind or not draft.name:
            raise ValueError("A creation draft needs a kind and a name.")
        self.save(draft)
        return draft

    def get(self, draft_id: str) -> CreationDraft | None:
        path = self._path(draft_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            draft = CreationDraft(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if draft.owner_id != get_current_user().id:
            return None
        return draft

    def save(self, draft: CreationDraft) -> None:
        if draft.owner_id != get_current_user().id:
            raise PermissionError("Creation draft belongs to another user.")
        path = self._path(draft.draft_id)
        tmp = path.with_suffix(".tmp")
        with _lock_for(path):
            tmp.write_text(
                json.dumps(asdict(draft), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)

    def mark_created(
        self, draft: CreationDraft, *, created_name: str, replaced: bool
    ) -> CreationDraft:
        draft.status = "created"
        draft.created_name = created_name
        draft.replaced = replaced
        draft.approved_at = datetime.now(UTC).isoformat()
        self.save(draft)
        return draft

    def created_by_session(self, session_id: str, kind: str, name: str) -> bool:
        """Did THIS session already create ``name`` as this ``kind``?

        That earlier creation is what turns a second ``propose_creation`` (or
        a second Approve) with the same name into an update instead of a
        name-collision conflict.
        """
        slug = str(name or "").strip().lower()
        session_id = str(session_id or "")
        return any(
            draft.status == "created"
            and draft.kind == kind
            and draft.session_id == session_id
            and draft.created_name.strip().lower() == slug
            for draft in self._iter_drafts()
        )

    def latest_for_session(self, session_id: str, kind: str) -> CreationDraft | None:
        session_id = str(session_id or "")
        matches = [
            draft
            for draft in self._iter_drafts()
            if draft.kind == kind and draft.session_id == session_id
        ]
        if not matches:
            return None
        return max(matches, key=lambda draft: draft.created_at)

    def _iter_drafts(self) -> list[CreationDraft]:
        if not self.root.exists():
            return []
        owner = get_current_user().id
        drafts: list[CreationDraft] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                draft = CreationDraft(**payload)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if draft.owner_id != owner:
                continue
            drafts.append(draft)
        return drafts

    def _path(self, draft_id: str) -> Path:
        normalized = str(draft_id or "").strip().lower()
        if not _SAFE_ID.fullmatch(normalized):
            raise ValueError("Invalid creation draft id.")
        return self.root / f"{normalized}.json"


__all__ = ["CreationDraft", "CreationDraftStore"]
