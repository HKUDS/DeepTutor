"""Content-workspace settings and authenticated presentation delivery."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.partner_access import visible_partners
from deeptutor.multi_user.paths import user_context
from deeptutor.services.auth import TokenPayload
from deeptutor.services.partners.scope import partner_user
from deeptutor.services.workspace import (
    WorkspaceError,
    WorkspaceItem,
    get_content_workspace_service,
)
from deeptutor.services.workspace.resources import WorkspaceResources

settings_router = APIRouter()
files_router = APIRouter()


class WorkspacePathPayload(BaseModel):
    path: str | None = None


class CreateWorkspacePayload(BaseModel):
    resources: WorkspaceResources | None = None
    name: str = Field(min_length=1, max_length=100)
    path: str | None = None


class UpdateWorkspacePayload(BaseModel):
    resources: WorkspaceResources | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class DataMigrationPayload(BaseModel):
    source_workspace_id: str = ""
    target_workspace_id: str = ""
    features: list[str] = Field(min_length=1)
    include_historical: bool = False


async def _data_operation(function, *args, **kwargs):
    _assert_migration_access()
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    try:
        return await asyncio.shield(task)
    except (WorkspaceError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _assert_migration_access():
    from deeptutor.multi_user.learning_access import current_learning_policy

    if current_learning_policy() is not None:
        raise HTTPException(
            status_code=403,
            detail="Data migration and export are managed by the guardian for this learning account.",
        )


@settings_router.get("/data/discover")
async def discover_workspace_data(source_workspace_id: str = "") -> dict:
    from deeptutor.services.workspace.data_migration import discover

    return await _data_operation(discover, source_workspace_id)


@settings_router.post("/data/preview")
async def preview_workspace_data(payload: DataMigrationPayload) -> dict:
    from deeptutor.services.workspace.data_migration import preview

    return await _data_operation(
        preview, payload.source_workspace_id, payload.target_workspace_id, payload.features
    )


@settings_router.post("/data/migrate")
async def migrate_workspace_data(payload: DataMigrationPayload) -> dict:
    from deeptutor.services.workspace.data_migration import migrate_data

    return await _data_operation(
        migrate_data, payload.source_workspace_id, payload.target_workspace_id, payload.features
    )


@settings_router.post("/data/export")
async def export_workspace_data(payload: DataMigrationPayload) -> dict:
    from deeptutor.services.workspace.data_migration import export_data

    return await _data_operation(
        export_data,
        payload.source_workspace_id,
        payload.features,
        include_historical=payload.include_historical,
    )


@settings_router.get("/data/operations")
async def workspace_data_operations() -> dict:
    _assert_migration_access()
    from deeptutor.services.workspace.data_migration import operations

    return {"operations": await asyncio.to_thread(operations)}


@settings_router.post("/data/operations/{operation_id}/recover")
async def recover_workspace_migration(operation_id: str) -> dict:
    from deeptutor.services.workspace.data_migration import recover_operation

    return await _data_operation(recover_operation, operation_id)


@settings_router.get("/data/exports/{operation_id}")
async def download_workspace_export(operation_id: str) -> FileResponse:
    _assert_migration_access()
    from deeptutor.services.workspace.data_migration import export_path

    try:
        return FileResponse(
            export_path(operation_id),
            media_type="application/zip",
            filename=f"deeptutor-data-{operation_id[:8]}.zip",
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@settings_router.get("/registrations")
async def list_workspaces() -> dict:
    return get_content_workspace_service().describe_catalog()


class WorkspaceMigrationPayload(BaseModel):
    path: str = Field(min_length=1)


async def _migrate_workspaces(path: str, workspace_id: str | None = None) -> dict:
    from deeptutor.services.session import get_session_store

    service = get_content_workspace_service()

    async def perform() -> dict:
        from deeptutor.services.workspace.activity import data_activity
        from deeptutor.services.workspace.data_migration import assert_no_pending_recovery

        with data_activity(exclusive=True):
            assert_no_pending_recovery()
            return await migrate_location()

    async def migrate_location() -> dict:
        with service.maintenance():
            active = await get_session_store().list_nonterminal_turns()
            if active:
                raise WorkspaceError(
                    "Wait for running conversations to finish before migrating workspace storage."
                )
            if workspace_id is None:
                return await asyncio.to_thread(service.migrate_root, path)
            return await asyncio.to_thread(service.migrate_workspace, workspace_id, path)

    # A disconnected browser must not abandon a copy midway or release the
    # migration guard while its worker is still copying files.
    task = asyncio.create_task(perform())
    # Retrieve a late error even if the requesting client has disconnected.
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    try:
        return await asyncio.shield(task)
    except (WorkspaceError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@settings_router.post("/registrations/migrate-root")
async def migrate_workspace_root(payload: WorkspaceMigrationPayload) -> dict:
    return await _migrate_workspaces(payload.path)


@settings_router.post("/registrations/{workspace_id}/migrate")
async def migrate_registered_workspace(
    workspace_id: str, payload: WorkspaceMigrationPayload
) -> dict:
    return await _migrate_workspaces(payload.path, workspace_id)


@settings_router.get("/registrations/system-snapshot")
@settings_router.post("/registrations/system-snapshot")
async def system_workspace_snapshot() -> dict:
    try:
        return get_content_workspace_service().refresh_system_snapshot()
    except (WorkspaceError, OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@settings_router.get("/resource-usage")
async def workspace_resource_usage(kind: str, resource_id: str, skill_workspace: str = "") -> dict:
    from deeptutor.services.workspace.resources import resource_usage

    try:
        return {"workspaces": resource_usage(kind, resource_id, skill_workspace=skill_workspace)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@settings_router.get("/resources")
async def workspace_resource_catalog(workspace_id: str = "") -> dict:
    from deeptutor.services.workspace.resources import resource_catalog

    try:
        return await asyncio.to_thread(resource_catalog, workspace_id=workspace_id)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@settings_router.post("/registrations")
async def create_workspace(payload: CreateWorkspacePayload) -> dict:
    try:
        workspace = get_content_workspace_service().create_workspace(
            payload.name,
            payload.path,
            resources=payload.resources.model_dump() if payload.resources else None,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"workspace": workspace}


@settings_router.patch("/registrations/{workspace_id}")
async def update_registered_workspace(workspace_id: str, payload: UpdateWorkspacePayload) -> dict:
    try:
        from deeptutor.services.workspace.activity import data_activity
        from deeptutor.services.workspace.data_migration import assert_no_pending_recovery

        with data_activity(exclusive=True):
            assert_no_pending_recovery()
            workspace = get_content_workspace_service().update_workspace(
                workspace_id, **payload.model_dump(exclude_unset=True)
            )
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"workspace": workspace}


@settings_router.get("")
async def get_workspace_settings() -> dict:
    return get_content_workspace_service().describe_current()


@settings_router.post("/validate")
async def validate_workspace(payload: WorkspacePathPayload) -> dict:
    return get_content_workspace_service().validate(payload.path)


@settings_router.put("")
async def update_workspace(payload: WorkspacePathPayload) -> dict:
    service = get_content_workspace_service()
    try:
        service.set_workspace(payload.path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return service.describe_current()


def _resolve_partner_item(
    workspace_id: str, workspace_item_id: str
) -> tuple[Path, WorkspaceItem] | None:
    """Resolve a presentation one of the caller's partners published.

    A partner web chat runs inside a synthetic workspace under
    ``data/partners/<id>/workspace``, so ``workspace_present`` writes its
    manifest to that scope's private presentation store. The human caller's own
    bindings never name that workspace, ``binding_by_id`` refuses it, and the
    attachment sitting in the transcript 404s on click (#1267).

    ``/files/outputs`` grew the same reach in #1012 — see
    ``_resolve_partner_output`` — and this is the other artifact URL shape. It
    does not need that endpoint's unique-match rule: a workspace id is derived
    from the owning user id together with the physical root and re-derived
    before a stored row is trusted, so a hit inside a partner scope belongs to
    that partner by construction, where a relative output path can collide.
    """
    from deeptutor.services.workspace.context import current_workspace_id

    if current_workspace_id():
        return None
    for partner in visible_partners():
        partner_id = str(partner.get("partner_id") or "").strip()
        if not partner_id:
            continue
        with user_context(partner_user(partner_id)):
            try:
                return get_content_workspace_service().resolve_published_item(
                    workspace_id, workspace_item_id
                )
            except WorkspaceError:
                continue
    return None


@files_router.get("/{workspace_id}/{workspace_item_id}", operation_id="read_workspace_item_get")
@files_router.head("/{workspace_id}/{workspace_item_id}", operation_id="read_workspace_item_head")
async def read_workspace_item(
    workspace_id: str,
    workspace_item_id: str,
    _auth: TokenPayload | None = Depends(require_auth),
) -> FileResponse:
    try:
        path, item = get_content_workspace_service().resolve_published_item(
            workspace_id, workspace_item_id
        )
    except WorkspaceError as exc:
        resolved = _resolve_partner_item(workspace_id, workspace_item_id)
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
            ) from exc
        path, item = resolved
    return FileResponse(
        path,
        media_type=item.mime_type,
        filename=item.filename,
        content_disposition_type="inline",
        headers={
            "ETag": f'"{item.sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            # Presented files are user/model-controlled. Opening an HTML or
            # SVG snapshot directly on the app origin must never execute it
            # with access to DeepTutor's authenticated origin.
            "Content-Security-Policy": (
                "sandbox; default-src 'none'; img-src data: blob:; "
                "media-src 'self' blob:; style-src 'unsafe-inline'"
            ),
        },
    )


__all__ = ["files_router", "settings_router"]
