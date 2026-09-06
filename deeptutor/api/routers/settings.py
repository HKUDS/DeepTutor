"""
Settings API Router
===================

UI preferences, configuration catalog management, and detailed streamed tests.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import time
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.model_access import allowed_llm_options
from deeptutor.services.codebuddy_auth import get_codebuddy_auth_service
from deeptutor.services.codex_auth import (
    CodexAuthError,
    get_codex_oauth_service,
    reconcile_codex_catalog_update,
)
from deeptutor.services.config import (
    CATALOG_SECRET_MASK,
    get_config_test_runner,
    get_model_catalog_service,
    get_runtime_settings_service,
    redact_catalog_secrets,
    restore_catalog_secrets,
)
from deeptutor.services.config.origins import normalize_origins
from deeptutor.services.config.runtime_settings import (
    CHAT_ATTACHMENT_CHARS_RANGE,
    CHAT_ATTACHMENT_MAX_FILE_MB_RANGE,
    CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE,
    compute_ws_max_size,
)
from deeptutor.services.config.settings_draft import (
    get_settings_draft_service,
    is_empty_draft,
    merge_draft_secrets,
    redact_draft,
)
from deeptutor.services.llm.config import clear_llm_config_cache
from deeptutor.services.model_selection import list_llm_options
from deeptutor.services.path_service import get_path_service
from deeptutor.services.settings.interface_settings import (
    DEFAULT_UI_SETTINGS as INTERFACE_DEFAULTS,
)
from deeptutor.services.settings.interface_settings import (
    atomic_update,
    resolve_languages,
    sanitize_enabled_tools,
)
from deeptutor.services.settings.interface_settings import (
    get_enabled_optional_tools as _get_enabled_optional_tools,
)
from deeptutor.services.settings.starter_settings import (
    TRACE_COUNT_RANGE as STARTER_TRACE_COUNT_RANGE,
)
from deeptutor.tools.builtin import USER_TOGGLEABLE_TOOL_NAMES

router = APIRouter()
# Public UI-settings router. The app shell bootstraps the interface language
# from GET /api/settings/ui, and auth pages (/register, /login) must be
# able to do the same *before* a session exists — so this one read endpoint
# is intentionally mounted outside the ``_auth`` dependency (see main.py).
# It only exposes non-sensitive UI preferences (theme/language), never the
# model catalog, provider credentials, or runtime configuration.
public_router = APIRouter()

TOUR_CACHE = None


def get_enabled_optional_tools() -> list[str]:
    """Compatibility export; the source of truth lives in the service layer."""

    return _get_enabled_optional_tools()


def _settings_file():
    return get_path_service().get_settings_file("interface")


def _tour_cache_file():
    if TOUR_CACHE is not None:
        return TOUR_CACHE
    return get_path_service().get_settings_dir() / ".tour_cache.json"


DEFAULT_SIDEBAR_NAV_ORDER = {
    "start": ["/", "/history", "/knowledge-bases", "/notebooks"],
    "learnResearch": ["/question", "/solver", "/research", "/co_writer"],
}

DEFAULT_UI_SETTINGS = {
    # theme / language / response_language come from the module that owns
    # interface.json, so the two readers of that file can't drift on what a
    # fresh install defaults to.
    **INTERFACE_DEFAULTS,
    "sidebar_description": "✨ Data Intelligence Lab @ HKU",
    "sidebar_nav_order": DEFAULT_SIDEBAR_NAV_ORDER,
    # User-toggleable chat tools. Default = all on; the /settings/tools page
    # is the single switchboard. Removed names (e.g. tools that ship later
    # and the user hasn't seen yet) are ignored on read; missing names from a
    # legacy file fall back to the default (all on).
    "enabled_optional_tools": list(USER_TOGGLEABLE_TOOL_NAMES),
    # When true, chat auto-plays each assistant reply via TTS. Per-user UI
    # preference (not catalog); the chat surface also keeps a per-session
    # override on top of this global default.
    "voice_autoplay": False,
    # Seconds the chat UI waits for any turn event before declaring the
    # connection timed out. Bumped from 60 → 180 so slow tools (image/video
    # generation) don't trip it; user-adjustable in Settings > Network.
    "chat_response_timeout": 180,
}

# Bounds for the chat idle timeout (seconds): long enough for video renders,
# capped so a typo can't wedge a turn open forever.
CHAT_RESPONSE_TIMEOUT_MIN = 30
CHAT_RESPONSE_TIMEOUT_MAX = 1800


class SidebarNavOrder(BaseModel):
    start: List[str]
    learnResearch: List[str]


class UISettings(BaseModel):
    theme: Literal["light", "dark", "glass", "snow"] = "snow"
    language: Literal["zh", "en"] = "en"
    response_language: Literal["zh", "en"] = "en"
    sidebar_description: Optional[str] = None
    sidebar_nav_order: Optional[SidebarNavOrder] = None
    code_block_theme: Optional[str] = None
    code_block_show_line_numbers: Optional[bool] = None
    code_block_wrap_long_lines: Optional[bool] = None


class UISettingsUpdate(BaseModel):
    """Partial UI settings for user-initiated PATCH/PUT updates via /api/settings/ui.

    All fields have None defaults so `model_dump(exclude_unset=True)` naturally
    excludes fields not provided in the frontend payload, while explicitly provided
    defaults (e.g., `theme: "snow"`) still update the backend. This separates
    the semantic contract: `/ui` endpoint only merges whatever explicitly arrives
    from the frontend.
    """

    # Same Literal domains as UISettings — a None default keeps them optional
    # for exclude_unset partial merges, but an explicit value is still validated
    # so PUT /ui cannot persist a theme/language the app can't render.
    theme: Literal["light", "dark", "glass", "snow"] | None = None
    language: Literal["zh", "en"] | None = None
    response_language: Literal["zh", "en"] | None = None
    sidebar_description: str | None = None
    sidebar_nav_order: SidebarNavOrder | None = None
    code_block_theme: str | None = None
    code_block_show_line_numbers: bool | None = None
    code_block_wrap_long_lines: bool | None = None


class VoiceAutoplayUpdate(BaseModel):
    voice_autoplay: bool


class ChatResponseTimeoutUpdate(BaseModel):
    chat_response_timeout: int = Field(ge=CHAT_RESPONSE_TIMEOUT_MIN, le=CHAT_RESPONSE_TIMEOUT_MAX)


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark", "glass", "snow"]


class LanguageUpdate(BaseModel):
    language: Literal["zh", "en"]


class SidebarDescriptionUpdate(BaseModel):
    description: str


class SidebarNavOrderUpdate(BaseModel):
    nav_order: SidebarNavOrder


class EnabledToolsUpdate(BaseModel):
    enabled_tools: List[str]


class CatalogPayload(BaseModel):
    catalog: dict[str, Any]


class CatalogServicePayload(BaseModel):
    """One model-catalog service to promote without touching other drafts."""

    service: Literal[
        "llm",
        "task",
        "embedding",
        "search",
        "tts",
        "stt",
        "imagegen",
        "videogen",
    ]
    config: dict[str, Any]


class SettingsDraftPayload(BaseModel):
    """The unapplied settings envelope, as the settings UI holds it."""

    catalog: dict[str, Any] | None = None
    # Opaque per-page state, keyed by the string the page registers with.
    extensions: dict[str, Any] = Field(default_factory=dict)


class CodexReasoningEffortUpdate(BaseModel):
    model: str = Field(min_length=1)
    reasoning_effort: str | None = None


class FetchModelsPayload(BaseModel):
    binding: str = ""
    base_url: str = ""
    api_key: Optional[str] = None
    profile_id: Optional[str] = None
    # Which LLM-shaped service the profile lives in (for resolving a masked key).
    service: Literal["llm", "task"] = "llm"
    # The profile's API format; decides whether /models takes Anthropic headers.
    api_format: Optional[str] = None


class ModelCapabilitiesQuery(BaseModel):
    binding: str = ""
    model: str = ""


class NetworkSettingsUpdate(BaseModel):
    backend_port: int = Field(ge=1, le=65535)
    frontend_port: int = Field(ge=1, le=65535)
    public_api_base: str = ""
    cors_origins: list[str] = Field(default_factory=list)


class ChatAttachmentSettingsUpdate(BaseModel):
    """Chat attachment policy (size caps + extraction budgets).

    Bounds mirror the normalization clamps in
    ``runtime_settings.CHAT_ATTACHMENT_*_RANGE`` so the API rejects loudly
    what the file layer would silently clamp.
    """

    max_file_mb: int = Field(
        ge=CHAT_ATTACHMENT_MAX_FILE_MB_RANGE[0], le=CHAT_ATTACHMENT_MAX_FILE_MB_RANGE[1]
    )
    max_total_mb: int = Field(
        ge=CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE[0], le=CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE[1]
    )
    max_chars_per_doc: int = Field(
        ge=CHAT_ATTACHMENT_CHARS_RANGE[0], le=CHAT_ATTACHMENT_CHARS_RANGE[1]
    )
    max_chars_total: int = Field(
        ge=CHAT_ATTACHMENT_CHARS_RANGE[0], le=CHAT_ATTACHMENT_CHARS_RANGE[1]
    )


class ChatStarterSettingsUpdate(BaseModel):
    """How much recent activity shapes the home screen's starting points.

    Bounds mirror ``starter_settings.TRACE_COUNT_RANGE`` so the API rejects
    loudly what the file layer would silently clamp.
    """

    trace_count: int = Field(ge=STARTER_TRACE_COUNT_RANGE[0], le=STARTER_TRACE_COUNT_RANGE[1])


class MinerUSettingsUpdate(BaseModel):
    """MinerU document-parsing backend settings.

    ``api_token`` is tri-state: ``None`` keeps the stored token (the UI sends
    None when the user didn't edit the secret field), ``""`` clears it, and a
    non-empty string or string array replaces it. The GET payload never echoes
    the raw token.
    """

    mode: Literal["local", "cloud"] = "local"
    api_base_url: str = "https://mineru.net"
    api_token: Optional[str | list[str]] = None
    local_cli_path: str = ""
    model_download_source: Literal["huggingface", "modelscope"] = "huggingface"
    model_download_endpoint: str = ""
    model_version: Literal["pipeline", "vlm"] = "pipeline"
    language: str = "auto"
    enable_formula: bool = True
    enable_table: bool = True
    is_ocr: bool = False
    # Off by default → a local parse fails fast rather than silently pulling
    # multi-GB model weights on first run.
    allow_local_model_download: bool = False


class MinerUModelDownloadPayload(BaseModel):
    """One-click model download request (draft form values, like /test)."""

    model_type: Literal["pipeline", "vlm", "all"] = "pipeline"
    source: Literal["huggingface", "modelscope"] = "huggingface"
    endpoint: str = ""
    local_cli_path: str = ""


class DocumentParsingUpdate(BaseModel):
    """Document-parsing settings update (the multi-engine control panel).

    ``engine`` (when provided) switches the active parse engine. ``engines``
    carries partial per-engine updates merged over the stored slices. For the
    MinerU engine, ``api_token`` stays tri-state: omit it (or send ``None``) to
    keep the stored token, ``""`` clears it, a non-empty string replaces it.
    The MinerU engine's own knobs can also be edited via the legacy
    ``/mineru`` endpoints; both preserve the other engines' settings.
    """

    engine: Optional[str] = None
    engines: Optional[dict[str, dict]] = None


class DocumentParsingTest(BaseModel):
    """Readiness test for one engine (defaults to the active engine)."""

    engine: Optional[str] = None


class DoclingRemoteTest(BaseModel):
    """Draft Docling remote-server test. ``api_token`` is tri-state: ``None``
    falls back to the stored key, ``""`` clears it, a string supplies it (so
    the user can verify an unsaved key before saving)."""

    api_base_url: str = "http://localhost:5001"
    api_token: Optional[str] = None


class TikaRemoteTest(BaseModel):
    """Draft Tika server test. Tests the unsaved URL so the user can verify
    before saving."""

    server_url: str = "http://localhost:9998"


class DocumentParsingInstall(BaseModel):
    """One-click pip install of an optional parser engine's package(s)."""

    engine: str


def _invalidate_runtime_caches() -> None:
    """Force runtime clients/config to pick up the latest saved catalog.

    The LLM and embedding clients are process-wide singletons, so resetting
    them here will affect any user turn that is mid-flight on another worker.
    Admins issuing Apply during active sessions accept that trade-off; we log
    a WARNING so the cause is visible in the audit trail.
    """
    logger.warning(
        "Admin applied catalog; resetting global LLM/embedding clients. "
        "In-flight user turns may flip backend client mid-call."
    )
    from deeptutor.services.embedding.client import reset_embedding_client
    from deeptutor.services.llm.client import reset_llm_client

    clear_llm_config_cache()
    reset_llm_client()
    reset_embedding_client()


def load_ui_settings() -> dict[str, Any]:
    settings_file = _settings_file()
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as handle:
                saved = json.load(handle)
                # resolve_languages owns the legacy migration (a file predating
                # the UI/response split inherits its one language into both).
                merged = {**DEFAULT_UI_SETTINGS, **saved, **resolve_languages(saved)}
                # Filter persisted enabled_optional_tools to current
                # toggleable set so retired tool names can't leak into
                # the per-turn payload.
                merged["enabled_optional_tools"] = sanitize_enabled_tools(
                    merged.get("enabled_optional_tools")
                )
                return merged
        except Exception:
            pass
    return DEFAULT_UI_SETTINGS.copy()


def save_ui_settings(settings: dict[str, Any]) -> None:
    """Replace the whole stored UI settings document.

    Writes through ``atomic_update`` rather than opening the file here, so this
    module and the setup capability — which both write ``interface.json`` —
    share one lock and one atomic replace. A lock held by only one of two
    writers protects nothing: measured with the old direct write, six concurrent
    router saves alongside six capability writes lost every one of the router's.

    Prefer :func:`patch_ui_settings` for changing individual fields. This
    replaces the whole document, so a caller that builds it from
    ``load_ui_settings`` writes the merged defaults back as stored values and
    stops following later changes to any of them.
    """
    payload = dict(settings)
    atomic_update(_settings_file(), lambda _stored: payload)


def patch_ui_settings(**fields: Any) -> None:
    """Change individual UI fields without rewriting the rest of the document."""
    atomic_update(_settings_file(), lambda stored: {**stored, **fields})


def _require_settings_admin() -> None:
    if not get_current_user().is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Model configuration is managed by an administrator.",
        )


