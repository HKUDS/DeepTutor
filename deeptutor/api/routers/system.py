"""
System Status API Router
Manages system status checks and model connection tests
"""

import asyncio
from datetime import datetime
import json
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from deeptutor.api.contracts.turn_protocol import (
    MINIMUM_WEB_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    RuntimeStatus,
)
from deeptutor.api.routers.auth import require_admin
from deeptutor.multi_user.context import get_current_user
from deeptutor.runtime import memory_probe
from deeptutor.services.app_update import (
    Installation,
    UpdateInProgressError,
    UpdateJob,
    UpdateJobStore,
    UpdateRequestError,
    VersionCheckError,
    VersionCheckResult,
    detect_installation,
    get_version_check_service,
    launcher_available,
    update_store_root,
)
from deeptutor.services.config import (
    get_runtime_settings_service,
    resolve_search_runtime_config,
    supported_search_providers_hint,
)


def get_embedding_client(*args, **kwargs):
    from deeptutor.services.embedding.client import get_embedding_client as resolve

    return resolve(*args, **kwargs)


def get_embedding_config(*args, **kwargs):
    from deeptutor.services.embedding.config import get_embedding_config as resolve

    return resolve(*args, **kwargs)


def get_llm_config(*args, **kwargs):
    from deeptutor.services.llm.config import get_llm_config as resolve

    return resolve(*args, **kwargs)


def get_token_limit_kwargs(*args, **kwargs):
    from deeptutor.services.llm.config import get_token_limit_kwargs as resolve

    return resolve(*args, **kwargs)


async def llm_complete(*args, **kwargs):
    from deeptutor.services.llm import complete

    return await complete(*args, **kwargs)


def web_search(*args, **kwargs):
    from deeptutor.services.search import web_search as search

    return search(*args, **kwargs)


router = APIRouter()


class TestResponse(BaseModel):
    success: bool
    message: str
    model: str | None = None
    response_time_ms: float | None = None
    error: str | None = None


class UpdateSettingsRequest(BaseModel):
    enabled: bool


class ManagedUpdateRequest(BaseModel):
    confirmation: Literal["update-and-restart"]


def get_update_job_store() -> UpdateJobStore:
    return UpdateJobStore(update_store_root())


def get_update_installation() -> Installation:
    return detect_installation()


def get_turn_activity():
    from deeptutor.app.container import get_application_container

    return get_application_container().runtime_registry.get(
        get_application_container().store_provider.get()
    )


@router.get(
    "/runtime",
    dependencies=[Depends(require_admin)],
    response_model=RuntimeStatus,
)
async def get_runtime_status(request: Request) -> RuntimeStatus:
    """Return credential-free coordination and worker diagnostics."""

    from deeptutor.app.container import get_application_container

    container = getattr(request.app.state, "application_container", None)
    if container is None:
        container = get_application_container()
        await container.start()
    report = await container.runtime_report()
    return RuntimeStatus.model_validate(
        {
            **report,
            "leader_healthy": bool(report.get("leader_id")),
            "protocol_version": PROTOCOL_VERSION,
            "minimum_web_protocol_version": MINIMUM_WEB_PROTOCOL_VERSION,
        }
    )


def _job_payload(job: UpdateJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "current_version": job.current_version,
        "target_version": job.target_version,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "restart_count": job.restart_count,
    }


def _stored_job(store: UpdateJobStore | None = None) -> UpdateJob | None:
    try:
        return (store or get_update_job_store()).load()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _update_payload(
    *,
    result: VersionCheckResult | None,
    installation: Installation,
    check_enabled: bool,
    check_error: str = "",
    store: UpdateJobStore | None = None,
) -> dict[str, Any]:
    release = result.release if result is not None else None
    return {
        "current_version": result.current_version if result else installation.current_version,
        "check_enabled": check_enabled,
        "checked_at": result.checked_at if result else "",
        "cached": result.cached if result else False,
        "check_error": check_error,
        "update_available": result.update_available if result else False,
        "release": (
            {
                "version": release.version,
                "name": release.name,
                "published_at": release.published_at,
                "url": release.url,
                "excerpt": release.excerpt,
                "migration_warning": release.migration_warning,
            }
            if release
            else None
        ),
        "installation": {
            "mode": installation.mode,
            "automatic_update": installation.automatic_update,
            "command": installation.command,
            "reason": installation.reason,
        },
        "launcher_managed": launcher_available(),
        "is_admin": get_current_user().is_admin,
        "job": _job_payload(_stored_job(store)),
    }


