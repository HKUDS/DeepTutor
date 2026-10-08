"""Independent account task board with workspace/conversation associations."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from deeptutor.services.task_board import (
    CreateCard,
    LinkStatus,
    LinkTasks,
    StatusColors,
    TaskBoard,
    UpdateCard,
    get_task_board_store,
)
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.models import WorkspaceError

router = APIRouter()


@router.get("", response_model=TaskBoard)
def get_board() -> TaskBoard:
    return get_task_board_store().read()


@router.get("/events")
async def board_events(request: Request):
    # Resolve once before streaming; each connection retains its account identity.
    store = await asyncio.to_thread(get_task_board_store)

    async def events():
        revision = -1
        heartbeat = 0
        while not await request.is_disconnected():
            current_revision = await asyncio.to_thread(store.revision)
            if current_revision != revision:
                board = await asyncio.to_thread(store.read)
                revision = board.revision
                yield f"id: {revision}\ndata: {board.model_dump_json()}\n\n"
            elif heartbeat % 30 == 0:
                yield ": heartbeat\n\n"
            heartbeat += 1
            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            # Next's proxy must flush each event instead of gzip-buffering it.
            "Cache-Control": "no-cache, no-transform",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/cards", response_model=TaskBoard, status_code=201)
def create_card(payload: CreateCard) -> TaskBoard:
    return get_task_board_store().create(payload)


@router.patch("/cards/{card_id}", response_model=TaskBoard)
def update_card(card_id: str, payload: UpdateCard) -> TaskBoard:
    try:
        if "workspace_id" in payload.model_fields_set and payload.workspace_id is not None:
            with workspace_context(payload.workspace_id) as scope:
                payload.workspace_id = scope.workspace_id
                if scope.archived:
                    raise WorkspaceError("Restore this workspace before assigning tasks.")
        return get_task_board_store().update(card_id, payload)
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task card not found.") from exc


@router.put("/colors", response_model=TaskBoard)
def update_colors(payload: StatusColors) -> TaskBoard:
    return get_task_board_store().set_colors(payload)


async def require_session(session_id: str, workspace_id: str) -> str:
    from deeptutor.services.session import get_session_store

    try:
        with workspace_context(workspace_id) as scope:
            if scope.archived:
                raise WorkspaceError("Restore this workspace before changing its conversations.")
            if await get_session_store().get_session(session_id) is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            return scope.workspace_id
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/sessions/{session_id}", response_model=TaskBoard)
async def link_tasks(session_id: str, payload: LinkTasks) -> TaskBoard:
    payload.workspace_id = await require_session(session_id, payload.workspace_id)
    try:
        return await asyncio.to_thread(get_task_board_store().link_tasks, session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found or archived.") from exc


@router.patch("/sessions/{session_id}/status", response_model=TaskBoard)
async def link_status(session_id: str, payload: LinkStatus) -> TaskBoard:
    payload.workspace_id = await require_session(session_id, payload.workspace_id)
    return await asyncio.to_thread(get_task_board_store().link_status, session_id, payload)