def _require_codex_oauth_actor() -> None:
    """Gate the Codex OAuth lifecycle: personal, not administrative.

    Every one of these endpoints acts on the *caller's own* credentials —
    ``get_codex_oauth_service()`` resolves the store, the model catalog, and
    the callback route from owner scope — so requiring an administrator was
    what left ordinary users unable to use Codex at all: an owner-bound
    profile is (correctly) never grantable, and they could not sign in for
    themselves either (#781).

    A partner is refused: it is a synthetic user whose owner is a real
    account, so letting one in would mean acting on that person's login —
    including signing them out. Partners inherit the owner's login at call
    time and need no lifecycle of their own.
    """
    from deeptutor.services.partners.scope import is_partner_user_id

    if is_partner_user_id(get_current_user().id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A partner uses the Codex login of the account that owns it.",
        )


def _codex_http_exception(error: CodexAuthError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={
            "code": error.code,
            "message": error.public_message,
        },
    )


def _provider_choices() -> dict[str, list[dict[str, Any]]]:
    """Build dropdown options for provider selection, keyed by service type."""
    from deeptutor.services.config.provider_runtime import (
        DEPRECATED_SEARCH_PROVIDERS,
        EMBEDDING_PROVIDERS,
        IMAGEGEN_PROVIDERS,
        SEARCH_PROVIDERS,
        STT_PROVIDERS,
        TTS_PROVIDERS,
        VIDEOGEN_PROVIDERS,
    )
    from deeptutor.services.provider_registry import PROVIDERS

    llm = sorted(
        [
            {
                "value": s.name,
                "label": (
                    "Custom (OpenAI API)"
                    if s.name == "custom"
                    else "Custom (Anthropic API)"
                    if s.name == "custom_anthropic"
                    else s.label
                ),
                "base_url": s.default_api_base,
                "auth_mode": s.auth_mode,
                "supports_wire_api_selection": s.supports_wire_api_selection,
                # Which protocols a profile on this vendor may pick, and the
                # vendor endpoint each one lives at when that differs.
                "api_formats": list(s.api_formats),
                "default_api_format": s.default_api_format,
                "base_urls": {
                    api_format: s.default_api_base_for(api_format)
                    for api_format in s.api_formats
                    if s.default_api_base_for(api_format)
                },
                # Legacy entries stay resolvable for stored catalogs but are
                # not offered for new profiles; the same thing is expressed
                # today as a provider plus an API format.
                "status": "legacy" if s.is_legacy else "supported",
            }
            for s in PROVIDERS
        ],
        key=lambda p: p["label"].lower(),
    )
    embedding = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_dim": str(spec.default_dim) if spec.default_dim else "",
            }
            for name, spec in EMBEDDING_PROVIDERS.items()
            if name != "custom_openai_sdk"
        ],
        key=lambda p: p["label"].lower(),
    )
    # Derived from SEARCH_PROVIDERS so the dropdown, the connection-field form
    # and the provider warnings the web app renders all follow the backend spec
    # table. No search provider ships a default base_url — only SearXNG takes
    # one, and it is the user's own instance.
    search = [
        {
            "value": name,
            "label": spec.label,
            "base_url": "",
            "requires_api_key": spec.requires_api_key,
            "requires_base_url": spec.requires_base_url,
            "soft_fallback": spec.soft_fallback,
            "status": "supported",
        }
        for name, spec in SEARCH_PROVIDERS.items()
    ]
    # Retired providers ride along marked rather than offered, so a stale
    # catalog can be told apart from a typo without a second name table in the
    # web app. The dropdown filters them out; only the warning text uses them.
    search += [
        {
            "value": name,
            "label": name,
            "base_url": "",
            "requires_api_key": False,
            "requires_base_url": False,
            "soft_fallback": True,
            "status": "deprecated",
        }
        for name in sorted(DEPRECATED_SEARCH_PROVIDERS)
    ]
    tts = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_model": spec.default_model,
                "default_voice": spec.default_voice,
            }
            for name, spec in TTS_PROVIDERS.items()
        ],
        key=lambda p: p["label"].lower(),
    )
    stt = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_model": spec.default_model,
            }
            for name, spec in STT_PROVIDERS.items()
        ],
        key=lambda p: p["label"].lower(),
    )
    imagegen = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_model": spec.default_model,
            }
            for name, spec in IMAGEGEN_PROVIDERS.items()
        ],
        key=lambda p: p["label"].lower(),
    )
    videogen = sorted(
        [
            {
                "value": name,
                "label": spec.label,
                "base_url": spec.default_api_base,
                "default_model": spec.default_model,
            }
            for name, spec in VIDEOGEN_PROVIDERS.items()
        ],
        key=lambda p: p["label"].lower(),
    )
    return {
        "llm": llm,
        # Same shape, same vendors: the task service stands in for the LLM.
        "task": llm,
        "embedding": embedding,
        "search": search,
        "tts": tts,
        "stt": stt,
        "imagegen": imagegen,
        "videogen": videogen,
    }


