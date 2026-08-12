from contextlib import asynccontextmanager
import logging
import sys

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


def validate_tool_consistency():
    """Validate that capability manifests only reference registered tools."""
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
    allow_origin_regex = None if auth_settings["enabled"] else r"https?://.*"
    mode = "explicit" if auth_settings["enabled"] else "permissive"
    return {"allow_origins": origins, "allow_origin_regex": allow_origin_regex, "mode": mode}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    logger.info("Application startup")
    validate_tool_consistency()
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
    try:
        from deeptutor.services.pocketbase_client import ping_pocketbase
        await ping_pocketbase()
    except Exception as e:
        logger.warning(f"PocketBase startup check failed: {e}")
    try:
        from deeptutor.services.memory import migrate_partner_surface_if_needed, migrate_v1_if_needed
        backup = migrate_v1_if_needed()
        if backup is not None:
            logger.info("v1 memory archived to %s", backup)
        migrate_partner_surface_if_needed()
    except Exception as e:
        logger.warning(f"v1 memory migration failed: {e}")
    yield
    logger.info("Application shutdown")
    try:
        from deeptutor.services.cron import get_cron_service
        await get_cron_service().stop()
    except Exception as e:
        logger.warning(f"Failed to stop cron service: {e}")
    try:
        from deeptutor.services.partners import get_partner_manager
        await get_partner_manager().stop_all(preserve_auto_start=True)
    except Exception as e:
        logger.warning(f"Failed to stop partners: {e}")
    try:
        from deeptutor.services.mcp import get_mcp_manager
        await get_mcp_manager().shutdown()
    except Exception as e:
        logger.warning(f"Failed to close MCP connections: {e}")
    try:
        from deeptutor.services.llm.provider_factory import close_runtime_provider_pool
        await close_runtime_provider_pool()
    except Exception as e:
        logger.warning(f"Failed to close pooled LLM clients: {e}")
    try:
        from deeptutor.core.agentic.client import close_agentic_client_pool
        await close_agentic_client_pool()
    except Exception as e:
        logger.warning(f"Failed to close agentic LLM clients: {e}")
    try:
        from deeptutor.events.event_bus import get_event_bus
        await get_event_bus().stop()
    except Exception as e:
        logger.warning(f"Failed to stop EventBus: {e}")


app = FastAPI(title="DeepTutor API", version="1.0.0", lifespan=lifespan, redirect_slashes=False)

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_settings["allow_origins"],
    allow_origin_regex=_cors_settings["allow_origin_regex"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from deeptutor.services.setup import init_user_directories
    init_user_directories()
except Exception:
    user_dir = get_path_service().get_public_outputs_root()
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

from deeptutor.api.routers import (
    agent_config, attachments, auth, book, capabilities_settings, chat, co_writer,
    dashboard, guruai, imports, knowledge, mastery_path, mcp_settings, memory,
    notebook, outputs, partners, personas, plugins_api, question, question_notebook,
    quiz_judge, sessions, settings, skills, space_cli_apps, space_mcp, subagents,
    system, unified_ws, voice,
)
from deeptutor.api.routers import tools as tools_router
from deeptutor.multi_user.router import router as multi_user_router

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(outputs.router, prefix="/api/outputs", tags=["outputs"])
from deeptutor.api.routers.auth import require_admin, require_auth
_auth = [Depends(require_auth)]
_admin = [Depends(require_admin)]

app.include_router(multi_user_router, prefix="/api/v1/multi-user", tags=["multi-user"], dependencies=_auth)
app.include_router(chat.router, prefix="/api/v1", tags=["chat"], dependencies=_auth)
app.include_router(question.router, prefix="/api/v1/question", tags=["question"], dependencies=_auth)
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"], dependencies=_auth)
app.include_router(imports.router, prefix="/api/v1/imports", tags=["imports"], dependencies=_auth)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=_auth)
app.include_router(mastery_path.router, prefix="/api/v1/learning", tags=["mastery-path"], dependencies=_auth)
app.include_router(co_writer.router, prefix="/api/v1/co_writer", tags=["co_writer"], dependencies=_auth)
app.include_router(notebook.router, prefix="/api/v1/notebook", tags=["notebook"], dependencies=_auth)
app.include_router(book.router, prefix="/api/v1/book", tags=["book"], dependencies=_auth)
app.include_router(memory.router, prefix="/api/v1/memory", tags=["memory"], dependencies=_auth)
app.include_router(capabilities_settings.router, prefix="/api/v1/capabilities", tags=["capabilities"], dependencies=_auth)
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"], dependencies=_auth)
app.include_router(question_notebook.router, prefix="/api/v1/question-notebook", tags=["question-notebook"], dependencies=_auth)
app.include_router(settings.public_router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"], dependencies=_auth)
app.include_router(mcp_settings.router, prefix="/api/v1/settings/mcp", tags=["mcp-settings"], dependencies=_auth)
app.include_router(space_mcp.router, prefix="/api/v1/space/mcp", tags=["space-mcp"], dependencies=_auth)
app.include_router(space_cli_apps.router, prefix="/api/v1/space/cli-apps", tags=["space-cli-apps"], dependencies=_auth)
app.include_router(skills.router, prefix="/api/v1/skills", tags=["skills"], dependencies=_auth)
app.include_router(subagents.router, prefix="/api/v1/subagents", tags=["subagents"], dependencies=_auth)
app.include_router(personas.router, prefix="/api/v1/personas", tags=["personas"], dependencies=_auth)
app.include_router(tools_router.router, prefix="/api/v1/tools", tags=["tools"], dependencies=_auth)
app.include_router(system.router, prefix="/api/v1/system", tags=["system"], dependencies=_auth)
app.include_router(voice.router, prefix="/api/v1/voice", tags=["voice"], dependencies=_auth)
app.include_router(plugins_api.router, prefix="/api/v1/plugins", tags=["plugins"], dependencies=_auth)
app.include_router(agent_config.router, prefix="/api/v1/agent-config", tags=["agent-config"], dependencies=_auth)
app.include_router(partners.router, prefix="/api/v1/partners", tags=["partners"], dependencies=_admin)
app.include_router(attachments.router, prefix="/api/attachments", tags=["attachments"], dependencies=_auth)
app.include_router(guruai.router, prefix="/api/v1/guruai", tags=["guruai"], dependencies=_auth)
app.include_router(unified_ws.router, prefix="/api/v1", tags=["unified-ws"])
app.include_router(quiz_judge.router, prefix="/api/v1", tags=["quiz-judge"])


@app.get("/")
async def root():
    return {"message": "Welcome to DeepTutor API"}


if __name__ == "__main__":
    from deeptutor.api.run_server import main as run_server_main
    run_server_main()
