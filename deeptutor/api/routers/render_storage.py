"""Authenticated storage actions for published Math Animator artifacts."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.session_handoff import is_loopback_host
from deeptutor.services.auth import TokenPayload
from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service
from deeptutor.services.workspace.render_storage import (
    clean_render_storage,
    inspect_chat_exec_output,
    inspect_render_storage,
    remove_chat_exec_output,
)

router = APIRouter()


class RenderCleanupPayload(BaseModel):
    """Bind cleanup to the storage inventory reviewed by the caller."""

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class GeneratedOutputCleanupPayload(BaseModel):
    """Bind deletion to the file details reviewed by the caller."""

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def _local_browser(request: Request, *, require_origin: bool = False) -> bool:
    origin = request.headers.get("origin", "")
    host = request.headers.get("x-deeptutor-frontend-host") or request.url.hostname or ""
    try:
        origin_host = urlsplit(origin).hostname or ""
    except ValueError:
        return False
    return bool(
        sys.platform == "darwin"
        and request.client
        and is_loopback_host(request.client.host)
        and is_loopback_host(host)
        and (not require_origin or origin)
        and (not origin or is_loopback_host(origin_host))
    )


@router.get("/{workspace_id}/{workspace_item_id}/render-storage")
async def render_storage(
    workspace_id: str,
    workspace_item_id: str,
    request: Request,
    _auth: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Return the original path and a preview of reproducible render files."""
    try:
        result = await asyncio.to_thread(
            inspect_render_storage, get_content_workspace_service(), workspace_id, workspace_item_id
        )
    except (WorkspaceError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**result, "can_reveal": _local_browser(request)}


@router.post("/{workspace_id}/{workspace_item_id}/clean-render-cache")
async def clean_render_cache(
    workspace_id: str,
    workspace_item_id: str,
    payload: RenderCleanupPayload,
    request: Request,
    _auth: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Clean a reviewed render directory while excluding active writers."""
    from deeptutor.services.session import get_session_store
    from deeptutor.services.workspace.activity import data_activity
    from deeptutor.services.workspace.data_migration import assert_no_pending_recovery

    # 当前请求的共享租约需要先释放，才能取得排斥渲染和迁移的独占租约。
    lease = getattr(request.state, "workspace_activity", None)
    if lease is not None:
        lease.close()
        del request.state.workspace_activity

    async def perform() -> dict:
        with data_activity(exclusive=True):
            assert_no_pending_recovery(reject_unreadable=True)
            if await get_session_store().list_nonterminal_turns():
                raise WorkspaceError("Wait for running conversations to finish before cleanup.")
            return await asyncio.to_thread(
                clean_render_storage,
                get_content_workspace_service(),
                workspace_id,
                workspace_item_id,
                payload.fingerprint,
            )

    task = asyncio.create_task(perform())
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    try:
        return await asyncio.shield(task)
    except (WorkspaceError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workspace_id}/{workspace_item_id}/reveal")
async def reveal_render_file(
    workspace_id: str,
    workspace_item_id: str,
    request: Request,
    _auth: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Select an artifact in the local desktop file manager."""
    if not _local_browser(request, require_origin=True):
        raise HTTPException(
            status_code=403, detail="Reveal is available only from a local browser."
        )
    try:
        storage = await asyncio.to_thread(
            inspect_render_storage, get_content_workspace_service(), workspace_id, workspace_item_id
        )
        path = storage["file_path"]
        command = ["open", "-R", path]
        await asyncio.to_thread(subprocess.run, command, check=True, timeout=5, capture_output=True)
    except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=409, detail="Unable to reveal this file.") from exc
    return {"revealed": True}


@router.get("/{workspace_id}/{workspace_item_id}/file-storage")
async def chat_output_file_storage(
    workspace_id: str,
    workspace_item_id: str,
    request: Request,
    _auth: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Return the local path of a generated chat tool attachment."""
    try:
        result = await asyncio.to_thread(
            inspect_chat_exec_output,
            get_content_workspace_service(),
            workspace_id,
            workspace_item_id,
        )
    except (WorkspaceError, OSError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**result, "can_reveal": _local_browser(request)}


@router.post("/{workspace_id}/{workspace_item_id}/remove-generated-output")
async def remove_chat_output_file(
    workspace_id: str,
    workspace_item_id: str,
    payload: GeneratedOutputCleanupPayload,
    request: Request,
    _auth: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Remove an unchanged workspace copy while retaining the chat snapshot."""
    from deeptutor.services.session import get_session_store
    from deeptutor.services.workspace.activity import data_activity
    from deeptutor.services.workspace.data_migration import assert_no_pending_recovery

    lease = getattr(request.state, "workspace_activity", None)
    if lease is not None:
        lease.close()
        del request.state.workspace_activity

    async def perform() -> dict:
        with data_activity(exclusive=True):
            assert_no_pending_recovery(reject_unreadable=True)
            if await get_session_store().list_nonterminal_turns():
                raise WorkspaceError("Wait for running conversations to finish before cleanup.")
            return await asyncio.to_thread(
                remove_chat_exec_output,
                get_content_workspace_service(),
                workspace_id,
                workspace_item_id,
                payload.fingerprint,
            )

    task = asyncio.create_task(perform())
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    try:
        return await asyncio.shield(task)
    except (WorkspaceError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{workspace_id}/{workspace_item_id}/reveal-generated-output")
async def reveal_chat_output_file(
    workspace_id: str,
    workspace_item_id: str,
    request: Request,
    _auth: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Select a generated chat attachment in the local desktop file manager."""
    if not _local_browser(request, require_origin=True):
        raise HTTPException(
            status_code=403, detail="Reveal is available only from a local browser."
        )
    try:
        storage = await asyncio.to_thread(
            inspect_chat_exec_output,
            get_content_workspace_service(),
            workspace_id,
            workspace_item_id,
        )
        await asyncio.to_thread(
            subprocess.run,
            ["open", "-R", storage["file_path"]],
            check=True,
            timeout=5,
            capture_output=True,
        )
    except (WorkspaceError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=409, detail="Unable to reveal this file.") from exc
    return {"revealed": True}
