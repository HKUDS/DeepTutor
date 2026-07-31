"""Admin APIs for the optional multi-user layer."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deeptutor.api.routers.auth import require_admin
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.config import get_runtime_settings_service
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.skill.service import SkillService

from .audit import log_admin_action
from .grants import load_grant, merge_grant_update, save_grant
from .identity import get_user_by_id, list_user_info
from .knowledge_access import admin_kb_base_dir
from .model_access import is_owner_bound
from .paths import get_admin_path_service
from .quota_config import DEFAULT_QUOTA, normalize_quotas

router = APIRouter()


class GrantPayload(BaseModel):
    grant: dict[str, Any]


class SkillInstallPayload(BaseModel):
    ref: str
    name: str | None = None
    force: bool = False
    allow_unverified: bool = False


class DefaultTokenQuotaPayload(BaseModel):
    """Accept the new resource shape plus legacy LLM-only fields."""

    daily_tokens: Any | None = None
    monthly_tokens: Any | None = None
    default_token_quota: dict[str, Any] | None = None
    default_quota: dict[str, Any] | None = None


def _read_default_quota() -> dict[str, dict[str, int]]:
    settings = get_runtime_settings_service().load_auth(include_process_overrides=False)
    return normalize_quotas(
        settings.get("default_quota"),
        fallback=DEFAULT_QUOTA,
        legacy_token_quota=settings.get("default_token_quota"),
    )


def _read_default_token_quota() -> dict[str, int]:
    """Backward-compatible read helper for old callers/tests."""
    return dict(_read_default_quota()["llm"])


def _quota_payload_values(payload: DefaultTokenQuotaPayload) -> dict[str, Any]:
    values = dict(payload.default_quota or {})
    if not values and payload.default_token_quota is not None:
        values["llm"] = dict(payload.default_token_quota)
    llm = values.get("llm")
    if not isinstance(llm, dict):
        llm = {}
        values["llm"] = llm
    if payload.daily_tokens is not None:
        llm["daily_tokens"] = payload.daily_tokens
    if payload.monthly_tokens is not None:
        llm["monthly_tokens"] = payload.monthly_tokens
    return values


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
        "tools": tool_options["tools"],
        "mcp_tools": tool_options["mcp_tools"],
    }


@router.get("/admin/default-quota")
async def get_default_token_quota(_: object = Depends(require_admin)) -> dict[str, Any]:
    """Return resource defaults plus the legacy LLM-only alias."""
    quota = _read_default_quota()
    return {
        "default_quota": quota,
        "default_token_quota": dict(quota["llm"]),
    }


@router.put("/admin/default-quota")
async def put_default_token_quota(
    payload: DefaultTokenQuotaPayload,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    """Persist new-user defaults while preserving the rest of auth.json."""
    service = get_runtime_settings_service()
    settings = service.load_auth(include_process_overrides=False)
    current_quota = normalize_quotas(
        settings.get("default_quota"),
        fallback=DEFAULT_QUOTA,
        legacy_token_quota=settings.get("default_token_quota"),
    )
    quota = normalize_quotas(
        _quota_payload_values(payload),
        fallback=current_quota,
        legacy_token_quota=current_quota["llm"],
    )
    settings["default_quota"] = quota
    settings["default_token_quota"] = dict(quota["llm"])
    saved = service.save_auth(settings)
    saved_quota = normalize_quotas(
        saved.get("default_quota"),
        fallback=DEFAULT_QUOTA,
        legacy_token_quota=saved.get("default_token_quota"),
    )
    log_admin_action(
        "default_token_quota_set",
        summary={
            "quota": saved_quota,
        },
    )
    return {
        "default_quota": saved_quota,
        "default_token_quota": dict(saved_quota["llm"]),
    }


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
        grant = save_grant(
            user_id,
            merge_grant_update(user_id, load_grant(user_id), payload.grant),
        )
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
            "quota": grant.get("quota"),
        },
    )
    return {"grant": grant}


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
