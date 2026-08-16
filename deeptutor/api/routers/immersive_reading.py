"""REST API for source-faithful Immersive Reading."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
from pathlib import Path
import time
from typing import Any, Literal
import uuid

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.service import MAX_UPLOAD_BYTES
from deeptutor.services.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigError,
    LLMError,
    LLMModelNotFoundError,
    LLMParseError,
    LLMRateLimitError,
    LLMTimeoutError,
)

router = APIRouter()
logger = logging.getLogger(__name__)

_SEARCH_JOB_TTL_SECONDS = 30 * 60
_SEARCH_JOB_LIMIT = 100
_search_jobs: dict[str, dict[str, Any]] = {}


class ProgressRequest(BaseModel):
    section_id: str
    scroll_percent: float = Field(default=0, ge=0, le=100)


class EpubProgressRequest(BaseModel):
    epub_cfi: str = Field(default="", max_length=2000)
    section_href: str = Field(default="", max_length=500)
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


class DictionaryRequest(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=4000)


class VocabRequest(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=4000)
    document_id: str = Field(default="", max_length=80)
    document_title: str = Field(default="", max_length=500)
    section_title: str = Field(default="", max_length=500)


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


def _original_media_type(path, source_format: str) -> str:
    fmt = (source_format or path.suffix.lstrip(".")).lower()
    if fmt == "epub" or path.suffix.lower() == ".epub":
        return "application/epub+zip"
    if fmt == "pdf" or path.suffix.lower() == ".pdf":
        return "application/pdf"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


@router.get("/documents/{document_id}/original")
async def get_original(document_id: str):
    service = get_immersive_reading_service()
    try:
        path = service.original_path(document_id)
        document = service.load_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    source_format = document.source_format if document else path.suffix.lstrip(".")
    return FileResponse(
        path,
        media_type=_original_media_type(path, source_format),
        filename=document.source_filename if document else path.name,
        content_disposition_type="inline",
    )


@router.get("/documents/{document_id}/sections/{section_id}")
async def get_section(document_id: str, section_id: str) -> dict:
    try:
        return get_immersive_reading_service().get_section(document_id, section_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/documents/{document_id}/epub-progress")
async def update_epub_progress(document_id: str, request: EpubProgressRequest) -> dict:
    try:
        progress = get_immersive_reading_service().update_epub_progress(
            document_id,
            epub_cfi=request.epub_cfi,
            section_href=request.section_href,
            scroll_percent=request.scroll_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"progress": progress.model_dump(mode="json")}


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
        progress = get_immersive_reading_service().skip_section(document_id, request.section_id)
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
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except LLMModelNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMAuthenticationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LLMError as exc:
        if getattr(exc, "status_code", None) == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Translation failed unexpectedly")
        raise HTTPException(
            status_code=500, detail="Translation failed. Please try again."
        ) from exc
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


@router.post("/dictionary")
async def dictionary_lookup(request: DictionaryRequest) -> dict:
    """Context-aware dictionary lookup with offline-first fallbacks."""
    try:
        service = get_immersive_reading_service()
        if hasattr(service, "lookup_word"):
            result = await service.lookup_word(request.word, request.context)
            return result.model_dump(mode="json")
        return await service.lookup_dictionary(request.word, request.context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except LLMModelNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMParseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMError as exc:
        if getattr(exc, "status_code", None) == 503:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.get("/dictionary/status")
async def dictionary_status() -> dict:
    return get_immersive_reading_service().dictionary_status()


@router.post("/dictionary/ecdict/import")
async def import_ecdict_csv(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload an ECDICT CSV export.")

    import tempfile

    max_bytes = 2 * 1024 * 1024 * 1024
    written = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ecdict-", suffix=".csv", delete=False) as target:
            temporary = Path(target.name)
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail="ECDICT CSV exceeds 2 GB.")
                target.write(chunk)
        await file.close()
        count = await asyncio.to_thread(
            get_immersive_reading_service().import_ecdict_csv,
            temporary,
        )
        return {"imported": True, "entries": count}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ECDICT import failed")
        raise HTTPException(status_code=500, detail=f"ECDICT import failed: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@router.post("/vocabulary")
async def add_vocabulary_word(request: VocabRequest) -> dict:
    """Save a word to the global vocabulary book with dictionary lookup."""
    try:
        entry = await get_immersive_reading_service().add_word(
            request.word,
            context=request.context,
            document_id=request.document_id,
            document_title=request.document_title,
            section_title=request.section_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vocabulary lookup failed: {exc}") from exc
    # The dictionary lookup is best-effort in the service layer; an empty
    # definition list means the LLM lookup failed but the word was still saved.
    lookup_warning = (
        "" if entry.definitions else "Definition unavailable; word saved without meaning."
    )
    return {"entry": entry.model_dump(mode="json"), "lookup_warning": lookup_warning}


@router.get("/vocabulary")
async def list_vocabulary(document_id: str | None = None) -> dict:
    entries = get_immersive_reading_service().list_vocabulary(document_id)
    return {"entries": [item.model_dump(mode="json") for item in entries]}


@router.delete("/vocabulary/{entry_id}")
async def delete_vocabulary_word(entry_id: str) -> dict:
    try:
        get_immersive_reading_service().delete_word(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True, "entry_id": entry_id}


class CharacterGraphRequest(BaseModel):
    section_id: str
    scope: Literal["current", "through_current"] = "current"
    force_refresh: bool = False


@router.post("/documents/{document_id}/character-graph")
async def character_graph(document_id: str, request: CharacterGraphRequest) -> dict:
    """Generate a character relationship graph for an immersive reading document."""
    from deeptutor.book.character_graph import (
        extract_character_graph,
        render_character_graph_mermaid,
    )

    service = get_immersive_reading_service()
    doc = service.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    sections = doc.sections
    target_index = next(
        (index for index, section in enumerate(sections) if section.id == request.section_id),
        None,
    )
    if target_index is None:
        raise HTTPException(status_code=404, detail="Section not found")

    if request.scope == "current":
        chosen = [sections[target_index]] if target_index < len(sections) else []
    else:
        chosen = sections[: target_index + 1]

    texts: list[str] = []
    for section in chosen:
        try:
            result = service.get_section(document_id, section.id)
            texts.append(result.get("content", ""))
        except Exception:
            pass

    combined = "\n\n".join(texts)
    if not combined.strip():
        return {
            "graph": {"nodes": [], "edges": []},
            "mermaid": 'graph LR\n  empty["No characters found"]',
        }

    content_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

    cache_path = (
        service._document_root(document_id) / f"character_graph_{request.scope}_{content_hash}.json"
    )
    if not request.force_refresh and cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    language = "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in combined[:500]) else "en"

    try:
        graph = await extract_character_graph(
            text=combined,
            language=language,
            included_chapter_ids=[s.id for s in chosen],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Character graph extraction failed: {exc}"
        ) from exc

    mermaid = render_character_graph_mermaid(graph)
    payload = {
        "graph": {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "aliases": n.aliases,
                    "description": n.description,
                }
                for n in graph.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "confidence": e.confidence,
                }
                for e in graph.edges
            ],
        },
        "mermaid": mermaid,
        "generated_at": time.time(),
        "scope": request.scope,
        "section_id": request.section_id,
    }

    try:
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return payload


# ── Bilingual paired reading ────────────────────────────────────────────

from deeptutor.immersive_reading.bilingual.service import get_pairing_service


class PairRequest(BaseModel):
    en_document_id: str
    zh_document_id: str
    target_lang: str | None = None
    translator: str = ""


class ChapterMapUpdateRequest(BaseModel):
    chapter_map: list[Any]


class AnnotationRequest(BaseModel):
    chapter_id: str
    group_index: int
    issue_type: Literal[
        "misalignment", "wrong_chapter", "missing_translation", "translation_error", "other"
    ]
    note: str = Field(default="", max_length=4000)


class ResolveAnnotationRequest(BaseModel):
    resolved: bool = True


class AlignmentOverridesRequest(BaseModel):
    overrides_json: str = Field(min_length=2, max_length=100_000)


class ReadingPositionRequest(BaseModel):
    chapter_index: int = Field(default=0, ge=0)
    group_index: int = Field(default=0, ge=0)
    epub_cfi: str = Field(default="", max_length=2000)
    section_href: str = Field(default="", max_length=500)
    scroll_percent: float = Field(default=0, ge=0, le=100)
    text_fingerprint: str = Field(default="", max_length=500)


class BookmarkRequest(BaseModel):
    position: ReadingPositionRequest
    title: str = Field(default="", max_length=200)
    preview: str = Field(default="", max_length=300)


class RenameBookmarkRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.post("/bilingual/pair")
async def bilingual_pair(request: PairRequest) -> dict[str, Any]:
    """Create a bilingual pairing from two imported reading documents."""
    try:
        return get_pairing_service().pair_documents(
            en_document_id=request.en_document_id,
            zh_document_id=request.zh_document_id,
            target_lang=request.target_lang,
            translator=request.translator,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bilingual")
async def bilingual_list_pairings() -> dict[str, Any]:
    """List all bilingual pairings."""
    return {"pairings": get_pairing_service().list_pairings()}


@router.get("/bilingual/{pairing_id}")
async def bilingual_get_pairing(pairing_id: str) -> dict[str, Any]:
    """Get pairing details + chapter map."""
    try:
        return get_pairing_service().get_pairing(pairing_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/bilingual/{pairing_id}/chapter-map")
async def bilingual_update_chapter_map(
    pairing_id: str, request: ChapterMapUpdateRequest
) -> dict[str, Any]:
    """Replace the chapter map with a user-edited version."""
    try:
        return get_pairing_service().update_chapter_map(pairing_id, request.chapter_map)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bilingual/{pairing_id}/align")
async def bilingual_align(pairing_id: str, force: bool = False) -> dict[str, Any]:
    """Run or re-run paragraph alignment for all mapped chapters."""
    try:
        return await asyncio.to_thread(get_pairing_service().align, pairing_id, force)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bilingual/{pairing_id}/section/{chapter_id}")
async def bilingual_get_section(pairing_id: str, chapter_id: str) -> dict[str, Any]:
    """Get aligned paragraph pairs for one chapter."""
    try:
        return get_pairing_service().get_bilingual_section(pairing_id, chapter_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bilingual/{pairing_id}/report")
async def bilingual_get_report(pairing_id: str) -> dict[str, Any]:
    """Get the alignment review report."""
    try:
        return {"report": get_pairing_service().get_report(pairing_id)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bilingual/{pairing_id}/export")
async def bilingual_export(pairing_id: str) -> FileResponse:
    """Build and download a bilingual EPUB."""
    try:
        epub_path = await asyncio.to_thread(get_pairing_service().export_epub, pairing_id)
        return FileResponse(
            path=str(epub_path),
            media_type="application/epub+zip",
            filename=epub_path.name,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bilingual/{pairing_id}/reading-position")
async def bilingual_get_reading_position(pairing_id: str) -> dict[str, Any]:
    try:
        return {"position": get_pairing_service().load_reading_position(pairing_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/bilingual/{pairing_id}/reading-position")
async def bilingual_update_reading_position(
    pairing_id: str, request: ReadingPositionRequest
) -> dict[str, Any]:
    try:
        position = get_pairing_service().update_reading_position(pairing_id, request.model_dump())
        return {"position": position}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/bilingual/{pairing_id}/bookmarks")
async def bilingual_list_bookmarks(pairing_id: str) -> dict[str, Any]:
    try:
        return {"bookmarks": get_pairing_service().list_bookmarks(pairing_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bilingual/{pairing_id}/bookmarks")
async def bilingual_add_bookmark(pairing_id: str, request: BookmarkRequest) -> dict[str, Any]:
    try:
        return get_pairing_service().add_bookmark(
            pairing_id,
            request.position.model_dump(),
            title=request.title,
            preview=request.preview,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/bilingual/{pairing_id}/bookmarks/{bookmark_id}")
async def bilingual_rename_bookmark(
    pairing_id: str, bookmark_id: str, request: RenameBookmarkRequest
) -> dict[str, Any]:
    try:
        return get_pairing_service().rename_bookmark(pairing_id, bookmark_id, request.title)
    except ValueError as exc:
        message = str(exc)
        status = 404 if message == "Bookmark not found" else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.delete("/bilingual/{pairing_id}/bookmarks/{bookmark_id}")
async def bilingual_delete_bookmark(pairing_id: str, bookmark_id: str) -> dict[str, Any]:
    try:
        get_pairing_service().delete_bookmark(pairing_id, bookmark_id)
        return {"status": "deleted", "bookmark_id": bookmark_id}
    except ValueError as exc:
        message = str(exc)
        status = 404 if message == "Bookmark not found" else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/bilingual/{pairing_id}/navigation")
async def bilingual_get_navigation(pairing_id: str) -> dict[str, Any]:
    try:
        return {"navigation": get_pairing_service().get_navigation(pairing_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bilingual/{pairing_id}/navigation")
async def bilingual_record_navigation(
    pairing_id: str, request: ReadingPositionRequest
) -> dict[str, Any]:
    try:
        navigation = get_pairing_service().record_navigation(pairing_id, request.model_dump())
        return {"navigation": navigation}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bilingual/{pairing_id}/navigation/back")
async def bilingual_navigate_back(pairing_id: str) -> dict[str, Any]:
    try:
        position, navigation = get_pairing_service().navigate_back(pairing_id)
        return {"position": position, "navigation": navigation}
    except ValueError as exc:
        message = str(exc)
        status = 409 if message == "No back navigation destination" else 404
        raise HTTPException(status_code=status, detail=message) from exc


@router.post("/bilingual/{pairing_id}/navigation/forward")
async def bilingual_navigate_forward(pairing_id: str) -> dict[str, Any]:
    try:
        position, navigation = get_pairing_service().navigate_forward(pairing_id)
        return {"position": position, "navigation": navigation}
    except ValueError as exc:
        message = str(exc)
        status = 409 if message == "No forward navigation destination" else 404
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/bilingual/{pairing_id}/annotations")
async def bilingual_list_annotations(pairing_id: str, status: str | None = None) -> dict[str, Any]:
    """List annotations, optionally filtered by status."""
    try:
        annotations = get_pairing_service().list_annotations(pairing_id, status)
        return {"annotations": annotations}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bilingual/{pairing_id}/annotations")
async def bilingual_add_annotation(pairing_id: str, request: AnnotationRequest) -> dict[str, Any]:
    """Flag a paragraph-group alignment issue for review."""
    try:
        return get_pairing_service().add_annotation(
            pairing_id=pairing_id,
            chapter_id=request.chapter_id,
            group_index=request.group_index,
            issue_type=request.issue_type,
            note=request.note,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/bilingual/{pairing_id}/annotations/{annotation_id}")
async def bilingual_resolve_annotation(
    pairing_id: str, annotation_id: str, request: ResolveAnnotationRequest
) -> dict[str, Any]:
    """Mark an annotation as resolved or reopen it."""
    try:
        return get_pairing_service().resolve_annotation(pairing_id, annotation_id, request.resolved)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/bilingual/{pairing_id}/annotations/{annotation_id}")
async def bilingual_delete_annotation(pairing_id: str, annotation_id: str) -> dict[str, Any]:
    """Delete an annotation."""
    try:
        get_pairing_service().delete_annotation(pairing_id, annotation_id)
        return {"status": "deleted"}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/bilingual/{pairing_id}/review-report")
async def bilingual_review_report(pairing_id: str) -> dict[str, Any]:
    """Export all open annotations as a structured markdown report for Codex."""
    try:
        report_path = get_pairing_service().export_review_report(pairing_id)
        return {"report": report_path.read_text(encoding="utf-8")}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/bilingual/{pairing_id}/alignment-overrides")
async def bilingual_save_overrides(
    pairing_id: str, request: AlignmentOverridesRequest
) -> dict[str, Any]:
    """Save alignment overrides JSON (e.g. produced by Codex from the review report).

    After saving, call POST /bilingual/{pairing_id}/align?force=true to re-align.
    """
    try:
        return get_pairing_service().save_alignment_overrides(pairing_id, request.overrides_json)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/bilingual/{pairing_id}")
async def bilingual_delete(pairing_id: str) -> dict[str, Any]:
    """Delete a bilingual pairing."""
    try:
        get_pairing_service().delete_pairing(pairing_id)
        return {"status": "deleted", "pairing_id": pairing_id}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception("Bilingual API error")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Kids experience mode ───────────────────────────────────────────────────


class ExperienceModeRequest(BaseModel):
    mode: Literal["standard", "kids"] = "kids"


class KidsQuizRequest(BaseModel):
    section_id: str
    force_refresh: bool = False


class KidsProgressRequest(BaseModel):
    section_id: str
    scroll_percent: float = Field(default=0, ge=0, le=100)
    epub_cfi: str = Field(default="", max_length=500)
    section_href: str = Field(default="", max_length=500)


@router.put("/documents/{document_id}/experience-mode")
async def set_experience_mode(document_id: str, request: ExperienceModeRequest):
    try:
        return get_immersive_reading_service().set_experience_mode(document_id, request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/documents/{document_id}/kids-quiz")
async def generate_kids_quiz(document_id: str, request: KidsQuizRequest):
    try:
        result = await get_immersive_reading_service().generate_kids_quiz(
            document_id, request.section_id, force_refresh=request.force_refresh
        )
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Kids quiz generation failed document=%s", document_id)
        raise HTTPException(status_code=502, detail=f"Quiz generation failed: {exc}") from exc


@router.put("/documents/{document_id}/kids-progress")
async def update_kids_progress(document_id: str, request: KidsProgressRequest):
    try:
        progress = get_immersive_reading_service().update_kids_progress(
            document_id,
            request.section_id,
            scroll_percent=request.scroll_percent,
            epub_cfi=request.epub_cfi,
            section_href=request.section_href,
        )
        return {"progress": progress.model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
