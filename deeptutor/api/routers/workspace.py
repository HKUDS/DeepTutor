"""Content-workspace settings and authenticated presentation delivery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from deeptutor.api.routers.auth import require_auth
from deeptutor.services.auth import TokenPayload
from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service

settings_router = APIRouter()
files_router = APIRouter()


class WorkspacePathPayload(BaseModel):
    path: str | None = None


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from exc
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
