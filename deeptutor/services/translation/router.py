"""REST API for the generic translation task board."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
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


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "translation-tasks"}


@router.get("/tasks")
async def list_tasks(
    source_type: Literal["bilingual", "kb_document"] | None = None,
    source_id: str | None = None,
    chapter_id: str | None = None,
    status: Literal["queued", "running", "completed", "failed"] | None = None,
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
        return await asyncio.to_thread(
            get_translation_task_service().plan,
            request.source_type,
            request.source_id,
            force=request.force,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/tasks/run")
async def run_tasks(request: RunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    service = get_translation_task_service()
    board = service._board(
        source_type=request.source_type,
        source_id=request.source_id,
        chapter_id=request.chapter_id,
    )
    if not board["summary"]["filtered_queued"]:
        return {"started": False, **board}
    background_tasks.add_task(
        service.run,
        request.limit,
        source_type=request.source_type,
        source_id=request.source_id,
        chapter_id=request.chapter_id,
    )
    return {"started": True, **board}


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
