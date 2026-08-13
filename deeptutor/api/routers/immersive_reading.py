"""REST API for source-faithful Immersive Reading."""

from __future__ import annotations

import logging
import time
from typing import Any, Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.service import MAX_UPLOAD_BYTES

router = APIRouter()
logger = logging.getLogger(__name__)

_SEARCH_JOB_TTL_SECONDS = 30 * 60
_SEARCH_JOB_LIMIT = 100
_search_jobs: dict[str, dict[str, Any]] = {}


class ProgressRequest(BaseModel):
    section_id: str
    scroll_percent: float = Field(default=0, ge=0, le=100)


class RestartRequest(BaseModel):
    reset_focus_checks: bool = False


class SkipSectionRequest(BaseModel):
    section_id: str = Field(min_length=1, max_length=80)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal["exact", "fuzzy", "description", "description_fast", "description_fine"] = "exact"


class CitationRequest(BaseModel):
    section_id: str
    quote: str = Field(min_length=1, max_length=12_000)
    note: str = Field(default="", max_length=4000)


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12_000)
    target_language: str = Field(default="Chinese", max_length=80)


class QuerySelectionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12_000)
    question: str = Field(default="", max_length=4000)
    language: Literal["zh", "en"] = "en"


class FocusCheckRequest(BaseModel):
    section_id: str
    summary: str = Field(min_length=1, max_length=20_000)
    reflection: str = Field(default="", max_length=12_000)
    language: Literal["zh", "en"] = "en"


async def _execute_search(document_id: str, request: SearchRequest) -> dict[str, Any]:
    service = get_immersive_reading_service()
    if request.mode == "description_fast":
        hits, metadata = await service.fast_description_search(document_id, request.query)
    else:
        hits = await service.search(document_id, request.query, request.mode)
        metadata = {
            "resolved_mode": (
                "description_fine"
                if request.mode in {"description", "description_fine"}
                else request.mode
            ),
            "fallback_used": False,
        }
    return {"hits": [hit.model_dump(mode="json") for hit in hits], **metadata}


def _prune_search_jobs(now: float) -> None:
    expired = [
        job_id
        for job_id, job in _search_jobs.items()
        if job.get("status") in {"completed", "failed"}
        and now - float(job.get("updated_at") or now) > _SEARCH_JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _search_jobs.pop(job_id, None)
    if len(_search_jobs) <= _SEARCH_JOB_LIMIT:
        return
    finished = sorted(
        (
            (float(job.get("updated_at") or 0), job_id)
            for job_id, job in _search_jobs.items()
            if job.get("status") in {"completed", "failed"}
        ),
    )
    for _updated_at, job_id in finished[: len(_search_jobs) - _SEARCH_JOB_LIMIT]:
        _search_jobs.pop(job_id, None)


async def _run_search_job(job_id: str, document_id: str, request: SearchRequest) -> None:
    job = _search_jobs.get(job_id)
    if job is None:
        return
    job.update(status="running", updated_at=time.time())
    try:
        result = await _execute_search(document_id, request)
    except Exception as exc:
        logger.exception(
            "Immersive-reading search job failed document=%s job=%s",
            document_id,
            job_id,
        )
        job.update(status="failed", error=str(exc), updated_at=time.time())
        return
    job.update(status="completed", result=result, updated_at=time.time())


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "immersive-reading"}


@router.get("/capabilities")
async def capabilities() -> dict:
    try:
        return get_immersive_reading_service().model_capabilities()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _queue_missing_fast_index(background_tasks: BackgroundTasks, document_id: str) -> None:
    service = get_immersive_reading_service()
    status = service.fast_index_status(document_id)
    should_resume = status["status"] == "partial" and not status["errors"]
    if status["status"] in {"not_started", "stale"} or should_resume:
        if service.fast_index_needs_build(document_id):
            background_tasks.add_task(service.build_fast_index, document_id)


@router.get("/documents")
async def list_documents(background_tasks: BackgroundTasks) -> dict:
    service = get_immersive_reading_service()
    documents = service.list_documents()
    for document in documents:
        _queue_missing_fast_index(background_tasks, document["id"])
    return {"documents": documents}


@router.post("/documents/import")
async def import_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict:
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        service = get_immersive_reading_service()
        document = service.import_document(file.filename or "book.txt", raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Book import failed: {exc}") from exc
    background_tasks.add_task(service.build_fast_index, document["id"])
    return {"document": document}


@router.get("/documents/{document_id}")
async def get_document(document_id: str, background_tasks: BackgroundTasks) -> dict:
    try:
        document = get_immersive_reading_service().document_detail(document_id)
        _queue_missing_fast_index(background_tasks, document_id)
        return {"document": document}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str) -> dict:
    try:
        get_immersive_reading_service().delete_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "document_id": document_id}