async def _checked_update_payload(*, force: bool = False) -> dict[str, Any]:
    settings = get_runtime_settings_service().load_system()
    enabled = bool(settings["version_check_enabled"])
    installation = get_update_installation()
    service = get_version_check_service()
    if not enabled:
        return _update_payload(
            result=service.cached(),
            installation=installation,
            check_enabled=False,
        )
    try:
        result = await service.check(force=force)
    except VersionCheckError as exc:
        if force:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from None
        return _update_payload(
            result=service.cached(),
            installation=installation,
            check_enabled=True,
            check_error=str(exc),
        )
    return _update_payload(
        result=result,
        installation=installation,
        check_enabled=True,
    )


@router.get("/update")
async def get_update_status() -> dict[str, Any]:
    """Return About-page version state, checking at most once per 24 hours."""

    return await _checked_update_payload()


@router.post("/update/check", dependencies=[Depends(require_admin)])
async def check_for_update() -> dict[str, Any]:
    """Perform an explicit administrator-requested release check."""

    return await _checked_update_payload(force=True)


@router.put("/update/settings", dependencies=[Depends(require_admin)])
async def update_check_settings(payload: UpdateSettingsRequest) -> dict[str, Any]:
    service = get_runtime_settings_service()
    current = service.load_system(include_process_overrides=False)
    service.save_system({**current, "version_check_enabled": payload.enabled})
    return await _checked_update_payload()


@router.get("/update/job")
async def get_update_job() -> dict[str, Any] | None:
    return _job_payload(_stored_job())


