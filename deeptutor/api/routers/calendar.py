"""Authenticated account calendar and workspace-local learning overlays."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from deeptutor.services.calendar import models as m
from deeptutor.services.calendar.layers import owner_key, read_layers
from deeptutor.services.calendar.recurrence import parse_instant, zone
from deeptutor.services.calendar.store import get_calendar_store
from deeptutor.services.workspace.context import workspace_context

from .task_board import board_workspace

router = APIRouter()


@contextmanager
def errors():
    try:
        yield
    except KeyError as exc:
        raise HTTPException(404, "Calendar item not found.") from exc
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def bounds(start, end, tz):
    with errors():
        first, last = parse_instant(start), parse_instant(end)
        zone(tz)
        if not first < last or last - first > timedelta(days=400):
            raise ValueError("Choose a range between one second and 400 days.")
        return first, last


def validate_task(payload, request):
    from deeptutor.services.task_board import get_task_board_store, workspace_board

    if (
        "task_workspace_id" in payload.model_fields_set
        and "task_id" not in payload.model_fields_set
    ):
        raise HTTPException(400, "Change the task and its workspace together.")
    if not payload.task_id:
        return
    workspace_id = board_workspace(request)
    if payload.task_workspace_id not in (None, workspace_id):
        raise HTTPException(404, "Task not found in this workspace.")
    if not any(
        c.id == payload.task_id and not c.archived
        for c in workspace_board(get_task_board_store().read(), workspace_id).cards
    ):
        raise HTTPException(404, "Task not found in this workspace.")
    payload.task_workspace_id = workspace_id


@router.get("/calendars", response_model=m.CalendarList)
def calendars():
    return get_calendar_store().calendars()


@router.post("/calendars", response_model=m.CalendarResponse, status_code=201)
def create_calendar(payload: m.CreateCalendar):
    return get_calendar_store().create_calendar(payload)


@router.patch("/calendars/{id}", response_model=m.CalendarResponse)
def update_calendar(id: str, payload: m.UpdateCalendar):
    with errors():
        return get_calendar_store().update_calendar(id, payload)


@router.delete("/calendars/{id}", response_model=m.CalendarRevision)
def delete_calendar(id: str):
    with errors():
        return get_calendar_store().delete_calendar(id)


@router.get("/events", response_model=m.OccurrenceList)
def events(start: str, end: str, tz: str = "UTC"):
    first, last = bounds(start, end, tz)
    with errors():
        return get_calendar_store().occurrences(first, last, tz)


@router.post("/events", response_model=m.CalendarEventResponse, status_code=201)
def create_event(payload: m.EventInput, request: Request):
    validate_task(payload, request)
    with errors():
        return get_calendar_store().create(payload)


@router.patch("/events/{id}", response_model=m.CalendarRevision)
def update_event(id: str, payload: m.EventPatchRequest, request: Request):
    validate_task(payload.changes, request)
    with errors():
        return get_calendar_store().update(id, payload)


@router.delete("/events/{id}")
def delete_event(id: str, scope: m.Scope = "all", occurrence: str | None = None):
    with errors():
        return get_calendar_store().delete(id, scope, occurrence)


@router.post("/undo/{token}", response_model=m.CalendarRevision)
def undo(token: str):
    with errors():
        return get_calendar_store().restore(token)


@router.get("/search", response_model=m.CalendarSearchResponse)
def search(
    q: str = Query(min_length=1, max_length=200), limit: int = Query(default=50, ge=1, le=100)
):
    with errors():
        return get_calendar_store().search(q, limit)


@router.get("/layers", response_model=m.CalendarLayers)
def layers(request: Request, start: str, end: str, tz: str = "UTC"):
    first, last = bounds(start, end, tz)
    workspace_id = board_workspace(request)
    with workspace_context(workspace_id):
        return read_layers(workspace_id, first, last, tz)


@router.delete("/automations/{job_id}", response_model=m.CalendarOk)
def cancel_automation(job_id: str, request: Request):
    from deeptutor.services.cron.service import get_cron_service

    service = get_cron_service()
    job = service.get_job(job_id)
    if (
        not job
        or job.owner.key != owner_key()
        or job.owner.kind != "chat"
        or job.owner.workspace_id != board_workspace(request)
    ):
        raise HTTPException(404, "Automation not found.")
    return {"ok": service.cancel_job(job_id, owner_key=owner_key())}


@router.get("/stream")
async def stream(request: Request):
    store = await asyncio.to_thread(get_calendar_store)

    async def changes():
        revision = -1
        tick = 0
        while not await request.is_disconnected():
            current = await asyncio.to_thread(store.revision)
            if current != revision:
                revision = current
                yield f'id: {revision}\ndata: {{"revision":{revision}}}\n\n'
            elif tick % 30 == 0:
                yield ": heartbeat\n\n"
            tick += 1
            await asyncio.sleep(0.5)

    return StreamingResponse(
        changes(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Content-Encoding": "identity",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/task-blocks", response_model=dict[str, int])
def task_blocks(request: Request):
    return get_calendar_store().task_blocks(board_workspace(request))
