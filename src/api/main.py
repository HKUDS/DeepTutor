from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routers import (
    agent_config,
    chat,
    co_writer,
    config,
    dashboard,
    guide,
    ideagen,
    knowledge,
    notebook,
    question,
    research,
    settings,
    solve,
    system,
)
from src.logging import get_logger
from src.services.path_service import get_path_service

# Note: Don't set service_prefix here - start_web.py already adds [Backend] prefix
logger = get_logger("API")

CONFIG_DRIFT_ERROR_TEMPLATE = (
    "Configuration Drift Detected: Tools {drift} found in agents.yaml "
    "investigate.valid_tools but missing from main.yaml solve.valid_tools. "
    "Add these tools to main.yaml solve.valid_tools or remove them from "
    "agents.yaml investigate.valid_tools."
)


def validate_tool_consistency():
    """
    Validate that the tools configured for agents are consistent with the main application
    configuration.

    This function loads the main configuration (``main.yaml``) and the agents configuration
    (``agents.yaml``) from the project root and compares:

    * ``solve.valid_tools`` in ``main.yaml``
    * ``investigate.valid_tools`` in ``agents.yaml``

    All tools referenced by agents must be present in the main configuration. If any tools are
    defined for agents that are not listed in the main configuration, a ``RuntimeError`` is
    raised describing the drift. The error is logged and re-raised, which causes the FastAPI
    application startup to fail when this function is called from the ``lifespan`` handler.

    Impact on startup
    ------------------
    This validation runs during application startup. Any configuration drift will:

    * Be logged as an error with details about the unknown tools.
    * Prevent the API from starting until the configuration is corrected.

    How to resolve configuration drift
    ----------------------------------
    If startup fails with a configuration drift error:

    1. Inspect the set of tools reported in the error message.
    2. Either:
       * Add the missing tools to ``solve.valid_tools`` in ``main.yaml``, **or**
       * Remove or rename the offending tools from ``investigate.valid_tools`` in ``agents.yaml``.
    3. Restart the application after updating the configuration files.

    Example of aligned configuration
    --------------------------------
    ``main.yaml``::

        solve:
          valid_tools:
            - web_search
            - code_execution

    ``agents.yaml``::

        investigate:
          valid_tools:
            - web_search

    In this case, validation passes because ``investigate.valid_tools`` is a subset of
    ``solve.valid_tools``.

    Example of configuration drift
    ------------------------------
    ``agents.yaml``::

        investigate:
          valid_tools:
            - web_search
            - unknown_tool

    Here, ``unknown_tool`` is not present in ``solve.valid_tools`` in ``main.yaml``, so
    validation will fail and prevent the application from starting until the configurations
    are aligned.
    """
    try:
        from src.services.config import load_config_with_main

        project_root = Path(__file__).parent.parent.parent
        main_config = load_config_with_main("main.yaml", project_root)
        agent_config_data = load_config_with_main("agents.yaml", project_root)

        main_tools = set(main_config.get("solve", {}).get("valid_tools", []))
        agent_tools = set(agent_config_data.get("investigate", {}).get("valid_tools", []))

        if not agent_tools.issubset(main_tools):
            drift = agent_tools - main_tools
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

    # Initialize LLM client early to set environment variables for LightRAG
    # LightRAG reads OPENAI_API_KEY from os.environ internally, so we must
    # set it before any RAG operations can happen
    try:
        from src.services.llm import get_llm_client

        llm_client = get_llm_client()
        logger.info(f"LLM client initialized: model={llm_client.config.model}")
    except Exception as e:
        logger.warning(f"Failed to initialize LLM client at startup: {e}")

    # Start EventBus for personalization
    try:
        from src.core.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.start()
        logger.info("EventBus started")
    except Exception as e:
        logger.warning(f"Failed to start EventBus: {e}")

    # Check if personalization should run externally
    # Set PERSONALIZATION_EXTERNAL=true to run personalization in a separate process
    # via: python scripts/start_personalization.py
    import os

    personalization_external = os.environ.get("PERSONALIZATION_EXTERNAL", "").lower() in (
        "true",
        "1",
        "yes",
    )

    if personalization_external:
        # External mode: Enable file queue for cross-process communication
        # Personalization service will be started separately via start_personalization.py
        try:
            from src.core.event_bus import enable_file_queue

            enable_file_queue()
            logger.info("Personalization running in external mode - file queue enabled")
            logger.info(
                "Start personalization service with: python scripts/start_personalization.py"
            )
        except Exception as e:
            logger.warning(f"Failed to enable file queue for external personalization: {e}")
    else:
        # Internal mode: Start PersonalizationService in-process
        try:
            from src.personalization.service import get_personalization_service

            personalization_service = get_personalization_service()
            await personalization_service.start()
            logger.info("PersonalizationService started (internal mode)")
        except Exception as e:
            logger.warning(f"Failed to start PersonalizationService: {e}")

    yield

    # Execute on shutdown
    logger.info("Application shutdown")

    # Stop PersonalizationService (only if running in internal mode)
    if not personalization_external:
        try:
            from src.personalization.service import get_personalization_service

            personalization_service = get_personalization_service()
            await personalization_service.stop()
            logger.info("PersonalizationService stopped")
        except Exception as e:
            logger.warning(f"Failed to stop PersonalizationService: {e}")
    else:
        # In external mode, just disable file queue
        try:
            from src.core.event_bus import disable_file_queue

            disable_file_queue()
            logger.info("File queue disabled")
        except Exception as e:
            logger.warning(f"Failed to disable file queue: {e}")

    # Stop EventBus
    try:
        from src.core.event_bus import get_event_bus

        event_bus = get_event_bus()
        await event_bus.stop()
        logger.info("EventBus stopped")
    except Exception as e:
        logger.warning(f"Failed to stop EventBus: {e}")