@router.post(
    "/update",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def request_managed_update(_request: ManagedUpdateRequest) -> dict[str, Any]:
    """Reserve one safe update for the supervising launcher to apply."""

    settings = get_runtime_settings_service().load_system()
    if not settings["version_check_enabled"]:
        raise HTTPException(status_code=409, detail="Version checks are disabled")
    if not launcher_available():
        raise HTTPException(
            status_code=409,
            detail="Web updates require DeepTutor to be running under `deeptutor start`.",
        )
    installation = get_update_installation()
    if installation.mode != "pypi" or not installation.automatic_update:
        raise HTTPException(
            status_code=409,
            detail=installation.reason or "This installation cannot update itself safely.",
        )
    try:
        result = await get_version_check_service().check()
    except VersionCheckError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    if not result.update_available:
        raise HTTPException(status_code=409, detail="No newer DeepTutor release is available")
    # Re-check installation evidence immediately before reserving the job. A
    # deployment changing underneath this request fails closed.
    confirmed = get_update_installation()
    if confirmed.mode != "pypi" or not confirmed.automatic_update:
        raise HTTPException(
            status_code=409, detail="The installation changed during the update check"
        )
    store = get_update_job_store()
    try:
        job = await get_turn_activity().reserve_managed_update(
            lambda: store.create(
                current_version=result.current_version,
                target_version=result.release.version,
            )
        )
    except (UpdateInProgressError, UpdateRequestError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if job is None:
        raise HTTPException(
            status_code=409,
            detail="Finish the active conversation before updating DeepTutor.",
        )
    return _job_payload(job) or {}


@router.get("/status")
async def get_system_status():
    """
    Get overall system status including backend and model configurations

    Returns:
        Dictionary containing status of backend, LLM, embeddings, and search
    """
    result = {
        "backend": {"status": "online", "timestamp": datetime.now().isoformat()},
        "llm": {"status": "unknown", "model": None, "testable": True},
        "embeddings": {"status": "unknown", "model": None, "testable": True},
        "search": {"status": "optional", "provider": None, "testable": True},
    }

    # Check backend status (this endpoint itself proves backend is online)
    result["backend"]["status"] = "online"

    # Check LLM configuration
    try:
        llm_config = get_llm_config()
        result["llm"]["model"] = llm_config.model
        result["llm"]["status"] = "configured"
    except ValueError as e:
        result["llm"]["status"] = "not_configured"
        result["llm"]["error"] = str(e)
    except Exception as e:
        result["llm"]["status"] = "error"
        result["llm"]["error"] = str(e)

    # Check Embeddings configuration
    try:
        embedding_config = get_embedding_config()
        result["embeddings"]["model"] = embedding_config.model
        result["embeddings"]["status"] = "configured"
    except ValueError as e:
        result["embeddings"]["status"] = "not_configured"
        result["embeddings"]["error"] = str(e)
    except Exception as e:
        result["embeddings"]["status"] = "error"
        result["embeddings"]["error"] = str(e)

    try:
        search_config = resolve_search_runtime_config()
        if search_config.requested_provider:
            result["search"]["provider"] = search_config.provider
            if search_config.unsupported_provider:
                result["search"]["status"] = "unsupported"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} is deprecated/unsupported. "
                    f"Switch to {supported_search_providers_hint()}."
                )
            elif search_config.deprecated_provider:
                result["search"]["status"] = "deprecated"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} is deprecated. "
                    f"Switch to {supported_search_providers_hint()}."
                )
            elif search_config.missing_credentials:
                result["search"]["status"] = "not_configured"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} requires api_key. "
                    "Set profile.api_key in Settings > Catalog."
                )
            elif search_config.provider == "none":
                result["search"]["status"] = "disabled"
                result["search"]["testable"] = False
            else:
                result["search"]["status"] = "configured"
                if search_config.fallback_reason:
                    result["search"]["status"] = "fallback"
                    result["search"]["error"] = search_config.fallback_reason
    except Exception as e:
        result["search"]["status"] = "error"
        result["search"]["error"] = str(e)

    # Non-admin users have no need to know which model the admin configured;
    # exposing the name leaks operational detail and would let curious users
    # fingerprint the deployment. Strip the identifying fields.
    if not get_current_user().is_admin:
        for section in ("llm", "embeddings"):
            result[section].pop("model", None)
        result["search"].pop("provider", None)

    return result


@router.get("/memory")
async def get_memory_usage():
    """Resident memory of the running DeepTutor process tree.

    Deliberately separate from ``/status``: that snapshot resolves the LLM,
    embedding and search configs and is fetched once per settings mount, while
    this one is cheap enough for the status strip to poll.

    Admin-only, for the same reason ``/status`` strips model names from
    non-admins — process composition and host memory are operational detail a
    tenant has no need for.
    """
    if not get_current_user().is_admin:
        return {"available": False}

    snapshot = await asyncio.to_thread(memory_probe.capture)
    if not snapshot.processes:
        return {"available": False}

    # Fold the tree into one row per role, largest first, so the tooltip stays
    # readable when capabilities have spawned a dozen short-lived sandboxes.
    grouped: dict[str, dict[str, int]] = {}
    for proc in snapshot.processes:
        row = grouped.setdefault(proc.label, {"count": 0, "rss_bytes": 0})
        row["count"] += 1
        row["rss_bytes"] += proc.rss_bytes
    ranked = sorted(grouped.items(), key=lambda item: item[1]["rss_bytes"], reverse=True)

    processes = [
        {"label": label, "count": row["count"], "rss_bytes": row["rss_bytes"]}
        for label, row in ranked[: memory_probe.MAX_REPORTED_PROCESSES]
    ]
    overflow = ranked[memory_probe.MAX_REPORTED_PROCESSES :]
    if overflow:
        processes.append(
            {
                "label": "other",
                "count": sum(row["count"] for _label, row in overflow),
                "rss_bytes": sum(row["rss_bytes"] for _label, row in overflow),
            }
        )

    return {
        "available": True,
        "total_rss_bytes": snapshot.total_rss_bytes,
        "limit_bytes": snapshot.limit_bytes,
        "available_bytes": snapshot.available_bytes,
        "limit_source": snapshot.limit_source,
        "usage_ratio": snapshot.usage_ratio,
        "partial": snapshot.partial,
        "processes": processes,
    }


