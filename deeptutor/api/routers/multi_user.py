"""Admin APIs for the optional multi-user layer."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import os
from pathlib import Path
import shutil
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool, field_validator

from deeptutor.api.routers.auth import require_admin, require_auth
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.multi_user.audit import log_admin_action, log_guardian_action
from deeptutor.multi_user.book_permission import (
    BookDefaultLevel,
    BookPermission,
    BookPermissionLevel,
)
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.device_credentials import revoke_device_credentials_for_user
from deeptutor.multi_user.grants import (
    LEARNING_AGE_BANDS,
    LEARNING_SURFACES,
    learner_grant,
    load_grant,
    normalize_grant,
    save_grant,
    validate_grant,
)
from deeptutor.multi_user.guardians import (
    GUARDIAN_PERMISSIONS,
    authorize_guardian,
    guardian_can_access,
    list_relationships,
    relationship_by_id,
    revoke_guardian,
)
from deeptutor.multi_user.identity import (
    get_user_by_id,
    list_user_info,
    set_book_permission,
    set_password,
)
from deeptutor.multi_user.knowledge_access import admin_kb_base_dir
from deeptutor.multi_user.model_access import is_owner_bound
from deeptutor.multi_user.paths import (
    get_admin_path_service,
    get_path_service_for_scope,
    scope_for_user,
)
from deeptutor.reading import ReadingStore
from deeptutor.reading.extensions import get_reading_extension_registry
from deeptutor.services.auth import POCKETBASE_ENABLED, hash_password
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.skill.service import SkillService

router = APIRouter()


class GrantPayload(BaseModel):
    grant: dict[str, Any]


class BookPermissionPayload(BaseModel):
    create: StrictBool = True
    default: BookDefaultLevel = "none"
    books: dict[str, BookPermissionLevel] = Field(default_factory=dict)


class GuardianAuthorizationPayload(BaseModel):
    guardian_user_id: str = Field(min_length=1, max_length=64)
    learner_user_id: str = Field(min_length=1, max_length=64)
    permissions: list[str] = Field(default_factory=lambda: sorted(GUARDIAN_PERMISSIONS))

    @field_validator("permissions")
    @classmethod
    def permissions_valid(cls, value: list[str]) -> list[str]:
        permissions = sorted(set(value))
        if not permissions or not set(permissions).issubset(GUARDIAN_PERMISSIONS):
            raise ValueError("Unknown guardian permission")
        return permissions


class GuardianMaterialsPayload(BaseModel):
    book_ids: list[str]

    @field_validator("book_ids")
    @classmethod
    def book_ids_valid(cls, value: list[str]) -> list[str]:
        book_ids: list[str] = []
        for raw_id in value:
            book_id = raw_id.strip()
            if not book_id:
                raise ValueError("Book ids cannot be empty")
            if book_id not in book_ids:
                book_ids.append(book_id)
        return book_ids


class GuardianRestrictionsPayload(BaseModel):
    age_band: str
    allow_upload: StrictBool
    allowed_surfaces: list[str]
    extensions: list[str]

    @field_validator("age_band")
    @classmethod
    def age_band_valid(cls, value: str) -> str:
        if value not in LEARNING_AGE_BANDS:
            raise ValueError("Unknown learning age band")
        return value

    @field_validator("allowed_surfaces")
    @classmethod
    def surfaces_valid(cls, value: list[str]) -> list[str]:
        surfaces = list(dict.fromkeys(value))
        if not surfaces or not set(surfaces).issubset(LEARNING_SURFACES):
            raise ValueError("Unknown or empty learning surface")
        return surfaces

    @field_validator("extensions")
    @classmethod
    def extensions_valid(cls, value: list[str]) -> list[str]:
        extensions: list[str] = []
        for raw_id in value:
            extension_id = raw_id.strip()
            if not extension_id:
                raise ValueError("Reading extension ids cannot be empty")
            if extension_id not in extensions:
                extensions.append(extension_id)
        return extensions


class GuardianCredentialResetPayload(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


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
    """The partners an admin can hand to someone else.

    Admin-managed partners only — the ones with no owner, or that the admin
    created. A partner someone built for themselves is theirs to share or not;
    listing it here would let an admin lend out a private companion (and its
    soul, which people write personally) by a single click. Identity only: no
    channel wiring or model selection leaks into the assignable summary.
    """
    from deeptutor.services.partners import get_partner_manager

    admin_id = get_current_user().id
    return [
        {
            "partner_id": str(item.get("partner_id") or ""),
            "name": item.get("name") or item.get("partner_id") or "",
            "description": item.get("description") or "",
            "emoji": item.get("emoji") or "",
        }
        for item in get_partner_manager().list_partners()
        if str(item.get("owner_id") or "") in ("", admin_id)
    ]


def _reading_root(service: Any) -> Path:
    return service.get_workspace_feature_dir("reading")


def _admin_reading_summary() -> list[dict[str, Any]]:
    store = ReadingStore(_reading_root(get_admin_path_service()))
    return [manifest.to_dict() for manifest in store.list_materials()]


def _stage_assigned_materials(user_id: str, grant: dict[str, Any]) -> None:
    """Copy newly assigned admin books without touching learner-owned state."""
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


def _validate_reading_policy(grant: dict[str, Any]) -> None:
    policy = grant.get("learning_policy")
    reading = policy.get("reading") if isinstance(policy, dict) else None
    if not isinstance(reading, dict):
        return
    allowed_extensions = {
        extension.manifest.id for extension in get_reading_extension_registry().all()
    }
    unknown = sorted(set(reading.get("extensions") or []) - allowed_extensions)
    if unknown:
        raise ValueError(f"Unknown reading extensions: {', '.join(unknown)}")


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


def _users_by_id() -> dict[str, dict[str, Any]]:
    return {str(user.get("id") or ""): user for user in list_user_info()}


def _relationship_view(
    relationship: dict[str, Any], users: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    guardian = users.get(relationship["guardian_user_id"], {})
    learner = users.get(relationship["learner_user_id"], {})
    return {
        **relationship,
        "guardian_username": str(guardian.get("username") or ""),
        "learner_username": str(learner.get("username") or ""),
    }


def _require_guardian_access(
    current: object, learner_user_id: str, permission: str
) -> tuple[str, dict[str, Any], str, bool]:
    actor_user_id = str(getattr(current, "user_id", "") or "")
    learner_username, learner_record = _require_assignable_user(learner_user_id)
    is_admin = str(getattr(current, "role", "") or "") == "admin"
    if is_admin:
        return learner_username, learner_record, actor_user_id, True
    _guardian_username, _guardian_record = _require_assignable_user(actor_user_id)
    if not guardian_can_access(actor_user_id, learner_user_id, permission):
        raise HTTPException(status_code=403, detail="Guardian authorization required")
    return learner_username, learner_record, actor_user_id, False


def _log_supervisor_action(
    action: str,
    *,
    actor_user_id: str,
    learner_user_id: str,
    is_admin: bool,
    summary: dict[str, Any] | None = None,
) -> None:
    if is_admin:
        log_admin_action(action, target_user_id=learner_user_id, summary=summary)
        return
    log_guardian_action(
        action,
        guardian_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        summary=summary,
    )


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
            extension.manifest.model_dump() for extension in get_reading_extension_registry().all()
        ],
        "tools": tool_options["tools"],
        "mcp_tools": tool_options["mcp_tools"],
    }


@router.get("/admin/books")
async def admin_books(_: object = Depends(require_admin)) -> dict[str, Any]:
    from deeptutor.multi_user.book_access import admin_book_catalog

    return {"books": admin_book_catalog()}


@router.get("/guardians")
async def list_guardian_relationships(
    include_revoked: bool = False,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    users = _users_by_id()
    relationships = [
        _relationship_view(relationship, users)
        for relationship in list_relationships(include_revoked=include_revoked)
    ]
    return {"relationships": relationships}


@router.post("/guardians", status_code=201)
async def authorize_guardian_relationship(
    payload: GuardianAuthorizationPayload,
    current: object = Depends(require_admin),
) -> dict[str, Any]:
    _require_assignable_user(payload.guardian_user_id)
    _require_assignable_user(payload.learner_user_id)
    try:
        relationship = authorize_guardian(
            payload.guardian_user_id,
            payload.learner_user_id,
            payload.permissions,
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 409 if "already authorized" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    log_admin_action(
        "guardian_authorize",
        target_user_id=payload.learner_user_id,
        summary={
            "relationship_id": relationship["id"],
            "guardian_user_id": payload.guardian_user_id,
            "permissions": relationship["permissions"],
        },
    )
    return {
        "relationship": _relationship_view(relationship, _users_by_id()),
        "actor_username": str(getattr(current, "username", "") or ""),
    }


@router.delete("/guardians/{relationship_id}")
async def revoke_guardian_relationship(
    relationship_id: str,
    current: object = Depends(require_admin),
) -> dict[str, Any]:
    revoked_by = str(getattr(current, "user_id", "") or "")
    relationship = revoke_guardian(relationship_id, revoked_by=revoked_by)
    if relationship is None:
        raise HTTPException(status_code=404, detail="Guardian relationship not found")
    log_admin_action(
        "guardian_revoke",
        target_user_id=relationship["learner_user_id"],
        summary={
            "relationship_id": relationship["id"],
            "guardian_user_id": relationship["guardian_user_id"],
        },
    )
    return {
        "relationship": _relationship_view(relationship, _users_by_id()),
        "ok": True,
    }


@router.get("/me/guardianships")
async def my_guardianships(
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    guardian_user_id = str(getattr(current, "user_id", "") or "")
    _require_assignable_user(guardian_user_id)
    users = _users_by_id()
    relationships = [
        _relationship_view(relationship, users)
        for relationship in list_relationships(guardian_user_id=guardian_user_id)
    ]
    return {"relationships": relationships}


@router.delete("/me/guardianships/{relationship_id}")
async def revoke_my_guardianship(
    relationship_id: str,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    guardian_user_id = str(getattr(current, "user_id", "") or "")
    _require_assignable_user(guardian_user_id)
    relationship = relationship_by_id(relationship_id)
    if (
        relationship is None
        or relationship["guardian_user_id"] != guardian_user_id
        or relationship["revoked_at"] is not None
    ):
        raise HTTPException(status_code=404, detail="Active guardian relationship not found")
    revoked = revoke_guardian(relationship_id, revoked_by=guardian_user_id, reason="self_revoked")
    assert revoked is not None
    log_guardian_action(
        "guardian_self_revoke",
        guardian_user_id=guardian_user_id,
        learner_user_id=relationship["learner_user_id"],
        summary={"relationship_id": relationship_id},
    )
    return {"relationship": _relationship_view(revoked, _users_by_id()), "ok": True}


@router.get("/learners/{learner_user_id}/guardian-report")
async def guardian_report(
    learner_user_id: str,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "view_reports"
    )
    from deeptutor.multi_user.book_access import admin_book_catalog
    from deeptutor.multi_user.book_permission import (
        normalize_book_permission,
        public_permission_dict,
    )

    permission = normalize_book_permission(learner_record.get("book_permission"))
    permission_dict = public_permission_dict(permission)
    assigned_materials = [
        {**book, "permission": permission.level_for(book["book_id"])}
        for book in admin_book_catalog()
        if permission.level_for(book["book_id"]) != "none"
    ]
    grant = load_grant(learner_user_id)
    _log_supervisor_action(
        "guardian_report_view",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={"assigned_material_count": len(assigned_materials)},
    )
    return {
        "learner": {
            "id": learner_user_id,
            "username": learner_username,
            "disabled": bool(learner_record.get("disabled", False)),
        },
        "book_permission": permission_dict,
        "assigned_materials": assigned_materials,
        "grant_summary": {
            "model_count": len(grant.get("models", {}).get("llm", []) or []),
            "knowledge_base_count": len(grant.get("knowledge_bases") or []),
            "skill_count": len(grant.get("skills") or []),
            "enabled_tools": grant.get("enabled_tools"),
        },
    }


@router.get("/learners/{learner_user_id}/materials")
async def guardian_material_catalog(
    learner_user_id: str,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    _learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "assign_materials"
    )
    from deeptutor.multi_user.book_access import admin_book_catalog
    from deeptutor.multi_user.book_permission import normalize_book_permission

    permission = normalize_book_permission(learner_record.get("book_permission"))
    materials = [
        {
            **book,
            "assigned": permission.level_for(book["book_id"]) != "none",
            "permission": permission.level_for(book["book_id"]),
        }
        for book in admin_book_catalog()
    ]
    _log_supervisor_action(
        "guardian_material_catalog_view",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={"material_count": len(materials)},
    )
    return {"materials": materials}


@router.put("/learners/{learner_user_id}/materials")
async def assign_guardian_materials(
    learner_user_id: str,
    payload: GuardianMaterialsPayload,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "assign_materials"
    )
    from deeptutor.multi_user.book_access import admin_book_catalog
    from deeptutor.multi_user.book_permission import (
        BookPermission,
        normalize_book_permission,
        public_permission_dict,
    )

    catalog = admin_book_catalog()
    catalog_ids = {book["book_id"] for book in catalog}
    unknown = next((book_id for book_id in payload.book_ids if book_id not in catalog_ids), None)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown approved book id: {unknown}")

    # Guardians hand out the admin-approved catalogue as read-only material.
    # Admins remain the only source of edit/create capability.
    existing = normalize_book_permission(learner_record.get("book_permission"))
    selected_ids = set(payload.book_ids)
    permission = BookPermission(
        create=existing.create,
        default=existing.default,
        books=tuple(
            (book["book_id"], "read" if book["book_id"] in selected_ids else "none")
            for book in catalog
            if (book["book_id"] in selected_ids) != (existing.default == "read")
        ),
    )
    if not set_book_permission(learner_username, permission):
        raise HTTPException(status_code=404, detail="User not found")
    result = public_permission_dict(permission)
    _log_supervisor_action(
        "guardian_material_assign",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={"book_ids": payload.book_ids, "read_only": True},
    )
    return {"book_permission": result}


def _guardian_restrictions(grant: dict[str, Any]) -> dict[str, Any]:
    policy = grant.get("learning_policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=409, detail="Learner account has no learning policy")
    reading = policy.get("reading") if isinstance(policy.get("reading"), dict) else {}
    return {
        "age_band": policy.get("age_band"),
        "allow_upload": bool(reading.get("allow_upload", False)),
        "allowed_surfaces": list(policy.get("allowed_surfaces") or ["chat", "reading"]),
        "extensions": list(reading.get("extensions") or []),
    }


def _restriction_grant(learner_user_id: str, learner_record: dict[str, Any]) -> dict[str, Any]:
    grant = load_grant(learner_user_id)
    if grant.get("learning_policy") is None and learner_record.get("preset") == "learner":
        return learner_grant(learner_user_id)
    return grant


@router.get("/learners/{learner_user_id}/restrictions")
async def get_guardian_restrictions(
    learner_user_id: str,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    _learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "manage_restrictions"
    )
    restrictions = _guardian_restrictions(_restriction_grant(learner_user_id, learner_record))
    _log_supervisor_action(
        "guardian_restrictions_view",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
    )
    return {
        "restrictions": restrictions,
        "available_extensions": [
            extension.manifest.model_dump() for extension in get_reading_extension_registry().all()
        ],
    }


@router.put("/learners/{learner_user_id}/restrictions")
async def put_guardian_restrictions(
    learner_user_id: str,
    payload: GuardianRestrictionsPayload,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    _learner_username, learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "manage_restrictions"
    )
    available_extensions = {
        extension.manifest.id for extension in get_reading_extension_registry().all()
    }
    unknown_extensions = sorted(set(payload.extensions) - available_extensions)
    if unknown_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown reading extensions: {', '.join(unknown_extensions)}",
        )
    grant = deepcopy(_restriction_grant(learner_user_id, learner_record))
    policy = grant.get("learning_policy")
    if not isinstance(policy, dict):
        raise HTTPException(status_code=409, detail="Learner account has no learning policy")
    reading = policy.get("reading")
    if not isinstance(reading, dict):
        reading = {}
        policy["reading"] = reading
    policy["age_band"] = payload.age_band
    policy["allowed_surfaces"] = payload.allowed_surfaces
    reading["allow_upload"] = payload.allow_upload
    reading["extensions"] = payload.extensions
    try:
        grant = normalize_grant(learner_user_id, grant)
        validate_grant(grant)
        _validate_reading_policy(grant)
        grant = save_grant(learner_user_id, grant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    restrictions = _guardian_restrictions(grant)
    _log_supervisor_action(
        "guardian_restrictions_set",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary=restrictions,
    )
    return {"restrictions": restrictions}


@router.post("/learners/{learner_user_id}/credentials/reset")
async def reset_learner_credentials(
    learner_user_id: str,
    payload: GuardianCredentialResetPayload,
    current: object = Depends(require_auth),
) -> dict[str, Any]:
    learner_username, _learner_record, actor_user_id, is_admin = _require_guardian_access(
        current, learner_user_id, "reset_credentials"
    )
    if POCKETBASE_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="Guardian credential reset requires built-in local authentication.",
        )
    revoked_devices = revoke_device_credentials_for_user(
        learner_user_id,
        revoked_by=actor_user_id,
    )
    if set_password(learner_username, hash_password(payload.new_password)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    _log_supervisor_action(
        "guardian_credential_reset",
        actor_user_id=actor_user_id,
        learner_user_id=learner_user_id,
        is_admin=is_admin,
        summary={
            "credential_reset": True,
            "device_credentials_revoked": revoked_devices,
        },
    )
    return {"ok": True, "device_credentials_revoked": revoked_devices}


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
    user_record = _require_assignable_user(user_id)
    try:
        grant = normalize_grant(user_id, payload.grant)
        if (
            str(user_record[1].get("preset") or "standard") == "learner"
            and grant.get("learning_policy") is None
        ):
            raise ValueError("Learner accounts must retain a learning policy.")
        validate_grant(grant)
        _validate_reading_policy(grant)
        _stage_assigned_materials(user_id, grant)
        grant = save_grant(user_id, grant)
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
    from deeptutor.multi_user.book_permission import (
        normalize_book_permission,
        public_permission_dict,
    )

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
    from deeptutor.multi_user.book_access import shared_book_exists
    from deeptutor.multi_user.book_permission import public_permission_dict

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