def _match_service_provider(
    provider: str,
    table: dict[str, Any],
) -> tuple[str, Any] | None:
    """Find *provider*'s entry in one service's provider table.

    Vendors are not named identically across tables — the LLM registry calls
    Alibaba's endpoint ``dashscope`` while the embedding table calls it
    ``aliyun`` — so an exact key miss falls back to the spec's own keywords
    rather than to a second hand-maintained name map.
    """
    if provider in table:
        return provider, table[provider]
    for name, spec in table.items():
        if provider in getattr(spec, "keywords", ()):
            return name, spec
    return None


def _connection_targets() -> list[dict[str, Any]]:
    """Which services one vendor credential can configure, and with what.

    The connection UI needs to answer "if I paste an OpenRouter key here, what
    does it get me?" — so this joins the six per-service provider tables on the
    vendor and reports, per service, the provider value and the prefills a
    profile created from that connection should start with. Derived rather than
    duplicated: adding a vendor to a service table is enough to make it
    connectable, and the web app never keeps a second copy of the tables.
    """
    from deeptutor.services.config.provider_runtime import (
        EMBEDDING_PROVIDERS,
        IMAGEGEN_PROVIDERS,
        STT_PROVIDERS,
        TTS_PROVIDERS,
        VIDEOGEN_PROVIDERS,
    )
    from deeptutor.services.provider_registry import PROVIDERS

    service_tables: dict[str, dict[str, Any]] = {
        "embedding": {k: v for k, v in EMBEDDING_PROVIDERS.items() if k != "custom_openai_sdk"},
        "tts": TTS_PROVIDERS,
        "stt": STT_PROVIDERS,
        "imagegen": IMAGEGEN_PROVIDERS,
        "videogen": VIDEOGEN_PROVIDERS,
    }

    targets: list[dict[str, Any]] = []
    for spec in PROVIDERS:
        # OAuth vendors sign in through their own flow; there is no key to
        # share, so offering them here would promise something untrue.
        if spec.is_oauth:
            continue
        services: dict[str, dict[str, Any]] = {
            "llm": {
                "provider": spec.name,
                "base_url": spec.default_api_base,
                "default_model": "",
            }
        }
        for service_name, table in service_tables.items():
            match = _match_service_provider(spec.name, table)
            if match is None:
                continue
            name, service_spec = match
            entry: dict[str, Any] = {
                "provider": name,
                "base_url": service_spec.default_api_base,
                "default_model": service_spec.default_model,
            }
            if service_name == "embedding":
                entry["default_dim"] = (
                    str(service_spec.default_dim) if service_spec.default_dim else ""
                )
            if service_name == "tts":
                entry["default_voice"] = service_spec.default_voice
            services[service_name] = entry
        targets.append(
            {
                "provider": spec.name,
                "label": (
                    "Custom (OpenAI API)"
                    if spec.name == "custom"
                    else "Custom (Anthropic API)"
                    if spec.name == "custom_anthropic"
                    else spec.label
                ),
                "default_base_url": spec.default_api_base,
                "services": services,
            }
        )
    return sorted(targets, key=lambda item: str(item["label"]).lower())


