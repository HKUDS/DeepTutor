"""REST API for the generic translation task board."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .service import get_translation_task_service

router = APIRouter()


class PlanRequest(BaseModel):
    source_type: Literal["bilingual", "kb_document"]
    source_id: str = Field(min_length=1, max_length=300)
    force: bool = False


class RunRequest(BaseModel):
    limit: int = Field(default=4, ge=1, le=8)
    source_type: Literal["bilingual", "kb_document"] | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=300)
    chapter_id: str | None = Field(default=None, min_length=1, max_length=500)


class RetryFailedRequest(BaseModel):
    source_type: Literal["bilingual", "kb_document"] | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=300)


class GlossaryEntry(BaseModel):
    term: str = Field(min_length=1, max_length=300)
    translation: str = Field(default="", max_length=500)
    kind: str = Field(default="custom", max_length=50)
    frequency: int = Field(default=0, ge=0)
    protected: bool = False
    approved: bool = True
    decision: Literal["candidate", "approved", "rejected"] | None = None


class UpdateGlossaryRequest(BaseModel):
    source_type: Literal["bilingual", "kb_document"]
    source_id: str = Field(min_length=1, max_length=300)
    entries: list[GlossaryEntry] = Field(default_factory=list, max_length=500)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "translation-tasks"}


@router.get("/tasks")
async def list_tasks(
    source_type: Literal["bilingual", "kb_document"] | None = None,
    source_id: str | None = None,
    chapter_id: str | None = None,
    status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    return get_translation_task_service()._board(
        source_type=source_type,
        source_id=source_id,
        chapter_id=chapter_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/tasks/plan")
async def plan_tasks(request: PlanRequest) -> dict[str, Any]:
    try:
        return await get_translation_task_service().plan_with_review(
            request.source_type, request.source_id, force=request.force
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/tasks/run")
async def run_tasks(request: RunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    service = get_translation_task_service()
    run = service.start_run(
        limit=request.limit,
        source_type=request.source_type,
        source_id=request.source_id,
        chapter_id=request.chapter_id,
    )
    board = service._board(
        source_type=request.source_type,
        source_id=request.source_id,
        chapter_id=request.chapter_id,
    )
    if not run["task_ids"]:
        return {"started": False, "run_id": None, "selected_task_ids": [], "run": run, **board}
    background_tasks.add_task(
        service.run,
        run_id=run["run_id"],
    )
    return {
        "started": True,
        "run_id": run["run_id"],
        "selected_task_ids": run["task_ids"],
        "run": run,
        **board,
    }


@router.get("/tasks/runs/{run_id}/stream")
async def stream_translation_run(run_id: str) -> StreamingResponse:
    service = get_translation_task_service()
    try:
        run = service.get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.get("status") in {"completed", "failed", "cancelled"}:

        async def completed_stream():
            event_type = "run_cancelled" if run.get("status") == "cancelled" else "run_completed"
            payload = json.dumps(
                {
                    "type": event_type,
                    "run_id": run_id,
                    "sequence": int(run.get("sequence", 0)) + 1,
                    "completed": int(run.get("completed", 0)),
                    "failed": int(run.get("failed", 0)),
                    "board": service._board(
                        source_type=run.get("source_type"),
                        source_id=run.get("source_id"),
                        chapter_id=run.get("chapter_id"),
                    ),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: {event_type}\ndata: {payload}\n\n"

        return StreamingResponse(
            completed_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def event_stream():
        stream = service.subscribe(run_id=run_id)
        snapshot = await stream.asend(None)
        snapshot["board"] = service._board(
            source_type=run.get("source_type"),
            source_id=run.get("source_id"),
            chapter_id=run.get("chapter_id"),
        )
        yield _sse(snapshot)
        async for event in stream:
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tasks/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, Any]:
    try:
        return get_translation_task_service().cancel_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/stream")
async def stream_tasks(
    source_type: Literal["bilingual", "kb_document"] | None = None,
    source_id: str | None = None,
    chapter_id: str | None = None,
    limit: int = 8,
) -> StreamingResponse:
    """Deprecated compatibility wrapper around bounded run streams."""
    service = get_translation_task_service()
    run = service.start_run(
        limit=limit,
        source_type=source_type,
        source_id=source_id,
        chapter_id=chapter_id,
    )

    async def event_stream():
        if not run["task_ids"]:
            yield _sse(
                {
                    "type": "snapshot",
                    "run_id": None,
                    "sequence": 0,
                    "board": service._board(
                        source_type=source_type,
                        source_id=source_id,
                        chapter_id=chapter_id,
                    ),
                }
            )
            return

        stream = service.subscribe(run_id=run["run_id"])
        snapshot = await stream.asend(None)
        snapshot["board"] = service._board(
            source_type=source_type, source_id=source_id, chapter_id=chapter_id
        )
        yield _sse(snapshot)
        asyncio.create_task(service.run(run_id=run["run_id"]))
        async for event in stream:
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.get('type', 'task_updated')}\ndata: {payload}\n\n"


@router.get("/glossary")
async def get_glossary(
    source_type: Literal["bilingual", "kb_document"], source_id: str
) -> dict[str, Any]:
    try:
        return {
            "source_type": source_type,
            "source_id": source_id,
            "entries": get_translation_task_service().get_glossary(source_type, source_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/glossary")
async def update_glossary(request: UpdateGlossaryRequest) -> dict[str, Any]:
    try:
        return get_translation_task_service().update_glossary(
            request.source_type,
            request.source_id,
            [entry.model_dump() for entry in request.entries],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str) -> dict[str, Any]:
    try:
        return get_translation_task_service().retry(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/retry-failed")
async def retry_failed_tasks(request: RetryFailedRequest) -> dict[str, Any]:
    return get_translation_task_service().retry_failed(
        source_type=request.source_type, source_id=request.source_id
    )
