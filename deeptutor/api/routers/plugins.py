"""Authenticated introspection and managed plugin HTTP route dispatch."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from deeptutor.api.routers.auth import AUTH_COOKIE_NAME, require_admin, require_auth
from deeptutor.plugins.manifest import PluginExtension
from deeptutor.plugins.registry import PluginInstallation, PluginRecord, PluginRegistry
from deeptutor.plugins.runtime import (
    PluginHttpResponse,
    PluginRuntimeError,
    PluginWorkerHttpRoute,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_registry_factory = PluginRegistry
_MAX_JSON_BODY_BYTES = 1024 * 1024


async def _require_authenticated(request: Request):
    return await require_auth(
        authorization=request.headers.get("Authorization"),
        dt_token=request.cookies.get(AUTH_COOKIE_NAME),
    )


async def _require_admin(request: Request):
    return await require_admin(
        payload=await _require_authenticated(request),
    )


def _managed_records(registry: PluginRegistry) -> list[PluginRecord]:
    return [
        record
        for record in registry.list_plugins(include_catalog=False)
        if record.status == "enabled"
        and record.distribution == "managed"
        and record.manifest is not None
        and record.installation is not None
    ]


def _extensions_payload(records: list[PluginRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": record.id,
            "name": record.name,
            "version": record.version,
            "extensions": [extension.to_dict() for extension in record.manifest.extensions],
        }
        for record in records
        if record.manifest is not None
    ]


def _find_route(
    *,
    plugin_id: str,
    plugin_path: str,
) -> tuple[PluginRecord, PluginExtension, PluginInstallation] | None:
    normalized_path = _normalize_plugin_path(plugin_path)
    if normalized_path is None:
        return None
    for record in _managed_records(_registry_factory()):
        if record.id != plugin_id or record.manifest is None or record.installation is None:
            continue
        for extension in record.manifest.extensions:
            if extension.type == "http_route" and extension.path == normalized_path:
                return record, extension, record.installation
    return None


def _normalize_plugin_path(value: str) -> str | None:
    if not value or "\x00" in value or "%" in value or "\\" in value:
        return None
    return "/" + value.strip("/")


async def _authenticate_plugin_route(request: Request) -> None:
    matched = _find_route(
        plugin_id=request.path_params["plugin_id"],
        plugin_path=request.path_params["plugin_path"],
    )
    if matched is None:
        return
    request.state.plugin_route = matched
    policy = matched[1].auth
    if policy == "authenticated":
        await _require_authenticated(request)
    elif policy == "admin":
        await _require_admin(request)


@router.get("/extensions", dependencies=[Depends(_require_authenticated)])
def list_extensions() -> dict[str, Any]:
    return {"plugins": _extensions_payload(_managed_records(_registry_factory()))}


@router.api_route(
    "/{plugin_id}/{plugin_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    dependencies=[Depends(_authenticate_plugin_route)],
)
async def dispatch_plugin_route(request: Request) -> Response:
    matched = getattr(request.state, "plugin_route", None)
    if matched is None:
        raise HTTPException(status_code=404, detail="Plugin route not found")
    record, extension, installation = matched
    if request.method not in extension.methods:
        raise HTTPException(
            status_code=405,
            detail="Method not allowed",
            headers={"Allow": ", ".join(extension.methods)},
        )

    raw_body = await request.body()
    if len(raw_body) > _MAX_JSON_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Plugin request body is too large")
    body = None
    if raw_body:
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Request body must be JSON") from exc

    query: dict[str, tuple[str, ...]] = {
        name: tuple(request.query_params.getlist(name)) for name in request.query_params.keys()
    }
    worker = PluginWorkerHttpRoute(
        manifest=record.manifest,
        installation=installation,
        extension_id=extension.id,
    )
    try:
        result = worker.handle(
            method=request.method,
            path=extension.path,
            query=query,
            body=body,
        )
    except PluginRuntimeError as exc:
        logger.warning(
            "Managed HTTP route %s/%s failed its worker contract",
            record.id,
            extension.id,
            exc_info=exc,
        )
        raise HTTPException(status_code=500, detail="Plugin route failed") from exc
    return _http_response(result)


def _http_response(result: PluginHttpResponse) -> Response:
    if result.status == 204:
        return Response(status_code=204, headers=dict(result.headers or {}))
    return JSONResponse(
        status_code=result.status,
        content=result.body,
        headers=dict(result.headers or {}),
    )


__all__ = ["router"]
