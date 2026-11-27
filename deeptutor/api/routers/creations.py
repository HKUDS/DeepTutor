"""Create mode review API: read and approve a Skill/Persona draft.

Drafts are produced by the chat loop's ``propose_creation`` tool
(:mod:`deeptutor.capabilities.creator`); this router is the only place a
draft is turned into a real Skill or Persona, through the owning
``CreationKind.publish`` (``SkillService`` / ``PersonaService``), exactly
like one authored on the Skills/Personas pages. Modelled on the Partner
draft routes in ``deeptutor/api/routers/partners.py``.

Mounted at ``/api/creations`` via ``deeptutor/modules/manifests/server.json``,
next to the Skills and Personas routers.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deeptutor.multi_user.context import get_current_user
from deeptutor.services.creations import CreationDraftStore, get_creation_kind
from deeptutor.services.creations.kinds import CreationKind

router = APIRouter()

# Per-(user, draft) lock, matching the Partner draft confirm routes: two
# concurrent Approves on the same draft must not both publish.
_approve_locks: dict[tuple[str, str], asyncio.Lock] = {}
_approve_locks_mutex = asyncio.Lock()


async def _get_approve_lock(draft_id: str) -> asyncio.Lock:
    key = (get_current_user().id, draft_id)
    async with _approve_locks_mutex:
        lock = _approve_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _approve_locks[key] = lock
        return lock


class ApproveCreationRequest(BaseModel):
    """Editable fields accepted by the explicit draft-approval step."""

    name: str | None = None
    description: str | None = None
    content: str | None = None
    tags: list[str] | None = None


def _classify(draft: Any, kind: CreationKind, name: str) -> str:
    """``create`` | ``update`` | ``conflict`` | ``done`` for ``name``."""
    if draft.status == "created":
        return "done"
    if not kind.name_in_use(name):
        return "create"
    if CreationDraftStore().created_by_session(draft.session_id, kind.key, name):
        return "update"
    return "conflict"


def _load_draft(draft_id: str) -> tuple[Any, CreationKind]:
    try:
        draft = CreationDraftStore().get(draft_id)
    except ValueError:
        draft = None
    if draft is None:
        raise HTTPException(status_code=404, detail="Creation draft not found")
    kind = get_creation_kind(draft.kind)
    if kind is None:
        # The kind this draft was authored under is no longer registered.
        raise HTTPException(status_code=404, detail="Creation draft not found")
    return draft, kind


@router.get("/drafts/{draft_id}")
async def get_creation_draft(draft_id: str) -> dict[str, Any]:
    draft, kind = _load_draft(draft_id)
    return {"draft": draft.to_dict(), "approval": _classify(draft, kind, draft.name)}


@router.post("/drafts/{draft_id}/approve")
async def approve_creation_draft(draft_id: str, payload: ApproveCreationRequest) -> dict[str, Any]:
    lock = await _get_approve_lock(draft_id)
    async with lock:
        return await _approve_creation_draft(draft_id, payload)


async def _approve_creation_draft(
    draft_id: str,
    payload: ApproveCreationRequest,
) -> dict[str, Any]:
    store = CreationDraftStore()
    draft, kind = _load_draft(draft_id)

    if draft.status == "created":
        return {
            "draft": draft.to_dict(),
            "saved_name": draft.created_name,
            "replaced": draft.replaced,
            "already_created": True,
            "href": kind.href,
        }

    edits = payload.model_dump(exclude_none=True)
    fields = {
        "name": edits.get("name", draft.name),
        "description": edits.get("description", draft.description),
        "content": edits.get("content", draft.content),
        "tags": edits.get("tags", draft.tags),
        # References are not editable through Approve; only re-validated.
        "references": [dict(reference) for reference in draft.references],
    }
    try:
        normalized = kind.normalize(fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    name = normalized["name"]
    replace = kind.name_in_use(name)
    if replace and not store.created_by_session(draft.session_id, kind.key, name):
        raise HTTPException(
            status_code=409,
            detail=f"A {kind.label.lower()} named “{name}” already exists. Rename the draft.",
        )

    draft.name = name
    draft.description = normalized["description"]
    draft.content = normalized["content"]
    draft.tags = normalized.get("tags") or []
    draft.references = normalized.get("references") or draft.references

    try:
        saved_name = kind.publish(draft, replace=replace)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP status below
        mapped = _map_publish_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise

    store.mark_created(draft, created_name=saved_name, replaced=replace)
    return {
        "draft": draft.to_dict(),
        "saved_name": saved_name,
        "replaced": replace,
        "already_created": False,
        "href": kind.href,
    }


def _map_publish_error(exc: Exception) -> HTTPException | None:
    """Known Skill/Persona service errors to HTTP status; ``None`` to re-raise."""
    from deeptutor.services.persona import PersonaExistsError, PersonaNotFoundError
    from deeptutor.services.skill.service import (
        SkillExistsError,
        SkillImportError,
        SkillNotFoundError,
        SkillReadOnlyError,
    )

    if isinstance(exc, (SkillExistsError, PersonaExistsError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc,
        (
            SkillImportError,
            SkillNotFoundError,
            SkillReadOnlyError,
            PersonaNotFoundError,
            ValueError,
        ),
    ):
        return HTTPException(status_code=400, detail=str(exc))
    return None


__all__ = ["router"]
