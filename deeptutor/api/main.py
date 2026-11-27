import asyncio
from contextlib import asynccontextmanager
import logging
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from deeptutor.api.security_guard import install_security_guard
from deeptutor.logging import configure_logging
from deeptutor.modules.catalog import module_enabled
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
    """
    Validate that capability manifests only reference tools that are actually
    registered in the runtime ``ToolRegistry``.
    """
    try:
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
        from deeptutor.runtime.registry.tool_registry import get_tool_registry

        capability_registry = get_capability_registry()
        tool_registry = get_tool_registry()
        from deeptutor.tools.builtin_specs import BUILTIN_TOOL_NAMES

        available_tools = set(tool_registry.list_tools()) | set(BUILTIN_TOOL_NAMES)

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
    app.state.ready = False

    # Validate configuration consistency
    validate_tool_consistency()

    # Build one process-level dependency graph.  Every adapter resolves turns
    # through this container, so a WebSocket cannot accidentally construct a
    # second store/runtime for the same authenticated scope.
    from deeptutor.app.container import get_application_container

    application_container = getattr(app.state, "application_container", None)
    if application_container is None:
        application_container = get_application_container()
        app.state.application_container = application_container
    await application_container.start()
    if module_enabled("knowledge"):
        from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster
        from deeptutor.api.utils.task_log_stream import get_task_stream_manager
        from deeptutor.knowledge.progress_events import install_progress_ports

        install_progress_ports(
            broadcast=ProgressBroadcaster.get_instance().broadcast,
            emit_task_event=get_task_stream_manager().emit,
        )
    migration_reports = await application_container.run_startup_data_migrations()
    legacy_reports = migration_reports["legacy_chat"]
    migrated_reports = [report for report in legacy_reports if report.get("source_hash")]
    if migrated_reports:
        logger.info(
            "Legacy chat migration complete: imported=%s skipped=%s archived=%s",
            sum(int(report.get("imported") or 0) for report in migrated_reports),
            sum(int(report.get("skipped") or 0) for report in migrated_reports),
            [report.get("archived_to", "") for report in migrated_reports],
        )
    workspace_migrated = sum(
        int(report.get("migrated") or 0) for report in migration_reports["workspace_preferences"]
    )
    if workspace_migrated:
        logger.info(
            "Workspace session migration complete: migrated=%s scopes=%s",
            workspace_migrated,
            len(migration_reports["workspace_preferences"]),
        )

    try:
        if module_enabled("mastery"):
            from deeptutor.learning.assessment import reconcile_linked_assessments

            recovered, failed = await reconcile_linked_assessments()
            if recovered or failed:
                logger.info("Linked assessment recovery: recovered=%s failed=%s", recovered, failed)
    except Exception:
        logger.exception("Failed to reconcile linked assessments at startup")

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

    from deeptutor.runtime.coordination import BackgroundCommandKind

    async def _handle_background_command(command) -> None:
        kind = str(command.kind)
        if kind == BackgroundCommandKind.CRON_RELOAD:
            from deeptutor.modules.catalog import require_module

            require_module("calendar")
            from deeptutor.services.cron import get_cron_service

            get_cron_service().reload()
            return

        from deeptutor.modules.catalog import require_module

        require_module("partners")
        from deeptutor.services.partners import get_partner_manager

        manager = get_partner_manager()
        manager.configure_runtime_owner(application_container.worker_id)
        partner_id = str(command.payload.get("partner_id") or "").strip()
        if not partner_id:
            raise ValueError(f"Background command {kind!r} needs partner_id")
        if kind == BackgroundCommandKind.PARTNER_START:
            instance = await manager.start_partner(partner_id)
            if bool(command.payload.get("persist_auto_start", True)):
                manager.save_config(partner_id, instance.config, auto_start=True)
            return
        if kind == BackgroundCommandKind.PARTNER_STOP:
            await manager.stop_partner(
                partner_id,
                preserve_auto_start=bool(command.payload.get("preserve_auto_start", False)),
            )
            return
        if kind == BackgroundCommandKind.PARTNER_RELOAD:
            instance = manager.get_partner(partner_id)
            if instance is None or not instance.running:
                return
            config = manager.load_config(partner_id)
            if config is not None:
                instance.config = config
            await manager.reload_channels(partner_id)
            return
        raise ValueError(f"Unknown background command kind: {kind}")

    cron_service = None
    try:
        if module_enabled("calendar"):
            from deeptutor.services.cron import get_cron_service

            cron_service = get_cron_service()
            loop = asyncio.get_running_loop()

            def _notify_cron_change() -> None:
                task = loop.create_task(
                    application_container.coordinator.submit_background_command(
                        BackgroundCommandKind.CRON_RELOAD
                    )
                )
                task.add_done_callback(
                    lambda completed: completed.exception() if not completed.cancelled() else None
                )

            cron_service.change_notifier = _notify_cron_change
    except Exception:
        logger.exception("Failed to configure cron change notifications")

    from deeptutor.modules.services import module_service_callbacks
    from deeptutor.runtime.background_leader import BackgroundLeaderSupervisor

    background_supervisor = BackgroundLeaderSupervisor(
        application_container.coordinator,
        application_container.worker_id,
        start_callbacks=module_service_callbacks("start", application_container),
        stop_callbacks=module_service_callbacks("stop", application_container),
        recovery_callback=application_container.recover_once,
        control_callback=_handle_background_command,
        renew_interval_seconds=application_container.settings.renew_interval_seconds,
        recovery_interval_seconds=application_container.settings.recovery_interval_seconds,
    )
    app.state.background_supervisor = background_supervisor
    await background_supervisor.start()

    # Ping PocketBase if configured — logs a warning (not an error) if unreachable
    try:
        from deeptutor.services.pocketbase_client import ping_pocketbase

        await ping_pocketbase()
    except Exception as e:
        logger.warning(f"PocketBase startup check failed: {e}")

    # Migrate any v1 memory files (PROFILE.md / SOUL.md / SUMMARY.md) into a
    # backup folder so the v2 three-layer subsystem starts clean.
    try:
        if module_enabled("memory"):
            from deeptutor.services.memory import (
                migrate_partner_surface_if_needed,
                migrate_v1_if_needed,
            )
            from deeptutor.services.path_service import get_path_service

            get_path_service().migrate_legacy_memory_markdown()
            backup = migrate_v1_if_needed()
            if backup is not None:
                logger.info("v1 memory archived to %s", backup)
            # Rename the legacy ``tutorbot`` memory surface (footnote refs, L2
            # doc, snapshot/trace dirs, L3 meta keys) to ``partner``.
            migrate_partner_surface_if_needed()
    except Exception as e:
        logger.warning(f"v1 memory migration failed: {e}")

    app.state.ready = True
    yield

    # Execute on shutdown
    app.state.ready = False
    logger.info("Application shutdown")

    if module_enabled("knowledge"):
        install_progress_ports(broadcast=None, emit_task_event=None)

    try:
        await background_supervisor.close()
        logger.info("Leader-owned background services stopped")
    except Exception as e:
        logger.warning(f"Failed to stop background leader: {e}")

    try:
        await application_container.close()
        logger.info("Application container closed")
    except Exception as e:
        logger.warning(f"Failed to close application container: {e}")

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
        from deeptutor.runtime.agentic.client import close_agentic_client_pool

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


