"""
Personas API Router
===================

CRUD endpoints for user-authored PERSONA.md files stored under
``data/user/workspace/personas/<name>/PERSONA.md``.

Personas are behaviour/voice presets, not capability skills: admin-authored
personas are visible to every user as read-only deployment presets (no grant
mechanism — a persona carries no privileged workflow, only style guidance).
Users create and manage their own personas in their own workspace; a user
persona shadows an admin persona of the same name.

Mounted at ``/api/v1/personas``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.core.i18n import t
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import get_admin_path_service
from deeptutor.services.persona import (
    InvalidPersonaNameError,
    PersonaExistsError,
    PersonaNotFoundError,
    PersonaService,
    get_persona_service,
)

router = APIRouter()


class CreatePersonaRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    content: str = ""


class UpdatePersonaRequest(BaseModel):
    description: str | None = None
    content: str | None = None
    rename_to: str | None = None


def _admin_persona_service() -> PersonaService:
    return PersonaService(root=get_admin_path_service().get_workspace_dir() / "personas")


@router.get("/list")
async def list_personas() -> dict[str, list[dict[str, object]]]:
    service = get_persona_service()
    own = [info.to_dict() for info in service.list_personas()]
    user = get_current_user()
    if user.is_admin:
        return {"personas": own}
    own_names = {item["name"] for item in own}
    merged = list(own)
    for preset in _admin_persona_service().list_personas():
        if preset.name in own_names:
            continue
        entry = preset.to_dict()
        entry.update({"source": "admin", "read_only": True})
        merged.append(entry)
    return {"personas": merged}


@router.get("/{name}")
async def get_persona(name: str) -> dict[str, object]:
    service = get_persona_service()
    try:
        return service.get_detail(name).to_dict()
    except PersonaNotFoundError:
        pass
    except InvalidPersonaNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user = get_current_user()
    if not user.is_admin:
        try:
            detail = _admin_persona_service().get_detail(name).to_dict()
            detail.update({"source": "admin", "read_only": True})
            return detail
        except (PersonaNotFoundError, InvalidPersonaNameError):
            pass
    raise HTTPException(status_code=404, detail=t("api.persona_not_found", name=name))


@router.post("/create")
async def create_persona(payload: CreatePersonaRequest) -> dict[str, object]:
    service = get_persona_service()
    try:
        info = service.create(
            name=payload.name,
            description=payload.description,
            content=payload.content,
        )
        return info.to_dict()
    except PersonaExistsError:
        raise HTTPException(
            status_code=409,
            detail=t("api.persona_already_exists", name=payload.name),
        )
    except InvalidPersonaNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{name}")
async def update_persona(name: str, payload: UpdatePersonaRequest) -> dict[str, object]:
    service = get_persona_service()
    try:
        info = service.update(
            name,
            description=payload.description,
            content=payload.content,
            rename_to=payload.rename_to,
        )
        return info.to_dict()
    except PersonaNotFoundError:
        raise HTTPException(status_code=404, detail=t("api.persona_not_found", name=name))
    except PersonaExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidPersonaNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{name}")
async def delete_persona(name: str) -> dict[str, str]:
    service = get_persona_service()
    try:
        service.delete(name)
        return {"status": "deleted", "name": name}
    except PersonaNotFoundError:
        raise HTTPException(status_code=404, detail=t("api.persona_not_found", name=name))
    except InvalidPersonaNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
