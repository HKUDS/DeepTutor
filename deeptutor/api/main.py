from contextlib import asynccontextmanager
import logging
import sys

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from deeptutor.logging import configure_logging
from deeptutor.services.config import (
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    load_auth_settings,
    load_system_settings,
)
from deeptutor.services.config.origins import normalize_origins
from deeptutor.services.path_service import get_path_service

ensure_runtime_settings_files()
export_runtime_settings_to_env(overwrite=True)
configure_logging()
logger = logging.getLogger(__name__)


class _SuppressWsNoise(logging.Filter):
    """Suppress noisy uvicorn logs for WebSocket connection churn."""

    _SUPPRESSED = ("connection open", "connection closed")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(f in msg for f in self._SUPPRESSED)


logging.getLogger("uvicorn.error").addFilter(_SuppressWsNoise())

CONFIG_DRIFT_ERROR_TEMPLATE = (
    "Configuration Drift Detected: Capability tool references {drift} are not "
    "registered in the runtime tool registry. Register the missing tools or "
    "remove the stale tool names from the capability manifests."
)


class SafeOutputStaticFiles(StaticFiles):
    """Static file mount that only exposes explicitly whitelisted artifacts."""

    def __init__(self, *args, path_service, **kwargs):
        super().__init__(*args, **kwargs)
        self._path_service = path_service

    async def get_response(self, path: str, scope):
        if not self._path_service.is_public_output_path(path):
            raise HTTPException(status_code=404, detail="Output not found")
        return await super().get_response(path, scope)


def validate_tool_consistency():
    """
    Validate that capability manifests only reference tools that are actually
    registered in the runtime ``ToolRegistry``.
    """
    try:
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        capability_registry = get_capability_registry()
        tool_registry = get_tool_registry()
        available_tools = set(tool_registry.list_tools())

        referenced_tools = set()
        for manifest in capability_registry.get_manifests():
            referenced_tools.update(manifest.get("tools_used", []) or [])

        drift = referenced_tools - available_tools
        if drift:
            raise RuntimeError(CONFIG_DRIFT_ERROR_TEMPLATE.format(drift=drift))
    except RuntimeError:
        logger.exception("Configuration validation failed")
        raise
    except Exception:
        logger.exception("Failed to load configuration for validation")
        raise