from deeptutor.services.workspace.activity import WorkspaceActivityMiddleware

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

from deeptutor.core.errors import AccessError
from deeptutor.modules.catalog import ModuleUnavailable


@app.exception_handler(AccessError)
async def access_error_handler(request: Request, exc: AccessError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(ModuleUnavailable)
async def module_unavailable_handler(request: Request, exc: ModuleUnavailable):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.add_middleware(WorkspaceActivityMiddleware)


@app.middleware("http")
async def json_error_boundary(request: Request, call_next):
    """Catch-all so 500s always return JSON, never Starlette's plain-text body.

    Registered as a middleware rather than an ``@app.exception_handler``: a
    handler for ``Exception`` is installed on Starlette's outermost
    ``ServerErrorMiddleware``, so its response skips every middleware added
    here — the 500 would carry no CORS headers (a cross-origin caller sees an
    opaque CORS failure instead of this body) and would never reach the access
    log below. Registered *before* ``CORSMiddleware``, this boundary sits
    inside it, so the response travels back out through the normal stack.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"{type(exc).__name__}: {exc}",
                "type": type(exc).__name__,
            },
        )


# Optional fastapi-guard screening (off unless security_guard.enabled). Added
# before the access log and CORS middlewares below: Starlette makes the last-added
# middleware outermost, so CORS stays outside the guard (429/403 carry CORS
# headers) and the access log sees what the guard rejects.
install_security_guard(app)

# Access logging is funneled through this one middleware. uvicorn's own
# per-request access log is disabled on every launch path (run_server.py via
# access_log=False; the launcher and Docker via `--no-access-log`), so routine
# 200s — the chatty frontend polling of /settings, /tools, /knowledge-bases,
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
    # An expired app login must not strand provider credentials in a callback URL.
    # Authentication still runs normally; only its failure presentation changes.
    if (
        request.url.path == "/api/video-learning/invidious/account/callback"
        and response.status_code in {401, 403}
    ):
        response = RedirectResponse(
            "/reading?account=authorization_login_required",
            status_code=303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
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

# Initialize user directories on startup
try:
    from deeptutor.services.setup import init_user_directories

    init_user_directories()
except Exception:
    # Fallback: just create the main directory if it doesn't exist
    user_dir = get_path_service().get_public_outputs_root()
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

# Runtime settings must be initialized before a router module is imported.
# The native profile defers unrelated feature schemas until their first request.
import os  # noqa: E402

from deeptutor.api.router_loader import RouterLoader  # noqa: E402

_router_loader = RouterLoader(
    app, lazy=os.environ.get("DEEPTUTOR_CHAT_ENGINE") == "typescript-native"
)

from deeptutor.api.module_routes import mount_module_routes

mount_module_routes(app, _router_loader)


@app.get("/")
async def root():
    return {"message": "Welcome to DeepTutor API"}


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health", include_in_schema=False)
@app.get("/health/ready")
async def health_ready(request: Request):
    if not bool(getattr(request.app.state, "ready", False)):
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    container = getattr(request.app.state, "application_container", None)
    if container is None or not await container.coordinator.health():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "coordination_unavailable"},
        )
    return {"status": "ready"}


if __name__ == "__main__":
    from deeptutor.api.run_server import main as run_server_main

    run_server_main()
