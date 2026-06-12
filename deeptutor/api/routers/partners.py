"""Partners management API.

A partner is an IM-connected companion driven by the chat agent loop.
This router owns: partner CRUD + lifecycle, the soul library, channel
config (schema-driven), asset provisioning (KB / skills / notebooks copied
into the partner workspace), tool configuration, history, and the web chat
entry points (HTTP / SSE / WebSocket).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from typing import Any, AsyncGenerator, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deeptutor.core.i18n import t
from deeptutor.partners.config.paths import get_partner_media_dir, resolve_owner_for_partner
from deeptutor.partners.helpers import safe_filename
from deeptutor.services.partners import get_partner_manager, slugify_partner_id
from deeptutor.services.partners.manager import (
    LEGACY_GLOBAL_DELIVERY_KEYS,
    PartnerConfig,
    PartnerInstance,
    mask_channel_secrets,
    strip_legacy_global_delivery,
)
from deeptutor.services.partners.workspace import (
    list_assets,
    provision_assets,
    read_soul,
    remove_asset,
    strip_frontmatter,
    write_soul,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Ownership 校验 ──────────────────────────────────────────────


def _check_partner_owner(partner_id: str) -> str:
    """校验当前用户是否有权操作该 partner。返回 owner_id。

    - admin 用户可以操作任意 partner
    - 普通用户只能操作 owner_id 等于自己 id 的 partner
    - partner 不存在时返回 404（避免通过 403/404 差异确认 partner_id 是否存在）
    - owner_id 为空串表示 admin owner，此时仅 admin 可操作
    """
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    owner_id = resolve_owner_for_partner(partner_id)

    # partner 不存在时直接 404
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id, owner_id=owner_id or None):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))

    if user.is_admin:
        return owner_id

    if owner_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="你没有权限操作此 partner",
        )
    return owner_id


# Per-partner async locks used to dedupe concurrent WebSocket-driven
# auto-starts (start_partner short-circuits when running, but that check is
# not async-safe under concurrent connections).
_start_locks: dict[str, asyncio.Lock] = {}
_start_locks_mutex = asyncio.Lock()


async def _get_start_lock(partner_id: str) -> asyncio.Lock:
    async with _start_locks_mutex:
        lock = _start_locks.get(partner_id)
        if lock is None:
            lock = asyncio.Lock()
            _start_locks[partner_id] = lock
        return lock


async def _ensure_running_partner(partner_id: str) -> PartnerInstance:
    mgr = get_partner_manager()
    instance = mgr.get_partner(partner_id)
    if instance and instance.running:
        return instance

    owner_id = resolve_owner_for_partner(partner_id) or None
    config = mgr.load_config(partner_id, owner_id=owner_id)
    if config is None:
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))

    lock = await _get_start_lock(partner_id)
    async with lock:
        instance = mgr.get_partner(partner_id)
        if instance and instance.running:
            return instance
        try:
            return await mgr.start_partner(partner_id, config)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        except Exception as exc:
            logger.exception("Failed to auto-start partner '%s'", partner_id)
            raise HTTPException(status_code=500, detail="Failed to start partner") from exc


# ── Request models ─────────────────────────────────────────────


class SoulSpec(BaseModel):
    """Where a new partner's soul comes from."""

    source: Literal["default", "library", "persona", "custom"] = "default"
    id: str | None = None  # library soul id, or persona name
    content: str | None = None  # custom markdown


class AssetSpec(BaseModel):
    knowledge_bases: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    notebooks: list[str] = Field(default_factory=list)


class CreatePartnerRequest(BaseModel):
    partner_id: str | None = None
    name: str = Field(..., min_length=1)
    description: str | None = None
    soul: SoulSpec | None = None
    channels: dict | None = None
    llm_selection: dict[str, str] | None = None
    backup_llm_selection: dict[str, str] | None = None
    language: str | None = None
    emoji: str | None = None
    color: str | None = None
    avatar: str | None = None
    enabled_tools: list[str] | None = None
    mcp_tools: list[str] | None = None
    assets: AssetSpec | None = None
    start: bool = True


class UpdatePartnerRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    channels: dict | None = None
    llm_selection: dict[str, str] | None = None
    backup_llm_selection: dict[str, str] | None = None
    language: str | None = None
    emoji: str | None = None
    color: str | None = None
    avatar: str | None = None
    enabled_tools: list[str] | None = None
    mcp_tools: list[str] | None = None


class SoulUpdateBody(BaseModel):
    content: str


class AssetAddRequest(AssetSpec):
    pass


class ChatAttachmentRequest(BaseModel):
    type: str = "file"
    url: str = ""
    base64: str = ""
    filename: str = ""
    mime_type: str = ""


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str = ""
    session_id: str | None = None
    chat_id: str | None = None
    attachments: list[ChatAttachmentRequest] = Field(default_factory=list)
    llm_selection: dict[str, str] | None = Field(default=None, alias="llmSelection")


class SoulCreateRequest(BaseModel):
    id: str
    name: str
    content: str


class SoulTemplateUpdateRequest(BaseModel):
    name: str | None = None
    content: str | None = None


# ── Validation helpers ─────────────────────────────────────────


def _validate_channels_payload(channels: dict) -> None:
    """Reject malformed channel configs at the API boundary (422)."""
    from deeptutor.partners.config.schema import ChannelsConfig

    legacy_keys = sorted(k for k in channels if k in LEGACY_GLOBAL_DELIVERY_KEYS)
    if legacy_keys:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "Delivery flags are configured per channel; remove top-level "
                    f"channel keys: {', '.join(legacy_keys)}"
                )
            },
        )

    try:
        ChannelsConfig(**channels)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": t("api.invalid_channels_config"), "errors": exc.errors()},
        ) from None
    except TypeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{t('api.invalid_channels_config')}: {exc}",
        ) from None


# Inline avatars are client-resized to ~128px before upload; this cap is a
# server-side backstop so config.yaml can't be bloated with raw photos.
_AVATAR_MAX_CHARS = 200_000


def _validate_avatar_payload(value: str | None) -> str:
    avatar = (value or "").strip()
    if not avatar:
        return ""
    if not avatar.startswith("data:image/"):
        raise HTTPException(status_code=422, detail="Avatar must be a data:image/* URL")
    if len(avatar) > _AVATAR_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail="Avatar too large — resize the image before uploading",
        )
    return avatar


def _validate_llm_selection_payload(
    value: dict[str, str] | None,
) -> dict[str, str] | None:
    """Validate a partner model selection against the shared LLM catalog."""
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.model_selection import apply_llm_selection_to_catalog
    from deeptutor.services.partners.model_runtime import normalize_partner_llm_selection

    try:
        selection = normalize_partner_llm_selection(value)
        if selection:
            apply_llm_selection_to_catalog(get_model_catalog_service().load(), selection)
        return selection
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _resolve_soul_content(soul: SoulSpec | None) -> tuple[str, dict[str, str]]:
    """Resolve a SoulSpec into (markdown content, origin record)."""
    from deeptutor.services.partners.workspace import DEFAULT_SOUL

    if soul is None or soul.source == "default":
        return DEFAULT_SOUL, {"type": "default", "id": ""}

    if soul.source == "custom":
        content = (soul.content or "").strip()
        if not content:
            raise HTTPException(status_code=422, detail=t("api.soul_content_empty"))
        return content, {"type": "custom", "id": ""}

    if soul.source == "library":
        entry = get_partner_manager().get_soul(str(soul.id or ""))
        if not entry:
            raise HTTPException(
                status_code=404,
                detail=t("api.soul_library_not_found", name=str(soul.id)),
            )
        return str(entry.get("content") or ""), {"type": "library", "id": str(soul.id)}

    # source == "persona": clone from the chat persona workspace (the
    # requesting user's personas first; non-admins fall back to admin
    # presets, mirroring chat's resolution).
    name = str(soul.id or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail=t("api.persona_name_required"))
    content = _load_persona_markdown(name)
    if not content:
        raise HTTPException(status_code=404, detail=t("api.persona_not_found", name=name))
    return content, {"type": "persona", "id": name}