@router.post("/test/llm", response_model=TestResponse)
async def test_llm_connection():
    """
    Test LLM model connection by sending a simple completion request

    Returns:
        Test result with success status and response time
    """
    start_time = time.time()

    try:
        llm_config = get_llm_config()
        model = llm_config.model
        base_url = llm_config.base_url.rstrip("/")

        # Sanitize Base URL (remove /chat/completions suffix if present)
        for suffix in ["/chat/completions", "/completions"]:
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]

        # Handle API Key (inject dummy if missing for local LLMs)
        api_key = llm_config.api_key
        if not api_key:
            api_key = "sk-no-key-required"

        # Send a minimal test request with a prompt that guarantees output
        test_prompt = "Say 'OK' to confirm you are working. Do not produce long output."
        token_kwargs = get_token_limit_kwargs(model, max_tokens=200)

        response = await llm_complete(
            model=model,
            prompt=test_prompt,
            system_prompt="You are a helpful assistant. Respond briefly.",
            binding=llm_config.binding,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            **token_kwargs,
        )

        response_time = (time.time() - start_time) * 1000

        if response and len(response.strip()) > 0:
            return TestResponse(
                success=True,
                message="LLM connection successful",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="LLM connection failed: Empty response",
            model=model,
            error="Empty response from API",
        )

    except ValueError as e:
        return TestResponse(success=False, message=f"LLM configuration error: {e!s}", error=str(e))
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"LLM connection failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )


@router.post("/test/embeddings", response_model=TestResponse)
async def test_embeddings_connection():
    """
    Test Embeddings model connection by sending a simple embedding request

    Returns:
        Test result with success status and response time
    """
    start_time = time.time()

    try:
        embedding_config = get_embedding_config()
        embedding_client = get_embedding_client()

        model = embedding_config.model
        binding = embedding_config.binding

        # Probe a tiny batch so "connection OK" also exercises the path RAG
        # uses for multi-chunk indexing.
        test_texts = ["test", "retrieval batch probe"]
        embeddings = await embedding_client.embed(test_texts)

        response_time = (time.time() - start_time) * 1000

        if (
            embeddings is not None
            and len(embeddings) == len(test_texts)
            and all(len(vector) > 0 for vector in embeddings)
            and len({len(vector) for vector in embeddings}) == 1
        ):
            return TestResponse(
                success=True,
                message=f"Embeddings connection successful ({binding} provider)",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="Embeddings connection failed: Invalid response",
            model=model,
            error="Embedding response must contain one non-empty vector per input",
        )

    except ValueError as e:
        return TestResponse(
            success=False, message=f"Embeddings configuration error: {e!s}", error=str(e)
        )
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"Embeddings connection failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )


@router.post("/test/search", response_model=TestResponse)
async def test_search_connection():
    start_time = time.time()

    try:
        search_config = resolve_search_runtime_config()
        if search_config.provider == "none":
            return TestResponse(
                success=False,
                message="Search is disabled",
                error="Set a Search provider in Settings > Catalog.",
            )
        if search_config.unsupported_provider:
            return TestResponse(
                success=False,
                message=(
                    f"Search provider `{search_config.requested_provider}` is deprecated/unsupported."
                ),
                error=f"Switch to {supported_search_providers_hint()}",
            )
        if search_config.missing_credentials:
            return TestResponse(
                success=False,
                message=f"Search provider `{search_config.requested_provider}` missing credentials.",
                error="Set profile.api_key in Settings > Catalog.",
            )
        result = web_search("DeepTutor health check", provider=search_config.provider)
        response_time = (time.time() - start_time) * 1000
        answer = result.get("answer") or result.get("search_results")
        if not answer:
            raise ValueError("Search provider returned no content")
        return TestResponse(
            success=True,
            message="Search connection successful",
            model=search_config.provider,
            response_time_ms=round(response_time, 2),
        )

    except ValueError as e:
        return TestResponse(
            success=False, message=f"Search configuration error: {e!s}", error=str(e)
        )
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"Search connection check failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )
