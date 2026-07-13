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
from deeptutor.multi_user.model_access import allowed_llm_options
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
    # "snow" is the pure-white neutral theme, shown as "Default" in the UI.
    "theme": "snow",
    "language": "en",
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
    sidebar_description: Optional[str] = None
    sidebar_nav_order: Optional[SidebarNavOrder] = None


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


class FetchModelsPayload(BaseModel):
    binding: str = ""
    base_url: str
    api_key: Optional[str] = None


class NetworkSettingsUpdate(BaseModel):
    backend_port: int = Field(ge=1, le=65535)
    frontend_port: int = Field(ge=1, le=65535)
    public_api_base: str = ""
    cors_origins: list[str] = Field(default_factory=list)


class MinerUSettingsUpdate(BaseModel):
    """MinerU PDF-parsing backend settings.

    ``api_token`` is tri-state: ``None`` keeps the stored token (the UI sends
    None when the user didn't edit the secret field), ``""`` clears it, and a
    non-empty string replaces it. The GET payload never echoes the raw token.
    """

    mode: Literal["local", "cloud"] = "local"
    api_base_url: str = "https://mineru.net"
    api_token: Optional[str] = None
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
    explicit ``tools`` list. Intersected with the admin grant whitelist so
    a restricted user's saved toggles can't resurrect a revoked tool.
    """
    from deeptutor.multi_user.tool_access import allowed_optional_tools

    enabled = _sanitize_enabled_tools(load_ui_settings().get("enabled_optional_tools"))
    allowed = allowed_optional_tools()
    if allowed is not None:
        enabled = [name for name in enabled if name in allowed]
    return enabled


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
    from deeptutor.services.config.provider_runtime import (
        EMBEDDING_PROVIDERS,
        IMAGEGEN_PROVIDERS,
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
        "embedding": embedding,
        "search": search,
        "tts": tts,
        "stt": stt,
        "imagegen": imagegen,
        "videogen": videogen,
    }


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
        if not entry["available"]:
            continue
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
        token = payload.api_token.strip()
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
        # MinerU token tri-state: omitted / None keeps the stored token.
        if name == "mineru" and merged.get("api_token") is None:
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
        report = parser.is_ready(parser.resolve_config())
    except Exception as exc:  # noqa: BLE001 - surface as a test result
        return {"ok": False, "message": str(exc)}
    return {
        "ok": report.ready,
        "message": report.message or ("Ready to parse." if report.ready else "Not ready."),
    }


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
                "magic-pdf 1.x — upgrade to MinerU 2.x for one-click downloads."
            )
        else:
            message = (
                "mineru-models-download not found on the server PATH. Install "
                'MinerU 2.x first (uv pip install -U "mineru[core]") or set the CLI path.'
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
                    '(uv pip install -U "mineru[core]"), set an explicit CLI path, '
                    "or switch to cloud mode."
                ),
            }
        # For a configured path, run --version against the path itself (the
        # bare command name may not be on this process's PATH).
        version_target = (
            probe["path"] if probe.get("source") == "configured" else str(probe["command"])
        )
        version = await asyncio.to_thread(local_cli_version, version_target)
        detail = version or f"at {probe['path']}"
        return {
            "ok": True,
            "message": f"Local MinerU CLI detected: {probe['command']} ({detail})",
        }

    service = get_runtime_settings_service()
    stored = service.load_mineru(include_process_overrides=False)
    token = stored.get("api_token", "") if payload.api_token is None else payload.api_token.strip()
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


@router.put("/voice-autoplay")
async def update_voice_autoplay(update: VoiceAutoplayUpdate):
    """Persist the global default for auto-playing chat replies via TTS.

    A personal UI preference (any authenticated user); the chat surface layers
    a per-session override on top of this value.
    """
    current_ui = load_ui_settings()
    current_ui["voice_autoplay"] = update.voice_autoplay
    save_ui_settings(current_ui)
    return {"voice_autoplay": update.voice_autoplay}


@router.put("/chat-response-timeout")
async def update_chat_response_timeout(update: ChatResponseTimeoutUpdate):
    """Persist how long the chat UI waits for a turn event before timing out.

    A personal UI preference (any authenticated user). Slow tools like image /
    video generation can take longer than the old 60s default, so this is
    user-adjustable; the chat surface reads it client-side.
    """
    current_ui = load_ui_settings()
    current_ui["chat_response_timeout"] = update.chat_response_timeout
    save_ui_settings(current_ui)
    return {"chat_response_timeout": update.chat_response_timeout}


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