def _load_persona_markdown(name: str) -> str:
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services.persona import PersonaService, get_persona_service

    try:
        detail = get_persona_service().get_detail(name)
        return strip_frontmatter(detail.content)
    except Exception:
        pass
    try:
        if not get_current_user().is_admin:
            admin_service = PersonaService(
                root=get_admin_path_service().get_workspace_dir() / "personas"
            )
            return strip_frontmatter(admin_service.get_detail(name).content)
    except Exception:
        pass
    return ""


# ── Soul template library (before /{partner_id} routes) ───────


@router.get("/souls")
async def list_souls():
    # 灵魂模板是共享资源，仅 admin 可管理
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return get_partner_manager().list_souls()


@router.post("/souls")
async def create_soul(payload: SoulCreateRequest):
    # 灵魂模板是共享资源，仅 admin 可管理
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    mgr = get_partner_manager()
    if mgr.get_soul(payload.id):
        raise HTTPException(status_code=409, detail=t("api.soul_already_exists", name=payload.id))
    return mgr.create_soul(payload.id, payload.name, payload.content)


@router.get("/souls/{soul_id}")
async def get_soul(soul_id: str):
    # 灵魂模板是共享资源，仅 admin 可管理
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    soul = get_partner_manager().get_soul(soul_id)
    if not soul:
        raise HTTPException(status_code=404, detail=t("api.soul_not_found"))
    return soul


@router.put("/souls/{soul_id}")
async def update_soul(soul_id: str, payload: SoulTemplateUpdateRequest):
    # 灵魂模板是共享资源，仅 admin 可管理
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    result = get_partner_manager().update_soul(soul_id, payload.name, payload.content)
    if not result:
        raise HTTPException(status_code=404, detail=t("api.soul_not_found"))
    return result


@router.delete("/souls/{soul_id}")
async def delete_soul(soul_id: str):
    # 灵魂模板是共享资源，仅 admin 可管理
    from deeptutor.multi_user.context import get_current_user

    user = get_current_user()
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    if not get_partner_manager().delete_soul(soul_id):
        raise HTTPException(status_code=404, detail=t("api.soul_not_found"))
    return {"id": soul_id, "deleted": True}


@router.get("/soul-sources")
async def soul_sources():
    """Everything the create-wizard's soul step can start from."""
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.paths import get_admin_path_service
    from deeptutor.services.persona import PersonaService, get_persona_service

    def _persona_entry(service: PersonaService, info: Any) -> dict[str, str]:
        # Content rides along so the wizard can preview the clone; creation
        # still re-resolves the persona server-side (_resolve_soul_content).
        try:
            content = strip_frontmatter(service.get_detail(info.name).content)
        except Exception:
            content = ""
        return {"name": info.name, "description": info.description, "content": content}

    personas: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        service = get_persona_service()
        for info in service.list_personas():
            personas.append(_persona_entry(service, info))
            seen.add(info.name)
    except Exception:
        logger.warning("Failed to list user personas", exc_info=True)
    try:
        if not get_current_user().is_admin:
            admin_service = PersonaService(
                root=get_admin_path_service().get_workspace_dir() / "personas"
            )
            for info in admin_service.list_personas():
                if info.name not in seen:
                    personas.append(_persona_entry(admin_service, info))
    except Exception:
        logger.warning("Failed to list admin personas", exc_info=True)

    return {"library": get_partner_manager().list_souls(), "personas": personas}


# ── Static catalog endpoints ───────────────────────────────────


@router.get("")
async def list_partners():
    return get_partner_manager().list_partners()


@router.get("/recent")
async def recent_partners(limit: int = 3):
    return get_partner_manager().get_recent_active_partners(limit=limit)


@router.get("/channels/schema")
async def list_channel_schemas():
    """JSON-Schema metadata for every available channel (schema-driven UI)."""
    from deeptutor.api.routers._partners_channel_schema import all_channel_schemas

    return {"channels": all_channel_schemas()}


@router.get("/tool-options")
async def tool_options():
    """The configurable tool surface for a partner.

    ``tools`` mirrors the user-toggleable system tools (the same pool the
    chat composer / settings expose); ``mcp_tools`` lists every configured
    MCP tool the partner could be allowed to load.
    """
    from deeptutor.api.utils.tool_options import build_tool_options

    return await build_tool_options()


# ── Create / read / update / lifecycle ─────────────────────────


