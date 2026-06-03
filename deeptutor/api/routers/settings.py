"""
Settings API Router
===================

UI preferences, configuration catalog management, and detailed streamed tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.model_access import allowed_llm_options, redacted_model_access
from deeptutor.services.config import (
    get_config_test_runner,
    get_model_catalog_service,
    get_runtime_settings_service,
)
from deeptutor.services.config.origins import normalize_origins
from deeptutor.services.embedding.client import reset_embedding_client
from deeptutor.services.llm.client import reset_llm_client
from deeptutor.services.llm.config import clear_llm_config_cache
from deeptutor.services.model_selection import list_llm_options
from deeptutor.services.path_service import get_path_service
from deeptutor.tools.builtin import USER_TOGGLEABLE_TOOL_NAMES

router = APIRouter()

TOUR_CACHE = None

UILanguage = Literal["zh", "en", "de"]


def _settings_file():
    return get_path_service().get_settings_file("interface")


def _tour_cache_file():
    if TOUR_CACHE is not None:
        return TOUR_CACHE
    return get_path_service().get_settings_dir() / ".tour_cache.json"


DEFAULT_SIDEBAR_NAV_ORDER = {
    "start": ["/", "/history", "/knowledge", "/notebook"],
    "learnResearch": ["/question", "/solver", "/research", "/co_writer"],
}

DEFAULT_UI_SETTINGS = {
    "theme": "light",
    "language": "en",
    "sidebar_description": "✨ Data Intelligence Lab @ HKU",
    "sidebar_nav_order": DEFAULT_SIDEBAR_NAV_ORDER,
    # User-toggleable chat tools. Default = all on; the /settings/tools page
    # is the single switchboard. Removed names (e.g. tools that ship later
    # and the user hasn't seen yet) are ignored on read; missing names from a
    # legacy file fall back to the default (all on).
    "enabled_optional_tools": list(USER_TOGGLEABLE_TOOL_NAMES),
}


class SidebarNavOrder(BaseModel):
    start: List[str]
    learnResearch: List[str]


class UISettings(BaseModel):
    theme: Literal["light", "dark", "glass", "snow"] = "light"
    language: UILanguage = "en"
    sidebar_description: Optional[str] = None
    sidebar_nav_order: Optional[SidebarNavOrder] = None


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark", "glass", "snow"]


class LanguageUpdate(BaseModel):
    language: UILanguage


class SidebarDescriptionUpdate(BaseModel):
    description: str


class SidebarNavOrderUpdate(BaseModel):
    nav_order: SidebarNavOrder


class EnabledToolsUpdate(BaseModel):
    enabled_tools: List[str]


class CatalogPayload(BaseModel):
    catalog: dict[str, Any]


class FetchModelsPayload(BaseModel):
    binding: str = ""
    base_url: str
    api_key: Optional[str] = None


class NetworkSettingsUpdate(BaseModel):
    backend_port: int = Field(ge=1, le=65535)
    frontend_port: int = Field(ge=1, le=65535)
    public_api_base: str = ""
    cors_origins: list[str] = Field(default_factory=list)


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
    clear_llm_config_cache()
    reset_llm_client()
    reset_embedding_client()


def load_ui_settings() -> dict[str, Any]:
    settings_file = _settings_file()
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as handle:
                saved = json.load(handle)
                merged = {**DEFAULT_UI_SETTINGS, **saved}
                # Filter persisted enabled_optional_tools to current
                # toggleable set so retired tool names can't leak into
                # the per-turn payload.
                merged["enabled_optional_tools"] = _sanitize_enabled_tools(
                    merged.get("enabled_optional_tools")
                )
                return merged
        except Exception:
            pass
    return DEFAULT_UI_SETTINGS.copy()


def _sanitize_enabled_tools(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(USER_TOGGLEABLE_TOOL_NAMES)
    allowed = set(USER_TOGGLEABLE_TOOL_NAMES)
    seen: set[str] = set()
    out: list[str] = []
    for name in value:
        if isinstance(name, str) and name in allowed and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def get_enabled_optional_tools() -> list[str]:
    """Return the user's currently-enabled toggleable tool names.

    Source of truth for the chat pipeline when a turn doesn't ship an
    explicit ``tools`` list.
    """
    return _sanitize_enabled_tools(load_ui_settings().get("enabled_optional_tools"))


def save_ui_settings(settings: dict[str, Any]) -> None:
    settings_file = _settings_file()
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)


def _require_settings_admin() -> None:
    if not get_current_user().is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Model configuration is managed by an administrator.",
        )


def _provider_choices() -> dict[str, list[dict[str, str]]]:
    """Build dropdown options for provider selection, keyed by service type."""
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
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
    search = [
        {"value": "none", "label": "None", "base_url": ""},
        {"value": "brave", "label": "Brave", "base_url": ""},
        {"value": "tavily", "label": "Tavily", "base_url": ""},
        {"value": "jina", "label": "Jina", "base_url": ""},
        {"value": "searxng", "label": "SearXNG", "base_url": ""},
        {"value": "duckduckgo", "label": "DuckDuckGo", "base_url": ""},
        {"value": "perplexity", "label": "Perplexity", "base_url": ""},
        {"value": "serper", "label": "Serper", "base_url": ""},
    ]
    return {"llm": llm, "embedding": embedding, "search": search}


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
        return {
            "ui": load_ui_settings(),
            "model_access": redacted_model_access(user.id),
        }
    return {
        "ui": load_ui_settings(),
        "catalog": get_model_catalog_service().load(),
        "providers": _provider_choices(),
    }


@router.get("/catalog")
async def get_catalog():
    _require_settings_admin()
    return {"catalog": get_model_catalog_service().load()}


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


@router.get("/llm-options")
async def get_llm_options():
    if not get_current_user().is_admin:
        return allowed_llm_options()
    return list_llm_options(get_model_catalog_service().load())


@router.put("/catalog")
async def update_catalog(payload: CatalogPayload):
    _require_settings_admin()
    catalog = get_model_catalog_service().save(payload.catalog)
    _invalidate_runtime_caches()
    return {"catalog": catalog}


@router.post("/apply")
async def apply_catalog(payload: CatalogPayload | None = None):
    _require_settings_admin()
    catalog = payload.catalog if payload is not None else get_model_catalog_service().load()
    applied = get_model_catalog_service().apply(catalog)
    _invalidate_runtime_caches()
    return {
        "message": "Catalog applied to runtime settings.",
        "catalog": get_model_catalog_service().load(),
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
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url is required.",
        )

    try:
        model_ids = await fetch_llm_models(binding, base_url, payload.api_key)
    except Exception as exc:  # noqa: BLE001 — surface any provider error as 502
        logger.exception("Failed to fetch models from %s", base_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider request failed: {exc}",
        ) from exc

    return {"models": [{"id": model_id, "name": model_id} for model_id in model_ids]}


@router.put("/theme")
async def update_theme(update: ThemeUpdate):
    current_ui = load_ui_settings()
    current_ui["theme"] = update.theme
    save_ui_settings(current_ui)
    return {"theme": update.theme}


@router.put("/language")
async def update_language(update: LanguageUpdate):
    current_ui = load_ui_settings()
    current_ui["language"] = update.language
    save_ui_settings(current_ui)
    return {"language": update.language}


@router.put("/ui")
async def update_ui_settings(update: UISettings):
    current_ui = load_ui_settings()
    current_ui.update(update.model_dump(exclude_none=True))
    save_ui_settings(current_ui)
    return current_ui


@router.post("/reset")
async def reset_settings():
    save_ui_settings(DEFAULT_UI_SETTINGS)
    return DEFAULT_UI_SETTINGS


@router.get("/themes")
async def get_themes():
    return {
        "themes": [
            {"id": "snow", "name": "Snow"},
            {"id": "light", "name": "Light"},
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
    current_ui = load_ui_settings()
    current_ui["sidebar_description"] = update.description
    save_ui_settings(current_ui)
    return {"description": update.description}


@router.put("/sidebar/nav-order")
async def update_sidebar_nav_order(update: SidebarNavOrderUpdate):
    current_ui = load_ui_settings()
    current_ui["sidebar_nav_order"] = update.nav_order.model_dump()
    save_ui_settings(current_ui)
    return {"nav_order": update.nav_order.model_dump()}


@router.put("/enabled-tools")
async def update_enabled_tools(update: EnabledToolsUpdate):
    sanitized = _sanitize_enabled_tools(update.enabled_tools)
    current_ui = load_ui_settings()
    current_ui["enabled_optional_tools"] = sanitized
    save_ui_settings(current_ui)
    return {"enabled_optional_tools": sanitized}


@router.post("/tests/{service}/start")
async def start_service_test(service: str, payload: CatalogPayload | None = None):
    _require_settings_admin()
    run = get_config_test_runner().start(service, payload.catalog if payload else None)
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
    catalog = payload.catalog if payload and payload.catalog else get_model_catalog_service().load()
    applied = get_model_catalog_service().apply(catalog)
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