def _api_base_source(system: dict[str, Any]) -> str:
    if system.get("next_public_api_base_external"):
        return "next_public_api_base_external"
    if system.get("next_public_api_base"):
        return "next_public_api_base"
    return "default_backend_url"


def _network_settings_payload() -> dict[str, Any]:
    service = get_runtime_settings_service()
    file_system = service.load_system(include_process_overrides=False)
    effective_system = service.load_system(include_process_overrides=True)
    auth = service.load_auth(include_process_overrides=True)
    backend_url = f"http://localhost:{effective_system['backend_port']}"
    browser_api_base = (
        effective_system["next_public_api_base_external"]
        or effective_system["next_public_api_base"]
        or backend_url
    )
    cors_origins = normalize_origins(
        [effective_system["cors_origin"], effective_system["cors_origins"]]
    )
    auth_enabled = bool(auth["enabled"])
    cookie_secure = bool(auth["cookie_secure"])
    return {
        "settings": {
            "backend_port": file_system["backend_port"],
            "frontend_port": file_system["frontend_port"],
            "public_api_base": file_system["next_public_api_base_external"],
            "cors_origins": normalize_origins(
                [file_system["cors_origin"], file_system["cors_origins"]]
            ),
        },
        "effective": {
            "backend_url": backend_url,
            "frontend_url": f"http://localhost:{effective_system['frontend_port']}",
            "browser_api_base": browser_api_base,
            "api_base_source": _api_base_source(effective_system),
            "cors_mode": "explicit" if auth_enabled else "permissive",
            "cors_origins": cors_origins,
            "allow_remote_http_origins": not auth_enabled,
        },
        "auth": {
            "enabled": auth_enabled,
            "cookie_secure": cookie_secure,
            "cookie_samesite": "none" if cookie_secure else "lax",
            "cross_site_cookie_ready": bool(auth_enabled and cookie_secure),
        },
        "restart_required": True,
    }


@router.get("")
async def get_settings():
    user = get_current_user()
    if not user.is_admin:
        # Non-admins never see the catalog (provider URLs/keys); their model
        # choices come from /settings/llm-options (grant-filtered).
        return {"ui": load_ui_settings()}
    return {
        "ui": load_ui_settings(),
        "catalog": redact_catalog_secrets(get_model_catalog_service().load()),
        "providers": _provider_choices(),
        "connection_targets": _connection_targets(),
    }


@router.post("/providers/openai-codex/oauth/start")
async def start_openai_codex_oauth() -> dict[str, Any]:
    _require_codex_oauth_actor()
    try:
        return await get_codex_oauth_service().start_login()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.get("/providers/openai-codex/oauth/status")
async def get_openai_codex_oauth_status() -> dict[str, Any]:
    _require_codex_oauth_actor()
    try:
        return get_codex_oauth_service().public_status()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/oauth/cancel")
async def cancel_openai_codex_oauth() -> dict[str, Any]:
    _require_codex_oauth_actor()
    try:
        return await get_codex_oauth_service().cancel_login()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/oauth/logout")
async def logout_openai_codex_oauth() -> dict[str, Any]:
    _require_codex_oauth_actor()
    try:
        return await get_codex_oauth_service().logout()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.post("/providers/openai-codex/models/refresh")
async def refresh_openai_codex_models() -> dict[str, Any]:
    _require_codex_oauth_actor()
    try:
        return await get_codex_oauth_service().refresh_models()
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None


@router.get("/providers/codebuddy/auth/status")
async def get_codebuddy_auth_status() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codebuddy_auth_service().status()


@router.post("/providers/codebuddy/auth/start")
async def start_codebuddy_auth() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codebuddy_auth_service().start_login()


@router.post("/providers/codebuddy/auth/cancel")
async def cancel_codebuddy_auth() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codebuddy_auth_service().cancel_login()


@router.post("/providers/codebuddy/auth/logout")
async def logout_codebuddy_auth() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codebuddy_auth_service().logout()


@router.post("/providers/openai-codex/models/reasoning-effort")
async def update_openai_codex_reasoning_effort(
    payload: CodexReasoningEffortUpdate,
) -> dict[str, Any]:
    _require_codex_oauth_actor()
    try:
        status_payload = await get_codex_oauth_service().set_reasoning_effort(
            payload.model,
            payload.reasoning_effort,
        )
    except CodexAuthError as exc:
        raise _codex_http_exception(exc) from None
    # This writes the catalog the runtime resolves against, like every other
    # catalog write here — without it the next turn keeps the old effort until
    # something else happens to invalidate.
    _invalidate_runtime_caches()
    return status_payload


@router.get("/catalog")
async def get_catalog():
    _require_settings_admin()
    return {"catalog": redact_catalog_secrets(get_model_catalog_service().load())}


@router.get("/network")
async def get_network_settings():
    _require_settings_admin()
    return _network_settings_payload()


@router.put("/network")
async def update_network_settings(payload: NetworkSettingsUpdate):
    _require_settings_admin()
    service = get_runtime_settings_service()
    current = service.load_system(include_process_overrides=False)
    service.save_system(
        {
            **current,
            "backend_port": payload.backend_port,
            "frontend_port": payload.frontend_port,
            "next_public_api_base_external": payload.public_api_base.strip(),
            "cors_origin": "",
            "cors_origins": normalize_origins(payload.cors_origins),
        }
    )
    return _network_settings_payload()


def _chat_attachments_payload() -> dict[str, Any]:
    service = get_runtime_settings_service()
    stored = service.load_system(include_process_overrides=False)
    effective = service.load_system(include_process_overrides=True)
    max_total_bytes = int(effective["chat_attachment_max_total_mb"]) * 1024 * 1024
    return {
        "settings": {
            "max_file_mb": stored["chat_attachment_max_file_mb"],
            "max_total_mb": stored["chat_attachment_max_total_mb"],
            "max_chars_per_doc": stored["chat_attachment_max_chars_per_doc"],
            "max_chars_total": stored["chat_attachment_max_chars_total"],
        },
        "effective": {
            "max_file_bytes": int(effective["chat_attachment_max_file_mb"]) * 1024 * 1024,
            "max_total_bytes": max_total_bytes,
            "max_chars_per_doc": effective["chat_attachment_max_chars_per_doc"],
            "max_chars_total": effective["chat_attachment_max_chars_total"],
            "ws_max_size": compute_ws_max_size(max_total_bytes),
        },
        "bounds": {
            "max_file_mb": list(CHAT_ATTACHMENT_MAX_FILE_MB_RANGE),
            "max_total_mb": list(CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE),
            "chars": list(CHAT_ATTACHMENT_CHARS_RANGE),
        },
        # Size caps and char budgets are re-read on every message, but the WS
        # frame ceiling is fixed at process start — uploads bigger than the
        # old ceiling need a backend restart to actually go through.
        "restart_required_for_larger_uploads": True,
    }


@router.get("/chat-attachments")
async def get_chat_attachment_settings():
    """Chat attachment policy. Readable by any user — the composer needs the
    caps to gate file picks client-side; only the PUT is admin-gated."""
    return _chat_attachments_payload()


@router.get("/chat-starters")
async def get_chat_starter_settings():
    """How many recent activities shape the home screen's starting points.

    Per user and not admin-gated, unlike the attachment caps next door: this
    changes the size of one prompt built from the caller's own memory, not any
    resource other people share.
    """
    from deeptutor.services.settings.starter_settings import (
        TRACE_COUNT_RANGE,
        get_starter_settings,
    )

    return {"settings": get_starter_settings(), "bounds": {"trace_count": TRACE_COUNT_RANGE}}


