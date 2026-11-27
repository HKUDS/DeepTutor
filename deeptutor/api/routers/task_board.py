"""Each workspace's task board, kept in one account store.

The router sits outside request scope installation (see ``auth.py``) so its
event stream never holds a workspace activity lease; it resolves the board's
workspace from the same header/query itself.
"""

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
    workspace_board,
)
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.models import WorkspaceError

router = APIRouter()


def board_workspace(request: Request) -> str:
    raw = request.headers.get("x-deeptutor-workspace") or request.query_params.get("dt_workspace")
    try:
        with workspace_context(raw or "") as scope:
            return scope.workspace_id
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=TaskBoard)
def get_board(request: Request) -> TaskBoard:
    return workspace_board(get_task_board_store().read(), board_workspace(request))


@router.get("/events")
async def board_events(request: Request):
    # Resolve once before streaming; each connection retains its account identity.
    workspace_id = board_workspace(request)
    store = await asyncio.to_thread(get_task_board_store)

    async def events():
        revision = -1
        heartbeat = 0
        while not await request.is_disconnected():
            current_revision = await asyncio.to_thread(store.revision)
            if current_revision != revision:
                board = workspace_board(await asyncio.to_thread(store.read), workspace_id)
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
def create_card(payload: CreateCard, request: Request) -> TaskBoard:
    workspace_id = board_workspace(request)
    return workspace_board(get_task_board_store().create(payload, workspace_id), workspace_id)


@router.patch("/cards/{card_id}", response_model=TaskBoard)
def update_card(card_id: str, payload: UpdateCard, request: Request) -> TaskBoard:
    workspace_id = board_workspace(request)
    try:
        if "workspace_id" in payload.model_fields_set and payload.workspace_id is not None:
            with workspace_context(payload.workspace_id) as scope:
                payload.workspace_id = scope.workspace_id
                if scope.archived:
                    raise WorkspaceError("Restore this workspace before assigning tasks.")
        return workspace_board(
            get_task_board_store().update(card_id, payload, workspace_id=workspace_id), workspace_id
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task card not found.") from exc


@router.put("/colors", response_model=TaskBoard)
def update_colors(payload: StatusColors, request: Request) -> TaskBoard:
    workspace_id = board_workspace(request)
    return workspace_board(get_task_board_store().set_colors(payload), workspace_id)


async def require_session(session_id: str, workspace_id: str, board_workspace_id: str) -> str:
    from deeptutor.services.session import get_session_store

    try:
        with workspace_context(workspace_id) as scope:
            if scope.workspace_id != board_workspace_id:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            if scope.archived:
                raise WorkspaceError("Restore this workspace before changing its conversations.")
            if await get_session_store().get_session(session_id) is None:
                raise HTTPException(status_code=404, detail="Conversation not found.")
            return scope.workspace_id
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/sessions/{session_id}", response_model=TaskBoard)
async def link_tasks(session_id: str, payload: LinkTasks, request: Request) -> TaskBoard:
    workspace_id = board_workspace(request)
    payload.workspace_id = await require_session(session_id, payload.workspace_id, workspace_id)
    try:
        board = await asyncio.to_thread(get_task_board_store().link_tasks, session_id, payload)
        return workspace_board(board, workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found or archived.") from exc


@router.patch("/sessions/{session_id}/status", response_model=TaskBoard)
async def link_status(session_id: str, payload: LinkStatus, request: Request) -> TaskBoard:
    workspace_id = board_workspace(request)
    payload.workspace_id = await require_session(session_id, payload.workspace_id, workspace_id)
    board = await asyncio.to_thread(get_task_board_store().link_status, session_id, payload)
    return workspace_board(board, workspace_id)
