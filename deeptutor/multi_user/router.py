"""Admin APIs for the optional multi-user layer."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool

from deeptutor.api.routers.auth import require_admin
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import get_reading_extension_registry
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.skill.service import SkillService

from .audit import log_admin_action
from .book_permission import BookDefaultLevel, BookPermission, BookPermissionLevel
from .grants import load_grant, normalize_grant, save_grant, validate_grant
from .identity import get_user_by_id, list_user_info, set_book_permission
from .knowledge_access import admin_kb_base_dir
from .model_access import is_owner_bound
from .paths import get_admin_path_service, get_path_service_for_scope, scope_for_user

router = APIRouter()


class GrantPayload(BaseModel):
    grant: dict[str, Any]


class BookPermissionPayload(BaseModel):
    create: StrictBool = True
    default: BookDefaultLevel = "none"
    books: dict[str, BookPermissionLevel] = Field(default_factory=dict)


class SkillInstallPayload(BaseModel):
    ref: str
    name: str | None = None
    force: bool = False
    allow_unverified: bool = False


def _admin_catalog_summary() -> dict[str, list[dict[str, Any]]]:
    catalog = ModelCatalogService(
        path=get_admin_path_service().get_settings_file("model_catalog")
    ).load()
    out: dict[str, list[dict[str, Any]]] = {"llm": []}
    for service, state in (catalog.get("services") or {}).items():
        if service not in out:
            continue
        for profile in state.get("profiles", []) or []:
            if is_owner_bound(profile):
                # Bound to one person's OAuth identity, so it is not assignable.
                # Listing it here would offer admins a grant the server drops.
                continue
            profile_id = str(profile.get("id") or "")
            models = []
            for model in profile.get("models", []) or []:
                models.append(
                    {
                        "model_id": model.get("id", ""),
                        "name": model.get("name") or model.get("model") or model.get("id"),
                        "model": model.get("model", ""),
                    }
                )
            out[service].append(
                {
                    "profile_id": profile_id,
                    "name": profile.get("name") or profile_id,
                    "models": models,
                }
            )
    return out


def _admin_kb_summary() -> list[dict[str, Any]]:
    manager = KnowledgeBaseManager(base_dir=str(admin_kb_base_dir()))
    return [
        {
            "resource_id": f"admin:kb:{name}",
            "name": name,
            "source": "admin",
        }
        for name in manager.list_knowledge_bases()
    ]


def _admin_skill_summary() -> list[dict[str, Any]]:
    root = get_admin_path_service().get_workspace_dir() / "skills"
    service = SkillService(root=root)
    return [item.to_dict() for item in service.list_skills()]


def _admin_partner_summary() -> list[dict[str, Any]]:
    """The partners an admin can assign. Partners are process-wide resources
    anchored at the admin workspace, so this lists them all (identity only — no
    channel wiring or model selection leaks into the assignable summary)."""
    from deeptutor.services.partners import get_partner_manager

    return [
        {
            "partner_id": str(item.get("partner_id") or ""),
            "name": item.get("name") or item.get("partner_id") or "",
            "description": item.get("description") or "",
            "emoji": item.get("emoji") or "",
        }
        for item in get_partner_manager().list_partners()
    ]


def _reading_root(service: Any) -> Path:
    return service.get_workspace_feature_dir("reading")


def _admin_reading_summary() -> list[dict[str, Any]]:
    store = ReadingStore(_reading_root(get_admin_path_service()))
    return [manifest.to_dict() for manifest in store.list_materials()]


def _stage_assigned_materials(user_id: str, grant: dict[str, Any]) -> None:
    """Copy newly assigned admin books; never delete learner-owned state."""
    policy = grant.get("learning_policy")
    reading = policy.get("reading") if isinstance(policy, dict) else None
    if not isinstance(reading, dict):
        return
    material_ids = set(reading.get("material_ids") or [])
    material_ids.discard("*")
    if not material_ids:
        return
    admin_root = _reading_root(get_admin_path_service())
    admin_store = ReadingStore(admin_root)
    user_service = get_path_service_for_scope(scope_for_user(user_id, is_admin=False))
    target_root = _reading_root(user_service)
    target_root.mkdir(parents=True, exist_ok=True)
    for material_id in sorted(material_ids):
        try:
            admin_store.manifest(material_id)
        except Exception as exc:
            raise ValueError(f"Unknown admin reading material: {material_id}") from exc
        target = target_root / material_id
        if target.exists():
            continue
        stage = target_root / f".{material_id}.{uuid.uuid4().hex[:8]}.staging"
        try:
            shutil.copytree(admin_root / material_id, stage)
            os.replace(stage, target)
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def _require_assignable_user(user_id: str) -> tuple[str, dict[str, Any]]:
    user_record = get_user_by_id(user_id)
    if user_record is None:
        raise HTTPException(status_code=404, detail="User not found")
    username, record = user_record
    if str(record.get("role") or "user") == "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin users use the main workspace and cannot receive assignments.",
        )
    return username, record


@router.get("/admin/resources")
async def admin_resources(_: object = Depends(require_admin)) -> dict[str, Any]:
    """Everything an admin can assign to a user: models, KBs, skills, and
    the tool surface (system tools + MCP tools, same pool partners use)."""
    from deeptutor.api.utils.tool_options import build_tool_options

    tool_options = await build_tool_options()
    return {
        "models": _admin_catalog_summary(),
        "knowledge_bases": _admin_kb_summary(),
        "skills": _admin_skill_summary(),
        "partners": _admin_partner_summary(),
        "reading_materials": _admin_reading_summary(),
        "reading_extensions": [
            extension.manifest.model_dump()
            for extension in get_reading_extension_registry().all()
        ],
        "tools": tool_options["tools"],
        "mcp_tools": tool_options["mcp_tools"],
    }


@router.get("/admin/books")
async def admin_books(_: object = Depends(require_admin)) -> dict[str, Any]:
    from .book_access import admin_book_catalog

    return {"books": admin_book_catalog()}


@router.get("/users/{user_id}/grants")
async def get_user_grants(user_id: str, _: object = Depends(require_admin)) -> dict[str, Any]:
    _require_assignable_user(user_id)
    return {"grant": load_grant(user_id)}


@router.put("/users/{user_id}/grants")
async def put_user_grants(
    user_id: str,
    payload: GrantPayload,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    _require_assignable_user(user_id)
    try:
        normalized = normalize_grant(user_id, payload.grant)
        validate_grant(normalized)
        _stage_assigned_materials(user_id, normalized)
        grant = save_grant(user_id, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        "grant_set",
        target_user_id=user_id,
        summary={
            "model_count": len(grant.get("models", {}).get("llm", []) or []),
            "kb_count": len(grant.get("knowledge_bases", []) or []),
            "skill_count": len(grant.get("skills", []) or []),
            "partner_count": len(grant.get("partners", []) or []),
            "enabled_tools": grant.get("enabled_tools"),
            "mcp_tool_count": (
                None if grant.get("mcp_tools") is None else len(grant.get("mcp_tools") or [])
            ),
            "exec_enabled": grant.get("exec_enabled"),
            "learning_policy": grant.get("learning_policy"),
        },
    )
    return {"grant": grant}


@router.get("/users/{user_id}/book-permission")
async def get_user_book_permission(
    user_id: str,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    from .book_permission import normalize_book_permission, public_permission_dict

    _, record = _require_assignable_user(user_id)
    return {
        "permission": public_permission_dict(
            normalize_book_permission(record.get("book_permission"))
        )
    }


@router.put("/users/{user_id}/book-permission")
async def put_user_book_permission(
    user_id: str,
    payload: BookPermissionPayload,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    from .book_access import shared_book_exists
    from .book_permission import public_permission_dict

    username, _record = _require_assignable_user(user_id)
    unknown = sorted(book_id for book_id in payload.books if not shared_book_exists(book_id))
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown book id: {unknown[0]}")
    permission = BookPermission(
        create=bool(payload.create),
        default=payload.default,
        books=tuple(payload.books.items()),
    )
    if not set_book_permission(username, permission):
        raise HTTPException(status_code=404, detail="User not found")
    result = public_permission_dict(permission)
    log_admin_action(
        "book_permission_set",
        target_user_id=user_id,
        summary={
            "create": permission.create,
            "default": permission.default,
            "book_count": len(permission.books),
        },
    )
    return {"permission": result}


@router.post("/admin/skills/install")
async def admin_install_skill(
    payload: SkillInstallPayload,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    """Install a hub skill into the admin catalog (``<hub>:<slug>[@version]``).

    The skill lands in the admin workspace — the same pool ``/admin/resources``
    lists — so it stays invisible to non-admin users until a grant assigns it.
    The install pipeline (verdict gate, safe extraction, ``always`` stripping)
    lives in :func:`deeptutor.services.skill.hub.install_from_hub`; this
    endpoint only chooses the target root and audits the action.
    """
    from deeptutor.services.skill.hub import HubError, install_from_hub
    from deeptutor.services.skill.service import (
        InvalidSkillNameError,
        SkillExistsError,
        SkillImportError,
    )

    service = SkillService(root=get_admin_path_service().get_workspace_dir() / "skills")
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
        raise HTTPException(status_code=409, detail=f"Skill already exists: {exc}") from exc
    except (SkillImportError, InvalidSkillNameError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_admin_action(
        "skill_hub_install",
        summary={
            "ref": payload.ref,
            "installed_as": outcome.result.info.name,
            "version": outcome.ref.version,
            "verdict": outcome.verdict.status,
            "forced": payload.force,
            "allow_unverified": payload.allow_unverified,
        },
    )
    return {
        "skill": outcome.result.info.to_dict(),
        "verdict": {"status": outcome.verdict.status, "detail": outcome.verdict.detail},
        "version": outcome.ref.version,
        "skipped": [{"path": rel, "reason": reason} for rel, reason in outcome.result.skipped],
    }


@router.get("/users")
async def multi_user_list_users(_: object = Depends(require_admin)) -> dict[str, Any]:
    return {"users": list_user_info()}
