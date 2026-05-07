from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from deeptutor.logging import configure_logging
from deeptutor.services.path_service import get_path_service

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
        from deeptutor.services.tutorbot import get_tutorbot_manager

        await get_tutorbot_manager().auto_start_bots()
    except Exception as e:
        logger.warning(f"Failed to auto-start TutorBots: {e}")

    yield

    # Execute on shutdown
    logger.info("Application shutdown")

    # Stop TutorBots
    try:
        from deeptutor.services.tutorbot import get_tutorbot_manager

        await get_tutorbot_manager().stop_all(preserve_auto_start=True)
        logger.info("TutorBots stopped")
    except Exception as e:
        logger.warning(f"Failed to stop TutorBots: {e}")

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

# Log only non-200 requests (uvicorn access_log is disabled in run_server.py)
_access_logger = logging.getLogger("uvicorn.access")


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


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend origin
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
    book,
    chat,
    co_writer,
    dashboard,
    knowledge,
    memory,
    notebook,
    plugins_api,
    question,
    question_notebook,
    sessions,
    settings,
    skills,
    solve,
    system,
    tutorbot,
    unified_ws,
    vision_solver,
)

# Include routers
app.include_router(solve.router, prefix="/api/v1", tags=["solve"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(question.router, prefix="/api/v1/question", tags=["question"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(co_writer.router, prefix="/api/v1/co_writer", tags=["co_writer"])
app.include_router(notebook.router, prefix="/api/v1/notebook", tags=["notebook"])
app.include_router(book.router, prefix="/api/v1/book", tags=["book"])
app.include_router(memory.router, prefix="/api/v1/memory", tags=["memory"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(
    question_notebook.router, prefix="/api/v1/question-notebook", tags=["question-notebook"]
)
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(skills.router, prefix="/api/v1/skills", tags=["skills"])
app.include_router(system.router, prefix="/api/v1/system", tags=["system"])
app.include_router(plugins_api.router, prefix="/api/v1/plugins", tags=["plugins"])
app.include_router(agent_config.router, prefix="/api/v1/agent-config", tags=["agent-config"])
app.include_router(vision_solver.router, prefix="/api/v1", tags=["vision-solver"])
app.include_router(tutorbot.router, prefix="/api/v1/tutorbot", tags=["tutorbot"])
app.include_router(attachments.router, prefix="/api/attachments", tags=["attachments"])

# Unified WebSocket endpoint
app.include_router(unified_ws.router, prefix="/api/v1", tags=["unified-ws"])


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "service": "deeptutor"}


@app.get("/")
async def root():
    return {"message": "Welcome to DeepTutor API"}


if __name__ == "__main__":
    from deeptutor.api.run_server import main as run_server_main

    run_server_main()