@router.post("")
async def create_partner(payload: CreatePartnerRequest):
    from deeptutor.multi_user.context import get_current_user

    mgr = get_partner_manager()
    partner_id = slugify_partner_id(payload.partner_id or payload.name)

    # 全局唯一性检查：如果 partner_id 已被任何用户占用，自动加后缀
    if mgr.partner_exists(partner_id):
        base = partner_id
        suffix = 2
        while mgr.partner_exists(partner_id):
            partner_id = f"{base}-{suffix}"
            suffix += 1

    if payload.channels is not None:
        _validate_channels_payload(payload.channels)
    llm_selection = _validate_llm_selection_payload(payload.llm_selection)
    backup_llm_selection = _validate_llm_selection_payload(payload.backup_llm_selection)
    soul_content, soul_origin = _resolve_soul_content(payload.soul)

    # 从当前用户获取 owner_id：admin 为空串，普通用户为 uid
    current_user = get_current_user()
    owner_id = "" if current_user.is_admin else current_user.id

    config = PartnerConfig(
        name=payload.name.strip(),
        description=(payload.description or "").strip(),
        channels=payload.channels or {},
        llm_selection=llm_selection,
        backup_llm_selection=backup_llm_selection,
        language=(payload.language or "").strip(),
        emoji=(payload.emoji or "").strip(),
        color=(payload.color or "").strip(),
        avatar=_validate_avatar_payload(payload.avatar),
        soul_origin=soul_origin,
        enabled_tools=payload.enabled_tools,
        mcp_tools=payload.mcp_tools,
        owner_id=owner_id,
    )
    mgr.save_config(partner_id, config, auto_start=True)
    write_soul(partner_id, soul_content, owner_id=owner_id or None)

    provisioning: dict[str, Any] = {"copied": {}, "errors": []}
    if payload.assets is not None:
        provisioning = provision_assets(
            partner_id,
            owner_id=owner_id or None,
            knowledge_bases=payload.assets.knowledge_bases,
            skills=payload.assets.skills,
            notebooks=payload.assets.notebooks,
        )

    if payload.start:
        try:
            instance = await mgr.start_partner(partner_id, config)
            result = instance.to_dict(mask_secrets=True)
        except Exception:
            logger.exception("Partner '%s' created but failed to start", partner_id)
            result = _stopped_partner_dict(partner_id, config)
            result["start_error"] = "Partner created but failed to start"
    else:
        result = _stopped_partner_dict(partner_id, config)

    result["provisioning"] = provisioning
    return result


def _stopped_partner_dict(
    partner_id: str,
    cfg: PartnerConfig,
    *,
    include_secrets: bool = False,
) -> dict:
    if include_secrets:
        channels: object = strip_legacy_global_delivery(cfg.channels)
    else:
        channels = mask_channel_secrets(strip_legacy_global_delivery(cfg.channels))
    return {
        "partner_id": partner_id,
        "name": cfg.name,
        "description": cfg.description,
        "channels": channels,
        "llm_selection": cfg.llm_selection,
        "backup_llm_selection": cfg.backup_llm_selection,
        "model": cfg.model,
        "language": cfg.language,
        "emoji": cfg.emoji,
        "color": cfg.color,
        "avatar": cfg.avatar,
        "soul_origin": cfg.soul_origin,
        "enabled_tools": cfg.enabled_tools,
        "mcp_tools": cfg.mcp_tools,
        "owner_id": cfg.owner_id,
        "running": False,
        "started_at": None,
        "last_reload_error": None,
    }


@router.get("/{partner_id}")
async def get_partner(
    partner_id: str,
    include_secrets: bool = Query(
        False,
        description=(
            "Return raw channel secrets (tokens, passwords). Required by the "
            "edit form; default response masks all secret-looking fields."
        ),
    ),
):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    instance = mgr.get_partner(partner_id)
    if instance:
        return instance.to_dict(
            include_secrets=include_secrets,
            mask_secrets=not include_secrets,
        )
    owner_id = resolve_owner_for_partner(partner_id) or None
    cfg = mgr.load_config(partner_id, owner_id=owner_id)
    if cfg:
        return _stopped_partner_dict(partner_id, cfg, include_secrets=include_secrets)
    raise HTTPException(status_code=404, detail=t("api.partner_not_found"))