@router.put("/chat-starters")
async def update_chat_starter_settings(payload: ChatStarterSettingsUpdate):
    from deeptutor.services.settings.starter_settings import (
        TRACE_COUNT_RANGE,
        save_starter_settings,
    )

    saved = save_starter_settings({"trace_count": payload.trace_count})
    return {"settings": saved, "bounds": {"trace_count": TRACE_COUNT_RANGE}}


@router.put("/chat-attachments")
async def update_chat_attachment_settings(payload: ChatAttachmentSettingsUpdate):
    _require_settings_admin()
    service = get_runtime_settings_service()
    current = service.load_system(include_process_overrides=False)
    service.save_system(
        {
            **current,
            "chat_attachment_max_file_mb": payload.max_file_mb,
            "chat_attachment_max_total_mb": payload.max_total_mb,
            "chat_attachment_max_chars_per_doc": payload.max_chars_per_doc,
            "chat_attachment_max_chars_total": payload.max_chars_total,
        }
    )
    return _chat_attachments_payload()


def _mineru_settings_payload() -> dict[str, Any]:
    """MinerU settings for the UI, with the API token redacted to a boolean.

    ``local_cli`` is a fast PATH probe (no subprocess) so the page can show
    install status at config time instead of failing at parse time; the
    definitive ``--version`` check runs behind the explicit Test button.
    """
    from deeptutor.services.parsing.engines.mineru.backend import local_cli_probe

    service = get_runtime_settings_service()
    settings = service.load_mineru(include_process_overrides=True)
    public = {key: value for key, value in settings.items() if key != "api_token"}
    return {
        "settings": public,
        "api_token_set": bool(settings.get("api_token")),
        "local_cli": local_cli_probe(str(settings.get("local_cli_path") or "")),
    }


def _document_parsing_payload() -> dict[str, Any]:
    """State for the Document Parsing settings page: active engine, all engine
    slices (MinerU token redacted), engine availability, and per-engine
    readiness (so the UI can surface the "models not downloaded" gate)."""
    from deeptutor.services.parsing.engines._install import (
        installable_engines,
        model_downloadable_engines,
    )
    from deeptutor.services.parsing.engines.factory import (
        get_parser,
        list_engines,
    )
    from deeptutor.services.parsing.engines.mineru.backend import local_cli_probe

    service = get_runtime_settings_service()
    full = service.load_document_parsing(include_process_overrides=True)
    engines = full.get("engines", {})

    redacted: dict[str, Any] = {}
    for name, slice_ in engines.items():
        clean = dict(slice_)
        clean.pop("api_token", None)
        redacted[name] = clean

    readiness: dict[str, Any] = {}
    available = list_engines()
    for entry in available:
        try:
            parser = get_parser(entry["id"])
            report = parser.is_ready(parser.resolve_config())
            readiness[entry["id"]] = {
                "ready": report.ready,
                "reason": report.reason,
                "message": report.message,
            }
        except Exception:  # pragma: no cover - defensive
            continue

    mineru_slice = engines.get("mineru", {})
    docling_slice = engines.get("docling", {})
    return {
        "engine": full.get("engine"),
        "engines": redacted,
        "available_engines": available,
        "readiness": readiness,
        # Engine ids that support one-click pip install / model download here.
        "installable": sorted(installable_engines()),
        "model_downloadable": sorted(model_downloadable_engines()),
        # MinerU-specific UI state (token presence + CLI probe).
        "mineru": {
            "api_token_set": bool(mineru_slice.get("api_token")),
            "local_cli": local_cli_probe(str(mineru_slice.get("local_cli_path") or "")),
        },
        # Docling UI state (token presence for remote mode).
        "docling": {
            "api_token_set": bool(docling_slice.get("api_token")),
        },
    }


@router.get("/mineru")
async def get_mineru_settings():
    _require_settings_admin()
    return _mineru_settings_payload()


@router.put("/mineru")
async def update_mineru_settings(payload: MinerUSettingsUpdate):
    _require_settings_admin()
    service = get_runtime_settings_service()
    current = service.load_mineru(include_process_overrides=False)
    # Tri-state token: None keeps the stored value, anything else replaces it.
    token = current.get("api_token", "")
    if payload.api_token is not None:
        token = (
            [value.strip() for value in payload.api_token if value.strip()]
            if isinstance(payload.api_token, list)
            else payload.api_token.strip()
        )
    service.save_mineru(
        {
            "mode": payload.mode,
            "api_base_url": payload.api_base_url,
            "api_token": token,
            "local_cli_path": payload.local_cli_path,
            "model_download_source": payload.model_download_source,
            "model_download_endpoint": payload.model_download_endpoint,
            "model_version": payload.model_version,
            "language": payload.language,
            "enable_formula": payload.enable_formula,
            "enable_table": payload.enable_table,
            "is_ocr": payload.is_ocr,
            "allow_local_model_download": payload.allow_local_model_download,
        }
    )
    return _mineru_settings_payload()


@router.get("/document-parsing")
async def get_document_parsing_settings():
    _require_settings_admin()
    return _document_parsing_payload()


@router.get("/readiness")
async def get_settings_readiness():
    """Return the value-free cross-setting capability readiness matrix."""

    _require_settings_admin()
    from deeptutor.services.config.readiness import build_settings_readiness

    return await build_settings_readiness()


@router.put("/document-parsing")
async def update_document_parsing_settings(payload: DocumentParsingUpdate):
    _require_settings_admin()
    service = get_runtime_settings_service()
    full = service.load_document_parsing(include_process_overrides=False)
    engines = {name: dict(slice_) for name, slice_ in full.get("engines", {}).items()}

    for name, update in (payload.engines or {}).items():
        if name not in engines:
            continue
        merged = dict(update or {})
        # Token tri-state for engines with a secret (MinerU, Docling remote):
        # omitted / None keeps the stored token; "" clears it; a string
        # replaces it.
        if "api_token" in (engines[name] or {}) and merged.get("api_token") is None:
            merged.pop("api_token", None)
        engines[name].update(merged)

    new_engine = payload.engine or full.get("engine")
    service.save_document_parsing({"engine": new_engine, "engines": engines})
    return _document_parsing_payload()


@router.post("/document-parsing/test")
async def test_document_parsing(payload: DocumentParsingTest):
    """Readiness test for an engine. For MinerU's deeper checks (live cloud
    token / CLI ``--version``) the UI uses ``/mineru/test``; this generic test
    covers engine availability + model readiness for all engines."""
    _require_settings_admin()
    from deeptutor.services.parsing.engines.factory import get_parser, is_engine_available

    service = get_runtime_settings_service()
    engine = payload.engine or service.load_document_parsing().get("engine") or ""
    if not is_engine_available(engine):
        return {"ok": False, "message": f"The '{engine}' parsing engine isn't installed."}
    try:
        parser = get_parser(engine)
        config = parser.resolve_config()
        report = parser.is_ready(config)
        # Remote engines get a live connectivity check (e.g. Docling Serve
        # /health) rather than a config-only readiness gate.
        verify = getattr(parser, "verify", None)
        if verify is not None and report.ready and callable(verify):
            ok, message = verify(config)
            return {"ok": ok, "message": message or ("Ready to parse." if ok else "Not ready.")}
    except Exception as exc:  # noqa: BLE001 - surface as a test result
        return {"ok": False, "message": str(exc)}
    return {
        "ok": report.ready,
        "message": report.message or ("Ready to parse." if report.ready else "Not ready."),
    }


