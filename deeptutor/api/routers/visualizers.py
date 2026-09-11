"""Per-user visualizer catalog, lifecycle and sandbox asset routes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from deeptutor.visualizers.registry import get_visualizer_registry
from deeptutor.visualizers.store import VisualizerStoreError

router = APIRouter()

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_IFRAME_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "media-src 'self' data: blob:; "
    "connect-src 'none'; frame-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def _http_error(exc: VisualizerStoreError) -> HTTPException:
    detail = str(exc)
    if "not found" in detail:
        return HTTPException(status_code=404, detail=detail)
    if "already installed" in detail or "reserved" in detail:
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.get("/list")
async def list_visualizers() -> dict[str, object]:
    registry = get_visualizer_registry()
    return {
        "schema_version": "deeptutor.visualizer-catalog/v1",
        "visualizers": registry.public_catalog(),
    }


@router.post("/bundled/{visualizer_id}/install")
async def install_bundled(visualizer_id: str) -> dict[str, object]:
    registry = get_visualizer_registry()
    try:
        registry.install_bundled(visualizer_id)
    except VisualizerStoreError as exc:
        raise _http_error(exc) from exc
    plugin = registry.get(visualizer_id)
    return {"status": "installed", "visualizer": plugin.manifest.id if plugin else visualizer_id}


@router.post("/{visualizer_id}/enable")
async def enable_visualizer(visualizer_id: str) -> dict[str, str]:
    registry = get_visualizer_registry()
    try:
        registry.set_enabled(visualizer_id, True)
    except VisualizerStoreError as exc:
        raise _http_error(exc) from exc
    return {"status": "enabled", "visualizer": visualizer_id}


@router.post("/{visualizer_id}/disable")
async def disable_visualizer(visualizer_id: str) -> dict[str, str]:
    registry = get_visualizer_registry()
    try:
        registry.set_enabled(visualizer_id, False)
    except VisualizerStoreError as exc:
        raise _http_error(exc) from exc
    return {"status": "disabled", "visualizer": visualizer_id}


@router.delete("/{visualizer_id}")
async def uninstall_visualizer(visualizer_id: str) -> dict[str, str]:
    registry = get_visualizer_registry()
    try:
        registry.uninstall(visualizer_id)
    except VisualizerStoreError as exc:
        raise _http_error(exc) from exc
    return {"status": "uninstalled", "visualizer": visualizer_id}


@router.post("/import")
async def import_visualizer(
    file: UploadFile = File(...),  # noqa: B008
) -> dict[str, object]:
    """Install one declarative ``visualizer.json`` + iframe bundle zip."""

    if not str(file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="visualizer package must be a zip file")

    fd, temp_name = tempfile.mkstemp(prefix="deeptutor-visualizer-", suffix=".zip")
    os.close(fd)
    temp_path = Path(temp_name)
    total = 0
    try:
        with temp_path.open("wb") as sink:
            while chunk := await file.read(1 << 20):
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="visualizer package exceeds 25 MB",
                    )
                sink.write(chunk)
        registry = get_visualizer_registry()
        try:
            plugin = registry.install_archive(temp_path)
        except VisualizerStoreError as exc:
            raise _http_error(exc) from exc
        catalog = registry.public_catalog()
        public_manifest = next(item for item in catalog if item["id"] == plugin.manifest.id)
        return {
            "status": "installed",
            "visualizer": plugin.manifest.id,
            "manifest": public_manifest,
        }
    finally:
        temp_path.unlink(missing_ok=True)
        await file.close()


@router.get("/{visualizer_id}/assets/{asset_path:path}")
async def get_visualizer_asset(visualizer_id: str, asset_path: str) -> FileResponse:
    registry = get_visualizer_registry()
    try:
        path = registry.asset_path(visualizer_id, asset_path)
    except VisualizerStoreError as exc:
        raise _http_error(exc) from exc
    return FileResponse(
        path,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Security-Policy": _IFRAME_CSP,
            "Cross-Origin-Resource-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )
