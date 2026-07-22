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
    assigned_skill_detail,
    assigned_skill_ids,
    assigned_skill_infos,
)
from deeptutor.services.skill import get_skill_service
from deeptutor.services.skill.service import (
    InvalidSkillNameError,
    InvalidTagError,
    SkillExistsError,
    SkillImportError,
    SkillNotFoundError,
    SkillReadOnlyError,
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


class InstallSkillRequest(BaseModel):
    """Install a hub skill into the caller's own skill layer.

    ``ref`` is a ``<hub>:<slug>[@version]`` reference (the bare hub prefix
    defaults to ``eduhub``). The web "import from EduHub" flow always builds an
    ``eduhub:`` ref so a spoofed bridge message can't redirect the install to an
    arbitrary registry.
    """

    ref: str = Field(..., min_length=1, max_length=256)
    name: str | None = None
    force: bool = False
    allow_unverified: bool = False


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


# ── hub browse (in-app EduHub skill browser; declared before `/{name}`) ──


@router.get("/hub/catalog")
async def hub_catalog(hub: str = "eduhub", q: str = "", limit: int = 50) -> dict[str, object]:
    """Proxy a skill hub's public catalog for the in-app browser.

    The web "Import from EduHub" panel renders these rows in DeepTutor's own
    UI — no embedded iframe, no login — so users can browse, search, and
    one-click download skills. Returns ``web_url`` (the hub's site origin) so
    the panel can offer a "view on EduHub" link out.
    """
    import asyncio

    from deeptutor.services.skill.hub import ClawHubProvider, HubError, get_hub_provider

    try:
        provider = get_hub_provider(hub)
    except HubError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not isinstance(provider, ClawHubProvider):
        raise HTTPException(status_code=400, detail=f"Hub `{hub}` does not support browsing.")
    try:
        skills = await asyncio.to_thread(provider.catalog, query=q, limit=limit)
    except HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"hub": provider.name, "web_url": provider.web_origin, "skills": skills}


@router.get("/hub/detail")
async def hub_detail(slug: str, hub: str = "eduhub") -> dict[str, object]:
    """Full metadata + SKILL.md body for one hub skill (browser detail view)."""
    import asyncio

    from deeptutor.services.skill.hub import ClawHubProvider, HubError, get_hub_provider

    try:
        provider = get_hub_provider(hub)
    except HubError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not isinstance(provider, ClawHubProvider):
        raise HTTPException(status_code=400, detail=f"Hub `{hub}` does not support browsing.")
    try:
        detail = await asyncio.to_thread(provider.detail, slug)
    except HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    detail["web_url"] = f"{provider.web_origin}/skills/{slug}"
    return detail


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


@router.post("/install")
async def install_skill(payload: InstallSkillRequest) -> dict[str, object]:
    """Import a hub skill (e.g. from EduHub) into the caller's own skill layer.

    Lands the package in the same per-user dir that ``/create`` writes to, so
    the imported skill shows up in this user's Skills list. The install gate
    (``suspicious`` verdict abort, safe extraction, ``always`` stripping)
    lives in :func:`deeptutor.services.skill.hub.install_from_hub`.
    """
    import asyncio

    from deeptutor.services.skill.hub import HubError, install_from_hub

    service = get_skill_service()
    try:
        outcome = await asyncio.to_thread(
            install_from_hub,
            payload.ref,
            service=service,
            rename_to=payload.name,
            force=payload.force,
            allow_unverified=payload.allow_unverified,
        )
    except SkillExistsError as exc:
        raise HTTPException(status_code=409, detail=f"Skill already exists: {exc}")
    except (SkillImportError, InvalidSkillNameError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "skill": outcome.result.info.to_dict(),
        "verdict": {"status": outcome.verdict.status, "detail": outcome.verdict.detail},
        "version": outcome.ref.version,
    }


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
    except SkillReadOnlyError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
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
    except SkillReadOnlyError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except InvalidSkillNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