def _build_cors_settings() -> dict[str, object]:
    """Build CORS settings for both localhost and remote Docker deployments."""
    system_settings = load_system_settings()
    auth_settings = load_auth_settings()
    frontend_port = str(system_settings["frontend_port"])
    extra_origins = normalize_origins(
        [system_settings["cors_origin"], system_settings["cors_origins"]]
    )
    origins = [
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    for origin in extra_origins:
        if origin not in origins:
            origins.append(origin)

    # Auth is disabled by default. In that local/single-user mode, mirror the
    # pre-v1.3.8 behavior and allow remote Docker/LAN origins out of the box.
    # When auth is enabled, require explicit CORS_ORIGIN(S) for credentialed
    # cross-origin requests.
    allow_origin_regex = None if auth_settings["enabled"] else r"https?://.*"
    mode = "explicit" if auth_settings["enabled"] else "permissive"
    return {
        "allow_origins": origins,
        "allow_origin_regex": allow_origin_regex,
        "mode": mode,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle management
    Gracefully handle startup and shutdown events, avoid CancelledError
    """
    # Execute on startup
    logger.info("Application startup")

    # Validate configuration consistency
    validate_tool_consistency()

    # Initialize LLM client early so OPENAI_* env vars are available before
    # any downstream provider integrations start.
    try:
        from deeptutor.services.llm import get_llm_client

        llm_client = get_llm_client()
        logger.info(f"LLM client initialized: model={llm_client.config.model}")
    except Exception as e:
        logger.warning(f"Failed to initialize LLM client at startup: {e}")

    try:
        from deeptutor.events.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.start()
        logger.info("EventBus started")
    except Exception as e:
        logger.warning(f"Failed to start EventBus: {e}")

    try:
        from deeptutor.services.partners import get_partner_manager

        await get_partner_manager().auto_start_partners()
    except Exception as e:
        logger.warning(f"Failed to auto-start partners: {e}")

    try:
        from deeptutor.services.cron import get_cron_service

        await get_cron_service().start()
    except Exception as e:
        logger.warning(f"Failed to start cron service: {e}")

    # Ping PocketBase if configured — logs a warning (not an error) if unreachable
    try:
        from deeptutor.services.pocketbase_client import ping_pocketbase

        await ping_pocketbase()
    except Exception as e:
        logger.warning(f"PocketBase startup check failed: {e}")

    # Migrate any v1 memory files (PROFILE.md / SUMMARY.md) into a
    # backup folder so the v2 three-layer subsystem starts clean.
    try:
        from deeptutor.services.memory import (
            migrate_partner_surface_if_needed,
            migrate_v1_if_needed,
        )

        backup = migrate_v1_if_needed()
        if backup is not None:
            logger.info("v1 memory archived to %s", backup)
        # Rename the legacy ``tutorbot`` memory surface (footnote refs, L2
        # doc, snapshot/trace dirs, L3 meta keys) to ``partner``.
        migrate_partner_surface_if_needed()
    except Exception as e:
        logger.warning(f"v1 memory migration failed: {e}")

    yield

    # Execute on shutdown
    logger.info("Application shutdown")

    # Stop cron scheduler
    try:
        from deeptutor.services.cron import get_cron_service

        await get_cron_service().stop()
    except Exception as e:
        logger.warning(f"Failed to stop cron service: {e}")

    # Stop partners
    try:
        from deeptutor.services.partners import get_partner_manager

        await get_partner_manager().stop_all(preserve_auto_start=True)
        logger.info("Partners stopped")
    except Exception as e:
        logger.warning(f"Failed to stop partners: {e}")

    # Close MCP server connections. Each one owns an AsyncExitStack inside its
    # own task, so they must be torn down here rather than left to interpreter
    # exit (stdio servers would otherwise leak child processes).
    try:
        from deeptutor.services.mcp import get_mcp_manager

        await get_mcp_manager().shutdown()
        logger.info("MCP connections closed")
    except Exception as e:
        logger.warning(f"Failed to close MCP connections: {e}")

    # Close pooled LLM SDK clients so their keep-alive sockets and transports
    # are released deterministically instead of waiting for interpreter GC.
    try:
        from deeptutor.services.llm.provider_factory import close_runtime_provider_pool

        await close_runtime_provider_pool()
        logger.info("LLM provider pool closed")
    except Exception as e:
        logger.warning(f"Failed to close LLM provider pool: {e}")

    try:
        from deeptutor.core.agentic.client import close_agentic_client_pool

        await close_agentic_client_pool()
        logger.info("Agentic LLM client pool closed")
    except Exception as e:
        logger.warning(f"Failed to close agentic LLM client pool: {e}")

    # Stop EventBus
    try:
        from deeptutor.events.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.stop()
        logger.info("EventBus stopped")
    except Exception as e:
        logger.warning(f"Failed to stop EventBus: {e}")


app = FastAPI(
    title="DeepTutor API",
    version="1.0.0",
    lifespan=lifespan,
    # Disable automatic trailing slash redirects to prevent protocol downgrade issues
    # when deployed behind HTTPS reverse proxies (e.g., nginx).
    # Without this, FastAPI's 307 redirects may change HTTPS to HTTP.
    # See: https://github.com/HKUDS/DeepTutor/issues/112
    redirect_slashes=False,
)

# Access logging is funneled through this one middleware. uvicorn's own
# per-request access log is disabled on every launch path (run_server.py via
# access_log=False; the launcher and Docker via `--no-access-log`), so routine
# 200s — the chatty frontend polling of /settings, /tools, /knowledge/list,
# etc. — never reach the logs. Only non-200s are surfaced, since those are the
# ones worth seeing.
#
# The `deeptutor.access` logger gets its own INFO stdout handler rather than
# leaning on the root handlers: the root console handler runs at the global log
# level (WARNING by default), which would swallow these INFO access lines.
# propagate=False keeps them from also printing through root if the global
# level is ever lowered to INFO/DEBUG.
_access_logger = logging.getLogger("deeptutor.access")
if not any(getattr(h, "_deeptutor_access_handler", False) for h in _access_logger.handlers):
    _access_handler = logging.StreamHandler(sys.stdout)
    _access_handler.setLevel(logging.INFO)
    _access_handler.setFormatter(logging.Formatter("%(message)s"))
    _access_handler._deeptutor_access_handler = True  # type: ignore[attr-defined]
    _access_logger.addHandler(_access_handler)
    _access_logger.setLevel(logging.INFO)
    _access_logger.propagate = False


@app.middleware("http")
async def selective_access_log(request, call_next):
    response = await call_next(request)
    if response.status_code != 200:
        _access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            request.client.host if request.client else "-",
            request.method,
            request.url.path,
            request.scope.get("http_version", "1.1"),
            response.status_code,
        )
    return response


_cors_settings = _build_cors_settings()
logger.info(
    "CORS configured: mode=%s allow_origins=%s allow_origin_regex=%s",
    _cors_settings["mode"],
    _cors_settings["allow_origins"],
    _cors_settings["allow_origin_regex"],
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_settings["allow_origins"],
    allow_origin_regex=_cors_settings["allow_origin_regex"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount a filtered view over user outputs.
# Only whitelisted artifact paths are readable through the static handler.
path_service = get_path_service()
user_dir = path_service.get_public_outputs_root()

# Initialize user directories on startup
try:
    from deeptutor.services.setup import init_user_directories

    init_user_directories()
except Exception:
    # Fallback: just create the main directory if it doesn't exist
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

app.mount(
    "/api/outputs",
    SafeOutputStaticFiles(directory=str(user_dir), path_service=path_service),
    name="outputs",
)

# Import routers only after runtime settings are initialized.
# Some router modules load YAML settings at import time.
from deeptutor.api.routers import (
    agent_config,
    attachments,
    auth,
    book,
    capabilities_settings,
    chat,
    co_writer,
    dashboard,
    imports,
    knowledge,
    mastery_path,
    mcp_settings,
    memory,
    notebook,
    partners,
    personas,
    plugins_api,
    question,
    question_notebook,
    quiz_judge,
    sessions,
    settings,
    skills,
    space_cli_apps,
    space_mcp,
    subagents,
    system,
    unified_ws,
    voice,
)
from deeptutor.api.routers import (
    tools as tools_router,
)
from deeptutor.multi_user.router import router as multi_user_router  # noqa: E402

# Auth router is public — login/logout/register/status require no token
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])

# All other routers require a valid session when AUTH_ENABLED=true.
# require_auth is a no-op when AUTH_ENABLED=false, so this is safe for local use.
from deeptutor.api.routers.auth import require_admin, require_auth  # noqa: E402

_auth = [Depends(require_auth)]
# Partner data is anchored at the admin workspace (data/partners) and shared
# process-wide, so management is admin-gated in multi-user deployments
# (single-user local runs are implicitly admin — no behaviour change there).
_admin = [Depends(require_admin)]

app.include_router(
    multi_user_router,
    prefix="/api/v1/multi-user",
    tags=["multi-user"],
    dependencies=_auth,
)

app.include_router(chat.router, prefix="/api/v1", tags=["chat"], dependencies=_auth)
app.include_router(
    question.router, prefix="/api/v1/question", tags=["question"], dependencies=_auth
)
app.include_router(
    knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"], dependencies=_auth
)
app.include_router(imports.router, prefix="/api/v1/imports", tags=["imports"], dependencies=_auth)
app.include_router(
    dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=_auth
)
app.include_router(
    mastery_path.router,
    prefix="/api/v1/learning",
    tags=["mastery-path"],
    dependencies=_auth,
)
app.include_router(
    co_writer.router, prefix="/api/v1/co_writer", tags=["co_writer"], dependencies=_auth
)
app.include_router(
    notebook.router, prefix="/api/v1/notebook", tags=["notebook"], dependencies=_auth
)
app.include_router(book.router, prefix="/api/v1/book", tags=["book"], dependencies=_auth)
app.include_router(memory.router, prefix="/api/v1/memory", tags=["memory"], dependencies=_auth)
app.include_router(
    capabilities_settings.router,
    prefix="/api/v1/capabilities",
    tags=["capabilities"],
    dependencies=_auth,
)
app.include_router(
    sessions.router, prefix="/api/v1/sessions", tags=["sessions"], dependencies=_auth
)
app.include_router(
    question_notebook.router,
    prefix="/api/v1/question-notebook",
    tags=["question-notebook"],
    dependencies=_auth,
)
# Public UI-settings read (auth pages bootstrap the interface language
# before a session exists, so GET /api/v1/settings/ui must not be gated
# by _auth). Mounted first so the path resolves here, not on the gated
# settings router below.
app.include_router(
    settings.public_router,
    prefix="/api/v1/settings",
    tags=["settings"],
)
app.include_router(
    settings.router, prefix="/api/v1/settings", tags=["settings"], dependencies=_auth
)
app.include_router(
    mcp_settings.router,
    prefix="/api/v1/settings/mcp",
    tags=["mcp-settings"],
    dependencies=_auth,
)
# Per-user MCP servers. Deliberately only ``_auth``: the router's own routes
# resolve the owner server-side, and everything a non-admin can reach through it
# is remote-transport-only (see the module docstring). The admin registry above
# keeps its own ``require_admin``.
app.include_router(
    space_mcp.router,
    prefix="/api/v1/space/mcp",
    tags=["space-mcp"],
    dependencies=_auth,
)
# CLI apps. Only ``_auth`` here as well, but for a different reason: the two
# routes that install or remove an app carry their own ``require_admin``, and
# what is left for an ordinary account is reading the catalog and toggling its
# own preference among apps an administrator already granted it.
app.include_router(
    space_cli_apps.router,
    prefix="/api/v1/space/cli-apps",
    tags=["space-cli-apps"],
    dependencies=_auth,
)
app.include_router(skills.router, prefix="/api/v1/skills", tags=["skills"], dependencies=_auth)
app.include_router(
    subagents.router, prefix="/api/v1/subagents", tags=["subagents"], dependencies=_auth
)
app.include_router(
    personas.router, prefix="/api/v1/personas", tags=["personas"], dependencies=_auth
)
app.include_router(tools_router.router, prefix="/api/v1/tools", tags=["tools"], dependencies=_auth)
app.include_router(system.router, prefix="/api/v1/system", tags=["system"], dependencies=_auth)
app.include_router(voice.router, prefix="/api/v1/voice", tags=["voice"], dependencies=_auth)
app.include_router(
    plugins_api.router, prefix="/api/v1/plugins", tags=["plugins"], dependencies=_auth
)
app.include_router(
    agent_config.router, prefix="/api/v1/agent-config", tags=["agent-config"], dependencies=_auth
)
app.include_router(
    partners.router, prefix="/api/v1/partners", tags=["partners"], dependencies=_admin
)
app.include_router(
    attachments.router,
    prefix="/api/attachments",
    tags=["attachments"],
    dependencies=_auth,
)

# Unified WebSocket endpoint — auth is checked inside the handler (WebSockets
# cannot use FastAPI dependencies in the standard way)
app.include_router(unified_ws.router, prefix="/api/v1", tags=["unified-ws"])

# Quiz AI-judge WebSocket — same caveat as unified_ws above; auth is checked
# inside the handler so the WS upgrade isn't rejected by an HTTP-style dep.
app.include_router(quiz_judge.router, prefix="/api/v1", tags=["quiz-judge"])


@app.get("/")
async def root():
    return {"message": "Welcome to DeepTutor API"}


if __name__ == "__main__":
    from deeptutor.api.run_server import main as run_server_main

    run_server_main()
