"""
Skills API Router
=================

CRUD endpoints for user-authored SKILL.md files stored under
``data/user/workspace/skills/<name>/SKILL.md``.

Mounted at ``/api/v1/skills``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.skill_access import (
    assert_skill_allowed,
    assigned_skill_detail,
    assigned_skill_ids,
    assigned_skill_infos,
)
from deeptutor.services.skill import get_skill_service
from deeptutor.services.skill.service import (
    InvalidSkillNameError,
    InvalidTagError,
    SkillExistsError,
    SkillNotFoundError,
    TagExistsError,
    TagNotFoundError,
)

router = APIRouter()


class CreateSkillRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)


class UpdateSkillRequest(BaseModel):
    description: str | None = None
    content: str | None = None
    rename_to: str | None = None
    tags: list[str] | None = None


class CreateTagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)


class RenameTagRequest(BaseModel):
    rename_to: str = Field(..., min_length=1, max_length=32)


# ── tag routes (declared before `/{name}` so they are not shadowed) ──


@router.get("/tags/list")
async def list_tags() -> dict[str, list[str]]:
    service = get_skill_service()
    return {"tags": service.list_tags()}


@router.post("/tags/create")
async def create_tag(payload: CreateTagRequest) -> dict[str, str]:
    service = get_skill_service()
    try:
        tag = service.create_tag(payload.name)
    except TagExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Tag already exists: {exc}")
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": tag}


@router.put("/tags/{tag}")
async def rename_tag(tag: str, payload: RenameTagRequest) -> dict[str, str]:
    service = get_skill_service()
    try:
        new_tag = service.rename_tag(tag, payload.rename_to)
    except TagNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tag not found: {tag}")
    except TagExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Tag already exists: {exc}")
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": new_tag}


@router.delete("/tags/{tag}")
async def delete_tag(tag: str) -> dict[str, str]:
    service = get_skill_service()
    try:
        service.delete_tag(tag)
    except TagNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tag not found: {tag}")
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "deleted", "name": tag}


# ── skill routes ───────────────────────────────────────────────────


@router.get("/list")
async def list_skills() -> dict[str, list[dict[str, object]]]:
    service = get_skill_service()
    own_items = [info.to_dict() for info in service.list_skills()]
    user = get_current_user()
    if user.is_admin:
        return {"skills": own_items}
    own_names = {item.get("name") for item in own_items}
    merged = list(own_items)
    for assigned in assigned_skill_infos(user.id):
        if assigned.get("name") in own_names:
            continue
        merged.append(assigned)
    return {"skills": merged}


@router.get("/{name}")
async def get_skill(name: str) -> dict[str, object]:
    service = get_skill_service()
    try:
        return service.get_detail(name).to_dict()
    except SkillNotFoundError:
        # User scope doesn't have it. Fall through to admin-assigned lookup
        # below, which returns 403 if the user has no grant for it.
        pass
    except InvalidSkillNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user = get_current_user()
    if user.is_admin:
        # Admin scope already checked above; nothing else to look at.
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    if name not in assigned_skill_ids(user.id):
        raise HTTPException(status_code=403, detail="Skill is not assigned to you")
    detail = assigned_skill_detail(name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return detail


@router.post("/create")
async def create_skill(payload: CreateSkillRequest) -> dict[str, object]:
    service = get_skill_service()
    try:
        info = service.create(
            name=payload.name,
            description=payload.description,
            content=payload.content,
            tags=list(payload.tags or []),
        )
        return info.to_dict()
    except SkillExistsError:
        raise HTTPException(status_code=409, detail=f"Skill already exists: {payload.name}")
    except InvalidSkillNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{name}")
async def update_skill(name: str, payload: UpdateSkillRequest) -> dict[str, object]:
    service = get_skill_service()
    try:
        info = service.update(
            name,
            description=payload.description,
            content=payload.content,
            rename_to=payload.rename_to,
            tags=payload.tags,
        )
        return info.to_dict()
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    except SkillExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidSkillNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{name}")
async def delete_skill(name: str) -> dict[str, str]:
    service = get_skill_service()
    try:
        service.delete(name)
        return {"status": "deleted", "name": name}
    except SkillNotFoundError:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    except InvalidSkillNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