# ---------------------------------------------------------------------------
# Starlette multipart upload size limit
#
# By default Starlette's ``MultiPartParser`` caps each individual file part at
# 1 MB (the class-level ``max_file_size`` / ``max_part_size`` attribute).
# Files that exceed this limit are rejected at the framework layer *before*
# the route handler runs, resulting in an HTTP 413 "Request Entity Too Large"
# response — even when the file is well within DocumentValidator.MAX_FILE_SIZE
# (100 MB).
#
# We raise the Starlette limit here to match the application-level cap so that
# the framework streams larger uploads through to the route handler, which then
# applies the real per-file size check via DocumentValidator.
#
# References:
#   https://github.com/HKUDS/DeepTutor/issues/170
#   https://github.com/encode/starlette/blob/master/starlette/formparsers.py
# ---------------------------------------------------------------------------
try:
    from starlette.formparsers import MultiPartParser as _MultiPartParser

    _UPLOAD_LIMIT_BYTES = 100 * 1024 * 1024  # 100 MB — matches DocumentValidator.MAX_FILE_SIZE
    # Starlette ≥ 0.31 exposes ``max_file_size`` as a class attribute used as
    # the default value for ``max_part_size`` in MultiPartParser.__init__().
    _MultiPartParser.max_file_size = _UPLOAD_LIMIT_BYTES
except (ImportError, AttributeError):
    # Older Starlette versions do not enforce a part-level size limit;
    # no patching is required.
    pass

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

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount user directory as static root for generated artifacts
# This allows frontend to access generated artifacts (images, PDFs, etc.)
# URL: /api/outputs/agent/solve/solve_xxx/artifacts/image.png
# Physical Path: DeepTutor/data/user/agent/solve/solve_xxx/artifacts/image.png
path_service = get_path_service()
user_dir = path_service.user_data_dir

# Initialize user directories on startup
try:
    from src.services.setup import init_user_directories

    init_user_directories()
except Exception:
    # Fallback: just create the main directory if it doesn't exist
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

app.mount("/api/outputs", StaticFiles(directory=str(user_dir)), name="outputs")

# Include routers
app.include_router(solve.router, prefix="/api/v1", tags=["solve"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(question.router, prefix="/api/v1/question", tags=["question"])
app.include_router(research.router, prefix="/api/v1/research", tags=["research"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(co_writer.router, prefix="/api/v1/co_writer", tags=["co_writer"])
app.include_router(notebook.router, prefix="/api/v1/notebook", tags=["notebook"])
app.include_router(guide.router, prefix="/api/v1/guide", tags=["guide"])
app.include_router(ideagen.router, prefix="/api/v1/ideagen", tags=["ideagen"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(system.router, prefix="/api/v1/system", tags=["system"])
app.include_router(config.router, prefix="/api/v1/config", tags=["config"])
app.include_router(agent_config.router, prefix="/api/v1/agent-config", tags=["agent-config"])


@app.get("/")
async def root():
    return {"message": "Welcome to DeepTutor API"}


if __name__ == "__main__":
    from pathlib import Path

    import uvicorn

    # Get project root directory
    project_root = Path(__file__).parent.parent.parent

    # Ensure project root is in Python path
    import sys

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Get port from configuration
    from src.services.setup import get_backend_port

    backend_port = get_backend_port(project_root)

    # Configure reload_excludes with absolute paths to properly exclude directories
    venv_dir = project_root / "venv"
    data_dir = project_root / "data"
    reload_excludes = [
        str(d)
        for d in [
            venv_dir,
            project_root / ".venv",
            data_dir,
            project_root / "web" / "node_modules",
            project_root / "web" / ".next",
            project_root / ".git",
        ]
        if d.exists()
    ]

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=backend_port,
        reload=True,
        reload_excludes=reload_excludes,
    )