@router.post("/document-parsing/docling/test")
async def test_docling_remote_connection(payload: DoclingRemoteTest):
    """Live connectivity check for the Docling remote-server draft values.
    Pings the server health + version endpoints and returns ``ok`` + a
    human-readable detail. Tests draft form values so the user can verify the
    URL/key before saving; falls back to the stored key when the secret field
    is untouched."""
    _require_settings_admin()
    from deeptutor.services.parsing.engines.docling.config import (
        DoclingConfig,
        resolve_docling_config,
    )
    from deeptutor.services.parsing.engines.docling.remote import verify_remote

    stored = resolve_docling_config()
    base_url = payload.api_base_url.strip().rstrip("/") or "http://localhost:5001"
    token = stored.api_token if payload.api_token is None else payload.api_token.strip()
    config = DoclingConfig(
        mode="remote",
        api_base_url=base_url,
        api_token=token,
        do_ocr=stored.do_ocr,
        do_table_structure=stored.do_table_structure,
    )
    ok, detail = await asyncio.to_thread(verify_remote, config)
    return {"ok": ok, "message": detail or ("Ready to parse." if ok else "Not ready.")}


@router.post("/document-parsing/tika/test")
async def test_tika_remote_connection(payload: TikaRemoteTest):
    """Live connectivity check for the Tika server draft URL. Pings ``/version``
    so the user can verify the URL before saving."""
    _require_settings_admin()
    from deeptutor.services.parsing.engines.tika.config import TikaConfig
    from deeptutor.services.parsing.engines.tika.remote import verify_remote

    server_url = payload.server_url.strip().rstrip("/") or "http://localhost:9998"
    config = TikaConfig(server_url=server_url)
    ok, detail = await asyncio.to_thread(verify_remote, config)
    return {"ok": ok, "message": detail or ("Ready to parse." if ok else "Not ready.")}


def _normalize_engine_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


@router.post("/document-parsing/install")
async def start_document_parsing_install(payload: DocumentParsingInstall):
    """Kick off a one-click ``pip install`` of an optional engine's package(s).

    Returns ``{ok, message}`` immediately; progress is polled via the shared job
    status endpoint. Only one job runs at a time (process-wide singleton). The
    engine must be in the install allow-list (``ENGINE_PIP_SPECS``)."""
    _require_settings_admin()
    from deeptutor.services.parsing.engines._install import (
        ENGINE_PIP_SPECS,
        get_background_job_manager,
    )

    engine = _normalize_engine_name(payload.engine)
    specs = ENGINE_PIP_SPECS.get(engine)
    if not specs:
        return {"ok": False, "message": f"No installable package for engine '{engine}'."}
    return get_background_job_manager().start_install(engine=engine, specs=specs)


@router.post("/document-parsing/models/download")
async def start_document_parsing_model_download(payload: DocumentParsingInstall):
    """Kick off a one-click model-weight download for an engine (e.g. Docling).

    Runs the engine's downloader console script (``docling-tools models
    download``) as a background subprocess; progress is polled via the shared job
    status endpoint. The engine must be in ``ENGINE_MODEL_DOWNLOADERS`` and its
    script reachable next to the server's python or on PATH."""
    _require_settings_admin()
    from deeptutor.services.parsing.engines._install import (
        get_background_job_manager,
        model_downloadable_engines,
        resolve_model_downloader,
    )

    engine = _normalize_engine_name(payload.engine)
    if engine not in model_downloadable_engines():
        return {"ok": False, "message": f"No model download for engine '{engine}'."}
    cmd = resolve_model_downloader(engine)
    if not cmd:
        return {
            "ok": False,
            "message": (
                f"The {engine} model downloader wasn't found. Reinstall the engine "
                f"(pip install deeptutor[parse-{engine}]) so its CLI is on PATH."
            ),
        }
    return get_background_job_manager().start_model_download(engine=engine, cmd=cmd)


@router.get("/document-parsing/job/status")
async def document_parsing_job_status(cursor: int = 0):
    _require_settings_admin()
    from deeptutor.services.parsing.engines._install import get_background_job_manager

    return get_background_job_manager().status(cursor)


@router.post("/document-parsing/job/cancel")
async def cancel_document_parsing_job():
    _require_settings_admin()
    from deeptutor.services.parsing.engines._install import get_background_job_manager

    return get_background_job_manager().cancel()


@router.post("/mineru/models/download")
async def start_mineru_models_download(payload: MinerUModelDownloadPayload):
    """Kick off a one-click model download via ``mineru-models-download``.

    Returns ``{ok, message}`` immediately; progress is polled via the status
    endpoint. Only one download runs at a time (process-wide singleton).
    """
    _require_settings_admin()
    from deeptutor.services.parsing.engines.mineru.models import (
        get_model_download_manager,
        resolve_models_downloader,
    )

    resolved = resolve_models_downloader(payload.local_cli_path)
    if not resolved["found"]:
        if resolved["path"]:
            message = (
                f"mineru-models-download not found next to the configured CLI "
                f"(expected {resolved['path']}). The configured install may be "
                "legacy magic-pdf — upgrade to MinerU >= 3.4.5 for one-click downloads."
            )
        else:
            message = (
                "mineru-models-download not found on the server PATH. Install "
                'current MinerU first (uv pip install -U "mineru[all]>=3.4.5") or set '
                "the CLI path."
            )
        return {"ok": False, "message": message}

    return get_model_download_manager().start(
        downloader=resolved["path"],
        model_type=payload.model_type,
        source=payload.source,
        endpoint=payload.endpoint,
    )


@router.get("/mineru/models/download/status")
async def mineru_models_download_status(cursor: int = 0):
    _require_settings_admin()
    from deeptutor.services.parsing.engines.mineru.models import get_model_download_manager

    return get_model_download_manager().status(cursor)


@router.post("/mineru/models/download/cancel")
async def cancel_mineru_models_download():
    _require_settings_admin()
    from deeptutor.services.parsing.engines.mineru.models import get_model_download_manager

    return get_model_download_manager().cancel()


@router.post("/mineru/test")
async def test_mineru_connection(payload: MinerUSettingsUpdate):
    """Validate the active backend. ``mode == "local"`` checks the CLI install
    (PATH probe + ``--version``); cloud mode validates the token against the
    live MinerU API (no parse quota consumed). Tests the draft form values so
    the user can verify before saving; falls back to the stored token when the
    secret field is untouched."""
    _require_settings_admin()
    from deeptutor.services.parsing.engines.mineru.cloud import verify_credentials
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError

    if payload.mode == "local":
        from deeptutor.services.parsing.engines.mineru.backend import (
            local_cli_probe,
            local_cli_version,
        )
        from deeptutor.services.parsing.engines.mineru.formats import (
            MIN_MINERU_VERSION,
            mineru_version_is_current,
        )

        probe = local_cli_probe(payload.local_cli_path)
        if not probe["found"]:
            if probe.get("source") == "configured":
                return {
                    "ok": False,
                    "message": (
                        f"Configured CLI path is not an executable file: {probe['path']}. "
                        "Fix the path or clear it to auto-detect from PATH."
                    ),
                }
            return {
                "ok": False,
                "message": (
                    "MinerU CLI not found on the server PATH. Install it "
                    '(uv pip install -U "mineru[all]>=3.4.5"), set an explicit CLI path, '
                    "or switch to cloud mode."
                ),
            }
        # For a configured path, run --version against the path itself (the
        # bare command name may not be on this process's PATH).
        version_target = (
            probe["path"] if probe.get("source") == "configured" else str(probe["command"])
        )
        version = await asyncio.to_thread(local_cli_version, version_target)
        if not mineru_version_is_current(version):
            detail = version or "an unknown version"
            return {
                "ok": False,
                "message": (
                    f"Local MinerU CLI reported {detail}. DeepTutor needs MinerU >= "
                    f"{MIN_MINERU_VERSION}; upgrade with "
                    f"`pip install -U 'mineru[all]>={MIN_MINERU_VERSION}'`."
                ),
            }
        return {
            "ok": True,
            "message": f"Local MinerU CLI detected: {probe['command']} ({version})",
        }

    service = get_runtime_settings_service()
    stored = service.load_mineru(include_process_overrides=False)
    token = stored.get("api_token", "")
    if payload.api_token is not None:
        token = (
            [value.strip() for value in payload.api_token if value.strip()]
            if isinstance(payload.api_token, list)
            else payload.api_token.strip()
        )
    config = MinerUConfig(
        mode="cloud",
        api_base_url=(payload.api_base_url or "").strip().rstrip("/") or "https://mineru.net",
        api_token=token,
        model_version=payload.model_version,
        language=payload.language or "auto",
        enable_formula=payload.enable_formula,
        enable_table=payload.enable_table,
        is_ocr=payload.is_ocr,
    )
    try:
        await asyncio.to_thread(verify_credentials, config)
    except MinerUError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 — report any provider error to the UI
        logger.exception("MinerU connectivity test failed")
        return {"ok": False, "message": f"Unexpected error: {exc}"}
    return {"ok": True, "message": "MinerU API token is valid."}


