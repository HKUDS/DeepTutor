"""Authenticated introspection and managed plugin HTTP route dispatch."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from deeptutor.api.routers.auth import AUTH_COOKIE_NAME, require_admin, require_auth
from deeptutor.plugins.frontend import (
    FrontendPageError,
    load_frontend_page_manifest,
    resolve_frontend_page_asset,
)
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
_FRONTEND_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "media-src 'self' data: blob:; "
    "connect-src 'none'; frame-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'; "
    "sandbox allow-scripts"
)


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
    result: list[dict[str, Any]] = []
    for record in records:
        if record.manifest is None:
            continue
        extensions: list[dict[str, Any]] = []
        for extension in record.manifest.extensions:
            payload = extension.to_dict()
            if extension.type == "frontend_page" and extension.manifest:
                payload["entry_url"] = f"/api/plugins/{record.id}/pages/{extension.id}/"
            extensions.append(payload)
        result.append(
            {
                "id": record.id,
                "name": record.name,
                "version": record.version,
                "extensions": extensions,
            }
        )
    return result


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


def _find_frontend_page(
    *,
    plugin_id: str,
    extension_id: str,
) -> tuple[PluginRecord, PluginExtension, PluginInstallation, Path] | None:
    for record in _managed_records(_registry_factory()):
        if record.id != plugin_id or record.manifest is None or record.installation is None:
            continue
        if record.installation.package_path is None:
            continue
        for extension in record.manifest.extensions:
            if extension.type == "frontend_page" and extension.id == extension_id:
                return record, extension, record.installation, record.installation.package_path
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


async def _authenticate_plugin_page(request: Request) -> None:
    matched = _find_frontend_page(
        plugin_id=request.path_params["plugin_id"],
        extension_id=request.path_params["extension_id"],
    )
    if matched is None:
        return
    request.state.plugin_page = matched
    policy = matched[1].auth
    if policy == "authenticated":
        await _require_authenticated(request)
    elif policy == "admin":
        await _require_admin(request)


@router.get("/extensions", dependencies=[Depends(_require_authenticated)])
def list_extensions() -> dict[str, Any]:
    return {"plugins": _extensions_payload(_managed_records(_registry_factory()))}


@router.get(
    "/{plugin_id}/pages/{extension_id}",
    dependencies=[Depends(_authenticate_plugin_page)],
)
def redirect_plugin_frontend_page(request: Request) -> RedirectResponse:
    matched = getattr(request.state, "plugin_page", None)
    if matched is None:
        raise HTTPException(status_code=404, detail="Plugin page not found")
    return RedirectResponse(url=f"{request.url.path}/", status_code=307)


@router.get(
    "/{plugin_id}/pages/{extension_id}/",
    dependencies=[Depends(_authenticate_plugin_page)],
)
def get_plugin_frontend_page(request: Request) -> FileResponse:
    matched = getattr(request.state, "plugin_page", None)
    if matched is None:
        raise HTTPException(status_code=404, detail="Plugin page not found")
    _, extension, _, package_path = matched
    if not extension.manifest:
        raise HTTPException(status_code=404, detail="Plugin page not found")
    try:
        page = load_frontend_page_manifest(package_path / extension.manifest)
        path = resolve_frontend_page_asset(page, package_path, page.entry)
    except FrontendPageError as exc:
        logger.warning(
            "Managed frontend page %s/%s failed validation",
            matched[0].id,
            extension.id,
            exc_info=exc,
        )
        raise HTTPException(status_code=404, detail="Plugin page not found") from exc
    return _frontend_file_response(path)


@router.get(
    "/{plugin_id}/pages/{extension_id}/assets/{asset_path:path}",
    dependencies=[Depends(_authenticate_plugin_page)],
)
def get_plugin_frontend_asset(request: Request) -> FileResponse:
    matched = getattr(request.state, "plugin_page", None)
    if matched is None:
        raise HTTPException(status_code=404, detail="Plugin page not found")
    _, extension, _, package_path = matched
    if not extension.manifest:
        raise HTTPException(status_code=404, detail="Plugin page not found")
    requested = request.path_params["asset_path"]
    try:
        page = load_frontend_page_manifest(package_path / extension.manifest)
        path = resolve_frontend_page_asset(page, package_path, requested)
    except FrontendPageError as exc:
        logger.warning(
            "Managed frontend asset %s/%s failed validation",
            matched[0].id,
            extension.id,
            exc_info=exc,
        )
        raise HTTPException(status_code=404, detail="Plugin page not found") from exc
    return _frontend_file_response(path, asset=True)


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


for _method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
    router.add_api_route(
        "/{plugin_id}/{plugin_path:path}",
        dispatch_plugin_route,
        methods=[_method],
        operation_id=f"dispatch_plugin_route_{_method.lower()}",
        dependencies=[Depends(_authenticate_plugin_route)],
    )


def _http_response(result: PluginHttpResponse) -> Response:
    if result.status == 204:
        return Response(status_code=204, headers=dict(result.headers or {}))
    return JSONResponse(
        status_code=result.status,
        content=result.body,
        headers=dict(result.headers or {}),
    )


def _frontend_file_response(path: Path, *, asset: bool = False) -> FileResponse:
    media_type = "text/html; charset=utf-8" if path.suffix.lower() == ".html" else None
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Security-Policy": _FRONTEND_CSP,
            "Cross-Origin-Resource-Policy": "cross-origin" if asset else "same-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