@router.get("/documents/{document_id}/cover")
async def get_cover(document_id: str):
    try:
        path = get_immersive_reading_service().cover_path(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", filename=f"{document_id}-cover.png")


@router.get("/documents/{document_id}/original")
async def get_original(document_id: str):
    service = get_immersive_reading_service()
    try:
        path = service.original_path(document_id)
        document = service.load_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=document.source_filename if document else path.name)


@router.get("/documents/{document_id}/sections/{section_id}")
async def get_section(document_id: str, section_id: str) -> dict:
    try:
        return get_immersive_reading_service().get_section(document_id, section_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/documents/{document_id}/progress")
async def update_progress(document_id: str, request: ProgressRequest) -> dict:
    try:
        progress = get_immersive_reading_service().update_progress(
            document_id, request.section_id, request.scroll_percent
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"progress": progress.model_dump(mode="json")}


@router.post("/documents/{document_id}/restart")
async def restart(document_id: str, request: RestartRequest) -> dict:
    try:
        progress = get_immersive_reading_service().restart(
            document_id, reset_focus_checks=request.reset_focus_checks
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"progress": progress.model_dump(mode="json")}


@router.post("/documents/{document_id}/skip-section")
async def skip_section(document_id: str, request: SkipSectionRequest) -> dict:
    try:
        progress = get_immersive_reading_service().skip_section(
            document_id, request.section_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"progress": progress.model_dump(mode="json")}


@router.post("/documents/{document_id}/search")
async def search(document_id: str, request: SearchRequest) -> dict:
    try:
        return await _execute_search(document_id, request)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/documents/{document_id}/search-jobs")
async def start_search_job(
    document_id: str,
    request: SearchRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    if request.mode not in {"description", "description_fast", "description_fine"}:
        raise HTTPException(
            status_code=400, detail="Search jobs are only used for description matching"
        )
    if get_immersive_reading_service().load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Reading document not found")
    now = time.time()
    _prune_search_jobs(now)
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "document_id": document_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "result": None,
        "error": "",
    }
    _search_jobs[job_id] = job
    background_tasks.add_task(_run_search_job, job_id, document_id, request)
    return {"job": job}


@router.get("/documents/{document_id}/search-jobs/{job_id}")
async def search_job_status(document_id: str, job_id: str) -> dict:
    job = _search_jobs.get(job_id)
    if job is None or job.get("document_id") != document_id:
        raise HTTPException(status_code=404, detail="Search job not found")
    return {"job": job}


@router.get("/documents/{document_id}/fast-search-index")
async def fast_search_index_status(document_id: str) -> dict:
    try:
        return {"index": get_immersive_reading_service().fast_index_status(document_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/fast-search-index/rebuild")
async def rebuild_fast_search_index(document_id: str, background_tasks: BackgroundTasks) -> dict:
    service = get_immersive_reading_service()
    try:
        status = service.fast_index_status(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(service.build_fast_index, document_id, force=True)
    return {"index": {**status, "status": "building", "needs_build": True}}


@router.post("/documents/{document_id}/focus-check")
async def focus_check(document_id: str, request: FocusCheckRequest) -> dict:
    try:
        result = await get_immersive_reading_service().focus_check(
            document_id,
            request.section_id,
            request.summary,
            request.reflection,
            request.language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Focus-Check failed: {exc}") from exc
    return result.model_dump(mode="json")


@router.get("/citations")
async def list_citations(document_id: str | None = None) -> dict:
    citations = get_immersive_reading_service().list_citations(document_id)
    return {"citations": [item.model_dump(mode="json") for item in citations]}


@router.post("/documents/{document_id}/citations")
async def add_citation(document_id: str, request: CitationRequest) -> dict:
    try:
        citation = get_immersive_reading_service().add_citation(
            document_id, request.section_id, request.quote, request.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"citation": citation.model_dump(mode="json")}


@router.delete("/citations/{citation_id}")
async def delete_citation(citation_id: str) -> dict:
    try:
        get_immersive_reading_service().delete_citation(citation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "citation_id": citation_id}


@router.post("/translate")
async def translate(request: TranslateRequest) -> dict:
    try:
        translated = await get_immersive_reading_service().translate(
            request.text, request.target_language
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Translation failed: {exc}") from exc
    return {"translation": translated}


@router.post("/query")
async def query_selection(request: QuerySelectionRequest) -> dict:
    try:
        result = await get_immersive_reading_service().query_selection(
            request.text, request.question, request.language
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Selection query failed: {exc}") from exc
    return result.model_dump(mode="json")
