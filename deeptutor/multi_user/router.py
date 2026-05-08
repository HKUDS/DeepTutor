"""Admin and current-user APIs for the optional multi-user layer."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deeptutor.api.routers.auth import require_admin
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.skill.service import SkillService

from .audit import log_admin_action
from .context import get_current_user
from .grants import load_grant, save_grant
from .identity import get_user_by_id, list_user_info
from .knowledge_access import admin_kb_base_dir, list_visible_knowledge_bases
from .model_access import redacted_model_access
from .paths import MULTI_USER_ROOT, get_admin_path_service, get_current_path_service
from .skill_access import assigned_skill_ids

router = APIRouter()


class GrantPayload(BaseModel):
    grant: dict[str, Any]


class SpaceAssignPayload(BaseModel):
    source: str
    target: str | None = None


def _admin_catalog_summary() -> dict[str, list[dict[str, Any]]]:
    catalog = ModelCatalogService(
        path=get_admin_path_service().get_settings_file("model_catalog")
    ).load()
    out: dict[str, list[dict[str, Any]]] = {"llm": [], "embedding": [], "search": []}
    for service, state in (catalog.get("services") or {}).items():
        if service not in out:
            continue
        for profile in state.get("profiles", []) or []:
            profile_id = str(profile.get("id") or "")
            if service == "search":
                out[service].append(
                    {
                        "profile_id": profile_id,
                        "name": profile.get("name") or profile.get("provider") or profile_id,
                        "provider": profile.get("provider", ""),
                    }
                )
                continue
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


def _safe_relative_dir(root: Path, value: str) -> Path:
    candidate = (root / str(value or "").strip()).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path escapes workspace root") from exc
    return candidate


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


@router.get("/me/access")
async def my_access() -> dict[str, Any]:
    user = get_current_user()
    return {
        "user": user.public_dict(),
        "models": {} if user.is_admin else redacted_model_access(user.id),
        "knowledge_bases": list_visible_knowledge_bases(),
        "skills": [] if user.is_admin else sorted(assigned_skill_ids(user.id)),
        "spaces": [] if user.is_admin else load_grant(user.id).get("spaces", []),
    }


@router.get("/admin/resources")
async def admin_resources(_: object = Depends(require_admin)) -> dict[str, Any]:
    return {
        "models": _admin_catalog_summary(),
        "knowledge_bases": _admin_kb_summary(),
        "skills": _admin_skill_summary(),
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
        grant = save_grant(user_id, payload.grant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_admin_action(
        "grant_set",
        target_user_id=user_id,
        summary={
            "model_count": sum(
                len(grant.get("models", {}).get(s, [])) for s in ("llm", "embedding", "search")
            ),
            "kb_count": len(grant.get("knowledge_bases", []) or []),
            "skill_count": len(grant.get("skills", []) or []),
        },
    )
    return {"grant": grant}


@router.get("/users")
async def multi_user_list_users(_: object = Depends(require_admin)) -> dict[str, Any]:
    return {"users": list_user_info()}


@router.post("/users/{user_id}/spaces/assign")
async def assign_space_template(
    user_id: str,
    payload: SpaceAssignPayload,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    _require_assignable_user(user_id)

    admin_workspace = get_admin_path_service().get_workspace_dir()
    user_workspace = (MULTI_USER_ROOT / user_id / "user" / "workspace").resolve()
    source = _safe_relative_dir(admin_workspace, payload.source)
    if not source.exists() or not source.is_dir():
        raise HTTPException(status_code=404, detail="Source space/template not found")

    target_name = payload.target or source.name
    target = _safe_relative_dir(user_workspace, target_name)
    if target.exists():
        raise HTTPException(status_code=409, detail="Target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    provenance = {
        "source": "admin",
        "source_path": payload.source,
        "assigned_by": get_current_user().username,
    }
    (target / ".deeptutor_provenance.json").write_text(
        __import__("json").dumps(provenance, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    grant = deepcopy(load_grant(user_id))
    grant.setdefault("spaces", []).append(
        {
            "space_id": target.name,
            "mode": "copy",
            "source": "admin",
            "provenance": provenance,
        }
    )
    save_grant(user_id, grant)
    log_admin_action(
        "space_assign",
        target_user_id=user_id,
        summary={"source": payload.source, "target": target.name},
    )
    return {"ok": True, "target": str(target.relative_to(user_workspace))}
