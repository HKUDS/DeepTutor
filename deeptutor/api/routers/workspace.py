"""Content-workspace settings and authenticated presentation delivery."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