def _apply_update(cfg: PartnerConfig, payload: UpdatePartnerRequest) -> None:
    if payload.name is not None:
        cfg.name = payload.name
    if payload.description is not None:
        cfg.description = payload.description
    if payload.channels is not None:
        cfg.channels = payload.channels
    if payload.language is not None:
        cfg.language = payload.language
    if payload.emoji is not None:
        cfg.emoji = payload.emoji
    if payload.color is not None:
        cfg.color = payload.color
    if payload.avatar is not None:
        cfg.avatar = _validate_avatar_payload(payload.avatar)
    if "llm_selection" in payload.model_fields_set:
        cfg.llm_selection = _validate_llm_selection_payload(payload.llm_selection)
        cfg.model = None  # selection supersedes any legacy model string
    if "backup_llm_selection" in payload.model_fields_set:
        cfg.backup_llm_selection = _validate_llm_selection_payload(payload.backup_llm_selection)
    if "enabled_tools" in payload.model_fields_set:
        cfg.enabled_tools = payload.enabled_tools
    if "mcp_tools" in payload.model_fields_set:
        cfg.mcp_tools = payload.mcp_tools


@router.patch("/{partner_id}")
async def update_partner(partner_id: str, payload: UpdatePartnerRequest):
    _check_partner_owner(partner_id)
    if payload.channels is not None:
        _validate_channels_payload(payload.channels)

    mgr = get_partner_manager()
    instance = mgr.get_partner(partner_id)
    if instance:
        _apply_update(instance.config, payload)
        mgr.save_config(partner_id, instance.config)
        if payload.channels is not None:
            try:
                await mgr.reload_channels(partner_id)
            except Exception as exc:
                logger.exception("reload_channels failed for partner '%s'", partner_id)
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Channels saved but failed to restart listeners "
                        f"({type(exc).__name__}); try stopping and starting the partner."
                    ),
                ) from None
        # LLM / tool changes need no reload: the runner resolves
        # llm_selection and tool config per turn from this same config object.
        return instance.to_dict(mask_secrets=True)

    owner_id = resolve_owner_for_partner(partner_id) or None
    cfg = mgr.load_config(partner_id, owner_id=owner_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    _apply_update(cfg, payload)
    mgr.save_config(partner_id, cfg)
    return _stopped_partner_dict(partner_id, cfg)


@router.post("/{partner_id}/start")
async def start_partner(partner_id: str):
    _check_partner_owner(partner_id)
    instance = await _ensure_running_partner(partner_id)
    return instance.to_dict(mask_secrets=True)


@router.post("/{partner_id}/stop")
async def stop_partner(partner_id: str):
    _check_partner_owner(partner_id)
    stopped = await get_partner_manager().stop_partner(partner_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=t("api.partner_not_found_or_not_running"))
    return {"partner_id": partner_id, "stopped": True}


@router.delete("/{partner_id}")
async def destroy_partner(partner_id: str):
    _check_partner_owner(partner_id)
    destroyed = await get_partner_manager().destroy_partner(partner_id)
    if not destroyed:
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    return {"partner_id": partner_id, "destroyed": True}


@router.post("/{partner_id}/channels/reload")
async def reload_partner_channels(partner_id: str):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    instance = mgr.get_partner(partner_id)
    if not instance or not instance.running:
        raise HTTPException(status_code=404, detail=t("api.partner_not_running"))
    try:
        await mgr.reload_channels(partner_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reload channels: {type(exc).__name__}",
        ) from None
    return {"partner_id": partner_id, "reloaded": True}


# ── Soul (the partner's own SOUL.md) ───────────────────────────


@router.get("/{partner_id}/soul")
async def get_partner_soul(partner_id: str):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    owner_id = resolve_owner_for_partner(partner_id) or None
    return {"partner_id": partner_id, "content": read_soul(partner_id, owner_id=owner_id)}


@router.put("/{partner_id}/soul")
async def put_partner_soul(partner_id: str, payload: SoulUpdateBody):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    owner_id = resolve_owner_for_partner(partner_id) or None
    write_soul(partner_id, payload.content, owner_id=owner_id)
    return {"partner_id": partner_id, "saved": True}


# ── Assets ─────────────────────────────────────────────────────


@router.get("/{partner_id}/assets")
async def get_partner_assets(partner_id: str):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    owner_id = resolve_owner_for_partner(partner_id) or None
    return list_assets(partner_id, owner_id=owner_id)


@router.post("/{partner_id}/assets")
async def add_partner_assets(partner_id: str, payload: AssetAddRequest):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    owner_id = resolve_owner_for_partner(partner_id) or None
    report = provision_assets(
        partner_id,
        owner_id=owner_id,
        knowledge_bases=payload.knowledge_bases,
        skills=payload.skills,
        notebooks=payload.notebooks,
    )
    return {"partner_id": partner_id, **report, "assets": list_assets(partner_id, owner_id=owner_id)}


@router.delete("/{partner_id}/assets/{asset_type}/{name}")
async def delete_partner_asset(partner_id: str, asset_type: str, name: str):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    owner_id = resolve_owner_for_partner(partner_id) or None
    try:
        removed = remove_asset(partner_id, asset_type, name, owner_id=owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not removed:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"partner_id": partner_id, "removed": True, "assets": list_assets(partner_id, owner_id=owner_id)}


# ── History ────────────────────────────────────────────────────


@router.get("/{partner_id}/history")
async def get_partner_history(
    partner_id: str,
    session_key: str | None = None,
    limit: int = 100,
):
    _check_partner_owner(partner_id)
    return get_partner_manager().get_history(partner_id, session_key=session_key, limit=limit)


@router.get("/{partner_id}/sessions")
async def get_partner_sessions(partner_id: str):
    _check_partner_owner(partner_id)
    mgr = get_partner_manager()
    if not mgr.partner_exists(partner_id):
        raise HTTPException(status_code=404, detail=t("api.partner_not_found"))
    owner_id = resolve_owner_for_partner(partner_id) or None
    return mgr.session_store(partner_id, owner_id=owner_id).list_sessions()


@router.get("/commands/palette")
async def partner_command_palette():
    from deeptutor.services.partners.commands import partner_command_palette

    return {"commands": partner_command_palette()}


# ── Chat (HTTP / SSE / WebSocket) ──────────────────────────────


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _resolve_http_session(payload: ChatMessageRequest) -> tuple[str, str]:
    explicit_session = (payload.session_id or "").strip()
    explicit_chat = (payload.chat_id or "").strip()
    if explicit_session:
        return explicit_session, explicit_chat or explicit_session
    if explicit_chat:
        return explicit_chat, explicit_chat
    session_id = uuid4().hex
    return session_id, session_id


_PARTNER_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
_PARTNER_UPLOAD_MAX_TOTAL_BYTES = 25 * 1024 * 1024


def _clean_attachment_base64(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1]
    return text


def _default_attachment_prompt(attachments: list[ChatAttachmentRequest]) -> str:
    if attachments and all(str(item.type).lower() == "image" for item in attachments):
        return t("Please analyze the attached image(s).")
    return t("Please use the attached file(s).")


def _materialize_partner_attachments(
    partner_id: str,
    attachments: list[ChatAttachmentRequest],
) -> list[str]:
    """Persist browser-sent attachment bytes into the partner media tree."""
    if not attachments:
        return []

    owner_id = resolve_owner_for_partner(partner_id) or None
    media_dir = get_partner_media_dir(partner_id, "web", owner_id=owner_id)
    total_bytes = 0
    media_paths: list[str] = []
    for item in attachments:
        raw_b64 = _clean_attachment_base64(item.base64)
        if not raw_b64:
            # Partner web chat accepts uploaded bytes only. URL-only
            # attachments are ignored rather than fetched server-side.
            continue
        try:
            data = base64.b64decode(raw_b64, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid attachment data for {item.filename or 'file'}",
            ) from exc
        if len(data) > _PARTNER_UPLOAD_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Attachment too large: {item.filename or 'file'}",
            )
        if total_bytes + len(data) > _PARTNER_UPLOAD_MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Attachment batch too large")
        total_bytes += len(data)

        filename = safe_filename(item.filename or "attachment") or "attachment"
        path = media_dir / f"{uuid4().hex[:12]}_{filename}"
        path.write_bytes(data)
        media_paths.append(str(path))
    return media_paths


@router.post("/{partner_id}/chat")
async def partner_chat_http(partner_id: str, payload: ChatMessageRequest) -> dict[str, Any]:
    """Send one HTTP message to a partner with persistent session context."""
    _check_partner_owner(partner_id)
    content = payload.content.strip()
    if not content and not payload.attachments:
        raise HTTPException(status_code=400, detail=t("api.content_required"))
    await _ensure_running_partner(partner_id)
    media_paths = _materialize_partner_attachments(partner_id, payload.attachments)
    if not content and media_paths:
        content = _default_attachment_prompt(payload.attachments)
    mgr = get_partner_manager()
    session_id, chat_id = _resolve_http_session(payload)
    try:
        response = await mgr.send_message(
            partner_id,
            content,
            chat_id=chat_id,
            session_id=session_id,
            media=media_paths,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "partner_id": partner_id,
        "session_id": session_id,
        "content": response,
    }


async def _partner_chat_stream(
    partner_id: str,
    payload: ChatMessageRequest,
) -> AsyncGenerator[str, None]:
    from deeptutor.core.stream import StreamEventType

    mgr = get_partner_manager()
    content = payload.content.strip()
    if not content and not payload.attachments:
        yield _sse("error", {"detail": t("api.content_required")})
        return
    media_paths = _materialize_partner_attachments(partner_id, payload.attachments)
    if not content and media_paths:
        content = _default_attachment_prompt(payload.attachments)
    session_id, chat_id = _resolve_http_session(payload)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    done = asyncio.Event()
    holder: dict[str, Any] = {}

    async def on_event(event: Any) -> None:
        if event.type == StreamEventType.THINKING and event.content:
            await queue.put({"event": "thinking", "payload": {"content": event.content}})

    async def run() -> None:
        try:
            holder["content"] = await mgr.send_message(
                partner_id,
                content,
                chat_id=chat_id,
                session_id=session_id,
                media=media_paths,
                on_event=on_event,
            )
        except Exception as exc:  # noqa: BLE001
            holder["error"] = str(exc)
        finally:
            done.set()

    yield _sse("session", {"partner_id": partner_id, "session_id": session_id})
    task = asyncio.create_task(run())
    try:
        while not done.is_set():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.15)
            except asyncio.TimeoutError:
                continue
            yield _sse(item["event"], item["payload"])
        while not queue.empty():
            item = queue.get_nowait()
            yield _sse(item["event"], item["payload"])
        if holder.get("error"):
            yield _sse("error", {"detail": holder["error"]})
            return
        yield _sse("content", {"content": holder.get("content", "")})
        yield _sse("done", {"partner_id": partner_id, "session_id": session_id})
    finally:
        if not task.done():
            task.cancel()


@router.post("/{partner_id}/chat/execute-stream")
async def partner_chat_http_stream(partner_id: str, payload: ChatMessageRequest):
    """Stream one HTTP message to a partner as server-sent events."""
    _check_partner_owner(partner_id)
    if not payload.content.strip() and not payload.attachments:
        raise HTTPException(status_code=400, detail=t("api.content_required"))
    await _ensure_running_partner(partner_id)
    return StreamingResponse(
        _partner_chat_stream(partner_id, payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/{partner_id}/ws")
async def partner_chat_ws(ws: WebSocket, partner_id: str):
    """Web chat socket.

    Client → server: ``{"content": str, "session_id"?: str, "chat_id"?: str,
    "attachments"?: [{"type", "filename", "mime_type", "base64"}]}``.
    Server → client frames:

    * ``{"type": "stream_event", "event": {...}}`` — every chat-loop
      StreamEvent (content/thinking/tool_call/progress/sources/result),
      letting the UI render the same live trace as product chat;
    * ``{"type": "content", "content": str}`` — the final reply;
    * ``{"type": "done"}`` / ``{"type": "error"}`` / ``{"type": "proactive"}``.
    """
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    # Ownership 校验：WebSocket 不能抛 HTTPException，需手动处理
    from deeptutor.multi_user.context import get_current_user

    ws_user = get_current_user()
    ws_owner_id = resolve_owner_for_partner(partner_id)
    if not ws_user.is_admin and ws_owner_id != ws_user.id:
        await ws.close(code=4003, reason="你没有权限操作此 partner")
        return

    disconnected = asyncio.Event()

    async def _safe_send(payload: dict) -> bool:
        try:
            await ws.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError):
            disconnected.set()
            return False

    mgr = get_partner_manager()
    instance = mgr.get_partner(partner_id)

    await ws.accept()

    if not instance or not instance.running:
        owner_id = resolve_owner_for_partner(partner_id) or None
        config = mgr.load_config(partner_id, owner_id=owner_id)
        if config is None:
            message = t("api.partner_not_found")
            await _safe_send({"type": "error", "content": message})
            await ws.close(code=4004, reason=message)
            return
        lock = await _get_start_lock(partner_id)
        async with lock:
            instance = mgr.get_partner(partner_id)
            if not instance or not instance.running:
                try:
                    instance = await mgr.start_partner(partner_id, config)
                except Exception:
                    logger.exception("Failed to auto-start partner '%s' for websocket", partner_id)
                    await _safe_send({"type": "error", "content": "Failed to start partner"})
                    await ws.close(code=1011, reason="Failed to start partner")
                    return

    logger.info("WebSocket connected for partner '%s'", partner_id)

    async def _handle_user_messages():
        while not disconnected.is_set():
            try:
                raw = await ws.receive_text()
            except WebSocketDisconnect:
                disconnected.set()
                break
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                if not await _safe_send({"type": "error", "content": "Invalid JSON"}):
                    break
                continue

            content = data.get("content", "").strip()
            try:
                attachments = [
                    ChatAttachmentRequest.model_validate(item)
                    for item in (data.get("attachments") or [])
                    if isinstance(item, dict)
                ]
            except ValidationError:
                if not await _safe_send({"type": "error", "content": "Invalid attachments"}):
                    break
                continue

            if not content and not attachments:
                continue
            try:
                media_paths = _materialize_partner_attachments(partner_id, attachments)
            except HTTPException as exc:
                if not await _safe_send({"type": "error", "content": str(exc.detail)}):
                    break
                continue
            if not content and media_paths:
                content = _default_attachment_prompt(attachments)

            async def on_event(event: Any) -> None:
                # Best-effort: never raise into the runner. A vanished
                # client just stops receiving frames; the turn finishes
                # server-side and lands in the session store.
                try:
                    await _safe_send({"type": "stream_event", "event": event.to_dict()})
                except Exception:
                    pass

            try:
                response = await mgr.send_message(
                    partner_id,
                    content,
                    chat_id=data.get("chat_id", "web"),
                    session_id=data.get("session_id"),
                    media=media_paths,
                    on_event=on_event,
                )
                if not await _safe_send({"type": "content", "content": response}):
                    break
                if not await _safe_send({"type": "done"}):
                    break
            except RuntimeError as exc:
                if not await _safe_send({"type": "error", "content": str(exc)}):
                    break
            except WebSocketDisconnect:
                disconnected.set()
                break
            except Exception:
                logger.exception("Error processing message for partner '%s'", partner_id)
                if not await _safe_send({"type": "error", "content": "Internal error"}):
                    break

    async def _handle_notifications():
        while not disconnected.is_set():
            get_task = asyncio.create_task(instance.notify_queue.get())
            wait_task = asyncio.create_task(disconnected.wait())
            done, pending = await asyncio.wait(
                {get_task, wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if get_task not in done:
                break
            content = get_task.result()
            if not await _safe_send({"type": "proactive", "content": content}):
                break

    user_task = asyncio.create_task(_handle_user_messages())
    notify_task = asyncio.create_task(_handle_notifications())
    try:
        done, pending = await asyncio.wait(
            [user_task, notify_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        disconnected.set()
        for t in pending:
            t.cancel()
        for t in done:
            if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                logger.exception(
                    "WebSocket task error for partner '%s'",
                    partner_id,
                    exc_info=t.exception(),
                )
    except Exception:
        disconnected.set()
        user_task.cancel()
        notify_task.cancel()
    finally:
        if user_token is not None:
            try:
                reset_current_user(user_token)
            except Exception:
                pass
    logger.info("WebSocket closed for partner '%s'", partner_id)
