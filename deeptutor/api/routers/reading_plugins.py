"""Administrator-only lifecycle API for the reading extension wheel."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
import httpx
from pydantic import BaseModel

from deeptutor.api.routers.auth import require_admin
from deeptutor.reading import component_plugins, plugin_manager

router = APIRouter(dependencies=[Depends(require_admin)])


async def _run(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except (ValueError, OSError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_plugins():
    return await _run(plugin_manager.status)


@router.post("/install")
async def install_plugin(file: UploadFile = File(...)):  # noqa: B008
    try:
        if not (file.filename or "").endswith(".whl"):
            raise HTTPException(status_code=400, detail="Choose a .whl file.")
        data = await file.read(plugin_manager.MAX_BYTES + 1)
        return await _run(plugin_manager.install, data)
    finally:
        await file.close()


@router.post("/download")
async def download_plugin(package: str = plugin_manager.PACKAGE):
    return await _run(plugin_manager.download_latest, package)


@router.delete("")
async def uninstall_plugin():
    return await _run(plugin_manager.configure, mode="disabled")


@router.post("/restore")
async def restore_builtin():
    return await _run(plugin_manager.configure, mode="builtin")


class EnabledPayload(BaseModel):
    enabled: bool


@router.put("/{extension}/enabled")
async def enable_plugin(extension: str, payload: EnabledPayload):
    return await _run(plugin_manager.configure, extension=extension, enabled=payload.enabled)


class ProviderPayload(BaseModel):
    package: str = ""


@router.put("/providers/{slot}")
async def select_provider(slot: str, payload: ProviderPayload):
    await _run(component_plugins.select, slot, payload.package)
    return await _run(plugin_manager.status)


@router.delete("/components/{package}")
async def remove_component(package: str):
    await _run(component_plugins.uninstall, package)
    return await _run(plugin_manager.status)