@router.get("/llm-options")
async def get_llm_options():
    if not get_current_user().is_admin:
        return allowed_llm_options()
    return list_llm_options(get_model_catalog_service().load())


@router.put("/catalog")
async def update_catalog(payload: CatalogPayload):
    _require_settings_admin()
    service = get_model_catalog_service()
    current = service.load()
    restored = restore_catalog_secrets(payload.catalog, current)
    proposed = reconcile_codex_catalog_update(current, restored)
    catalog = service.save(proposed)
    _invalidate_runtime_caches()
    return {"catalog": redact_catalog_secrets(catalog)}


@router.post("/apply/service")
async def apply_catalog_service(payload: CatalogServicePayload):
    """Apply one model service while leaving every other draft untouched.

    Provider dialogs use this narrower commit path for their Done action. A
    user may still have unrelated edits elsewhere in Settings, and closing an
    STT dialog must not silently promote those edits too.
    """

    _require_settings_admin()
    service = get_model_catalog_service()
    current = service.load()
    proposed = deepcopy(current)
    proposed.setdefault("services", {})[payload.service] = deepcopy(payload.config)
    restored = restore_catalog_secrets(proposed, current)
    reconciled = reconcile_codex_catalog_update(current, restored)
    runtime = service.apply(reconciled)
    catalog = service.load()

    # A previously saved draft contains a full catalog. Keep it, but advance
    # this one service to the value that is now live; otherwise reloading the
    # page would resurrect the pre-apply STT configuration over the live one.
    draft_service = get_settings_draft_service()
    stored_draft = draft_service.load()
    draft_catalog = stored_draft.get("catalog")
    if isinstance(draft_catalog, dict):
        draft_catalog.setdefault("services", {})[payload.service] = deepcopy(
            catalog["services"][payload.service]
        )
        stored_draft["catalog"] = None if draft_catalog == catalog else draft_catalog

    if is_empty_draft(stored_draft):
        draft_service.clear()
        public_draft = None
    else:
        public_draft = redact_draft(draft_service.save(stored_draft))

    _invalidate_runtime_caches()
    return {
        "message": f"{payload.service} settings applied to runtime.",
        "catalog": redact_catalog_secrets(catalog),
        "draft": public_draft,
        "runtime": runtime,
    }


@router.get("/draft")
async def get_settings_draft():
    """Return the unapplied draft, or nothing when there is none.

    The draft is deliberately invisible to every other read path: nothing that
    resolves runtime configuration looks here, which is the whole difference
    between saving a draft and applying it.
    """
    _require_settings_admin()
    draft = get_settings_draft_service().load()
    if is_empty_draft(draft):
        return {"draft": None}
    return {"draft": redact_draft(draft)}


@router.put("/draft")
async def update_settings_draft(payload: SettingsDraftPayload):
    _require_settings_admin()
    service = get_settings_draft_service()
    stored = service.load()
    merged = merge_draft_secrets(
        payload.model_dump(),
        stored,
        get_model_catalog_service().load(),
    )
    if is_empty_draft(merged):
        service.clear()
        return {"draft": None}
    saved = service.save(merged)
    return {"draft": redact_draft(saved)}


@router.delete("/draft")
async def discard_settings_draft():
    _require_settings_admin()
    get_settings_draft_service().clear()
    return {"draft": None}


@router.post("/apply")
async def apply_catalog(payload: CatalogPayload | None = None):
    """Move settings into the files the runtime reads, and clear the draft.

    With no body this promotes the stored draft's catalog, which is how the
    settings UI applies: credentials that only ever existed in a draft would
    otherwise have to round-trip through the browser as placeholders and come
    back resolving to the previous key.
    """
    _require_settings_admin()
    service = get_model_catalog_service()
    draft_service = get_settings_draft_service()
    current = service.load()
    if payload is not None:
        proposed = restore_catalog_secrets(payload.catalog, current)
    else:
        draft_catalog = draft_service.load().get("catalog")
        proposed = (
            restore_catalog_secrets(draft_catalog, current)
            if isinstance(draft_catalog, dict)
            else current
        )
    catalog = reconcile_codex_catalog_update(current, proposed)
    applied = service.apply(catalog)
    draft_service.clear()
    _invalidate_runtime_caches()
    return {
        "message": "Catalog applied to runtime settings.",
        "catalog": redact_catalog_secrets(service.load()),
        "runtime": applied,
    }


@router.post("/fetch-models")
async def fetch_models_from_provider(payload: FetchModelsPayload):
    """List the model IDs an OpenAI-compatible provider exposes.

    Thin HTTP surface over ``factory.fetch_models`` so the settings UI can
    populate a model picker from ``base_url`` + ``api_key`` instead of making
    the user type model IDs by hand.
    """
    _require_settings_admin()
    from deeptutor.services.llm.factory import fetch_models as fetch_llm_models

    base_url = (payload.base_url or "").strip()
    binding = (payload.binding or "").strip().lower() or "openai"
    if not base_url and binding != "codebuddy":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url is required for this provider.",
        )

    api_key = payload.api_key
    api_format = (payload.api_format or "").strip().lower()
    if payload.profile_id and (api_key == CATALOG_SECRET_MASK or not api_format):
        service = get_model_catalog_service().load().get("services", {}).get(payload.service, {})
        profile = next(
            (item for item in service.get("profiles", []) if item.get("id") == payload.profile_id),
            None,
        )
        if api_key == CATALOG_SECRET_MASK:
            api_key = profile.get("api_key") if profile else None
        if not api_format and profile:
            api_format = str(profile.get("api_format") or "")

    try:
        model_ids = await fetch_llm_models(binding, base_url, api_key, api_format or "auto")
    except Exception as exc:  # noqa: BLE001 — surface any provider error as 502
        logger.exception("Failed to fetch models from %s", base_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider request failed: {exc}",
        ) from exc

    return {"models": [{"id": model_id, "name": model_id} for model_id in model_ids]}


@router.post("/model-capabilities")
async def resolve_model_capabilities(payload: ModelCapabilitiesQuery):
    """What the built-in capability tables assume for one provider/model pair.

    The settings UI shows these as the value "Auto" resolves to next to each
    per-model override, so a user can see what they are overriding.
    """
    _require_settings_admin()
    from deeptutor.services.llm.capabilities import effective_capabilities

    binding = (payload.binding or "").strip().lower() or "openai"
    model = (payload.model or "").strip()
    return {
        "binding": binding,
        "model": model,
        "defaults": effective_capabilities(binding, model),
    }


@router.put("/theme")
async def update_theme(update: ThemeUpdate):
    patch_ui_settings(theme=update.theme)
    return {"theme": update.theme}


@router.put("/language")
async def update_language(update: LanguageUpdate):
    patch_ui_settings(language=update.language)
    return {"language": update.language}


@router.put("/voice-autoplay")
async def update_voice_autoplay(update: VoiceAutoplayUpdate):
    """Persist the global default for auto-playing chat replies via TTS.

    A personal UI preference (any authenticated user); the chat surface layers
    a per-session override on top of this value.
    """
    patch_ui_settings(voice_autoplay=update.voice_autoplay)
    return {"voice_autoplay": update.voice_autoplay}


@router.put("/chat-response-timeout")
async def update_chat_response_timeout(update: ChatResponseTimeoutUpdate):
    """Persist how long the chat UI waits for a turn event before timing out.

    A personal UI preference (any authenticated user). Slow tools like image /
    video generation can take longer than the old 60s default, so this is
    user-adjustable; the chat surface reads it client-side.
    """
    patch_ui_settings(chat_response_timeout=update.chat_response_timeout)
    return {"chat_response_timeout": update.chat_response_timeout}


# The UI preferences a page can need before it knows who is asking. All three
# describe the person's own presentation and output choices; none of them say
# anything about how the deployment is configured.
PRESESSION_UI_FIELDS = ("theme", "language", "response_language")


@public_router.get("/ui")
async def get_ui_settings():
    """Return the pre-session UI preferences: theme and the two languages.

    Public by design, which is why it is a narrow projection rather than the
    saved ``ui`` blob. The app shell — and the statically prerendered auth
    pages, which have no session at all — adopt the persisted languages here
    during bootstrap. Theme rides along so those pages can paint in the right
    one instead of flashing.

    Everything else under ``ui`` (sidebar_nav_order, enabled_optional_tools,
    chat_response_timeout, …) describes what the deployment has turned on, so
    it stays behind auth: read it from the ``ui`` key of GET /settings.
    """
    settings = load_ui_settings()
    return {field: settings.get(field) for field in PRESESSION_UI_FIELDS}


@router.put("/ui")
async def update_ui_settings(update: UISettingsUpdate):
    """Merge frontend partial update into current UI settings.

    Uses exclude_unset=True semantics so that only fields explicitly provided
    by the frontend override saved values. Fields not in the frontend payload
    (even if they equal the model defaults) are omitted from the merge.
    """
    dump = update.model_dump(exclude_unset=True)  # Only merge explicitly provided fields
    # Merged into the stored document, not into the defaults-merged view: saving
    # that view back would freeze today's defaults as this user's explicit
    # choices. The response keeps returning the merged view clients expect.
    patch_ui_settings(**dump)
    return load_ui_settings()


@router.post("/reset")
async def reset_settings():
    save_ui_settings(DEFAULT_UI_SETTINGS)
    return DEFAULT_UI_SETTINGS


@router.get("/themes")
async def get_themes():
    return {
        "themes": [
            {"id": "snow", "name": "Default"},
            {"id": "light", "name": "Cream"},
            {"id": "dark", "name": "Dark"},
            {"id": "glass", "name": "Glass"},
        ]
    }


@router.get("/sidebar")
async def get_sidebar_settings():
    current_ui = load_ui_settings()
    return {
        "description": current_ui.get(
            "sidebar_description", DEFAULT_UI_SETTINGS["sidebar_description"]
        ),
        "nav_order": current_ui.get("sidebar_nav_order", DEFAULT_UI_SETTINGS["sidebar_nav_order"]),
    }


@router.put("/sidebar/description")
async def update_sidebar_description(update: SidebarDescriptionUpdate):
    patch_ui_settings(sidebar_description=update.description)
    return {"description": update.description}


@router.put("/sidebar/nav-order")
async def update_sidebar_nav_order(update: SidebarNavOrderUpdate):
    patch_ui_settings(sidebar_nav_order=update.nav_order.model_dump())
    return {"nav_order": update.nav_order.model_dump()}


@router.put("/enabled-tools")
async def update_enabled_tools(update: EnabledToolsUpdate):
    sanitized = sanitize_enabled_tools(update.enabled_tools)
    patch_ui_settings(enabled_optional_tools=sanitized)
    return {"enabled_optional_tools": sanitized}


@router.post("/tests/{service}/start")
async def start_service_test(service: str, payload: CatalogPayload | None = None):
    _require_settings_admin()
    catalog = None
    if payload is not None:
        catalog_service = get_model_catalog_service()
        current = catalog_service.load()
        catalog = restore_catalog_secrets(payload.catalog, current)
        catalog = catalog_service.resolve_connections(catalog)
    run = get_config_test_runner().start(service, catalog)
    return {"run_id": run.id}


@router.get("/tests/{service}/{run_id}/events")
async def stream_service_test_events(service: str, run_id: str, request: Request):
    _require_settings_admin()
    runner = get_config_test_runner()
    run = runner.get(run_id)

    async def event_stream():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            events = run.snapshot(sent)
            if events:
                for event in events:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                sent += len(events)
                if events[-1]["type"] in {"completed", "failed"}:
                    return
            else:
                yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(0.35)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/tests/{service}/{run_id}/cancel")
async def cancel_service_test(service: str, run_id: str):
    _require_settings_admin()
    get_config_test_runner().cancel(run_id)
    return {"message": "Cancelled"}


@router.get("/tour/status")
async def tour_status():
    tour_cache = _tour_cache_file()
    if tour_cache.exists():
        try:
            cache = json.loads(tour_cache.read_text(encoding="utf-8"))
            return {
                "active": True,
                "status": cache.get("status", "unknown"),
                "launch_at": cache.get("launch_at"),
                "redirect_at": cache.get("redirect_at"),
            }
        except Exception:
            pass
    return {"active": False, "status": "none", "launch_at": None, "redirect_at": None}


class TourCompletePayload(BaseModel):
    catalog: dict[str, Any] | None = None
    test_results: dict[str, str] | None = None


@router.post("/tour/complete")
async def complete_tour(payload: TourCompletePayload | None = None):
    _require_settings_admin()
    service = get_model_catalog_service()
    current = service.load()
    catalog = (
        restore_catalog_secrets(payload.catalog, current)
        if payload and payload.catalog
        else current
    )
    applied = service.apply(catalog)
    _invalidate_runtime_caches()
    now = int(time.time())
    launch_at = now + 3
    redirect_at = now + 5

    tour_cache = _tour_cache_file()
    if tour_cache.exists():
        try:
            cache = json.loads(tour_cache.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
        cache["status"] = "completed"
        cache["launch_at"] = launch_at
        cache["redirect_at"] = redirect_at
        if payload and payload.test_results:
            cache["test_results"] = payload.test_results
        tour_cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    return {
        "status": "completed",
        "message": "Configuration saved. DeepTutor will restart shortly.",
        "launch_at": launch_at,
        "redirect_at": redirect_at,
        "runtime": applied,
    }


@router.post("/tour/reopen")
async def reopen_tour():
    return {
        "message": "Run the terminal setup guide from the project root to re-open the guided setup.",
        "command": "deeptutor init",
    }
