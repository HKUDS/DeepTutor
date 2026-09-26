"""
Question Notebook API — persists quiz questions, bookmarks, and categories.
"""

from __future__ import annotations

import base64 as _b64
from hashlib import sha256 as _sha256
import logging
from typing import Any, Literal
import uuid as _uuid

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator

from deeptutor.core.assessment import AssessmentResult, AssessmentSource, QuestionOriginType
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.storage import get_attachment_store

logger = logging.getLogger(__name__)

router = APIRouter()
ScoreTrend = Literal["new", "improved", "declined", "unchanged"]

# ── Models ────────────────────────────────────────────────────────


class AnswerImageItem(BaseModel):
    """Persisted reference to one image attached to a learner's answer.

    The bytes live in the AttachmentStore at ``url``; we never round-trip
    base64 back to the client so notebook lookups stay cheap.
    """

    id: str = ""
    url: str = ""
    filename: str = ""
    mime_type: str = ""


class CategoryItem(BaseModel):
    id: int
    name: str
    created_at: float = 0
    entry_count: int = 0


class NotebookEntryItem(BaseModel):
    id: int
    session_id: str = ""
    session_title: str = ""
    origin_type: QuestionOriginType = "conversation"
    origin_ref: str = ""
    turn_id: str = ""
    question_id: str = ""
    question: str
    question_type: str = ""
    options: dict[str, str] = {}
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = ""
    user_answer: str = ""
    user_answer_images: list[AnswerImageItem] = []
    source: AssessmentSource = "deep_question"
    material_id: str = ""
    material_title: str = ""
    section_id: str = ""
    section_title: str = ""
    score_trend: ScoreTrend = "new"
    assessment_type: str = ""
    result: AssessmentResult | str = ""
    mastery_path_id: str = ""
    knowledge_point_id: str = ""
    attempt_count: int = 1
    hints_used: int = 0
    confidence: float | None = None
    response_time: float | None = None
    quality: float | None = None
    is_correct: bool = False
    resolved: bool = False
    bookmarked: bool = False
    followup_session_id: str = ""
    ai_judgment: str = ""
    created_at: float
    updated_at: float
    categories: list[CategoryItem] | None = None
    practice: dict[str, Any] | None = None


class NotebookEntryListResponse(BaseModel):
    items: list[NotebookEntryItem]
    total: int


class EntryUpdateRequest(BaseModel):
    bookmarked: bool | None = None
    followup_session_id: str | None = None
    ai_judgment: str | None = None
    resolved: bool | None = None


class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class CategoryAddRequest(BaseModel):
    category_id: int


class BulkCategoryRequest(BaseModel):
    """File (or unfile) many entries at once.

    One round-trip per bulk action keeps the list view consistent: the
    client re-reads once instead of racing N per-entry writes.
    """

    entry_ids: list[int] = Field(..., min_length=1, max_length=500)
    category_id: int
    link: bool = True


class QuestionBankStats(BaseModel):
    total: int = 0
    wrong: int = 0
    unresolved: int = 0
    bookmarked: int = 0
    uncategorized: int = 0


class QuestionBankMaterial(BaseModel):
    source: str
    material_id: str
    material_title: str
    entry_count: int
    unresolved_count: int


class AnswerImageUpload(BaseModel):
    """One image attached to the learner's answer.

    Either ``base64`` (new upload) or ``url`` (re-submit of an already
    persisted image) must be set. ``id`` is preserved when the client
    sends one so the same logical image keeps a stable AttachmentStore
    record across resubmissions.
    """

    id: str = ""
    base64: str = ""
    url: str = ""
    filename: str = "answer.png"
    mime_type: str = "image/png"


class UpsertEntryRequest(BaseModel):
    session_id: str = ""
    origin_type: QuestionOriginType = "conversation"
    origin_ref: str = ""
    turn_id: str = ""
    question_id: str
    question: str
    question_type: str = ""
    options: dict[str, str] | None = None
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = ""
    user_answer: str = ""
    # Optional: list of images attached as part of the learner's answer.
    # ``None`` means "don't touch any previously-stored images on update";
    # an empty list explicitly clears them.
    user_answer_images: list[AnswerImageUpload] | None = None
    source: AssessmentSource = "deep_question"
    material_id: str = ""
    material_title: str = ""
    section_id: str = ""
    section_title: str = ""
    is_correct: bool = False
    assessment_type: str = ""
    result: str = ""
    mastery_path_id: str = ""
    knowledge_point_id: str = ""
    attempt_count: int = 1
    hints_used: int = 0
    confidence: float | None = None
    response_time: float | None = None
    quality: float | None = None

    @model_validator(mode="after")
    def _validate_origin(self) -> "UpsertEntryRequest":
        self.session_id = self.session_id.strip()
        self.origin_ref = self.origin_ref.strip()
        if self.origin_type == "conversation":
            if not self.session_id:
                raise ValueError("conversation entries require session_id")
            if self.origin_ref and self.origin_ref != self.session_id:
                raise ValueError("conversation origin_ref must match session_id")
            self.origin_ref = self.session_id
        elif not self.origin_ref:
            raise ValueError(f"{self.origin_type} entries require origin_ref")
        return self


# ── Entry endpoints ──────────────────────────────────────────────


def _answer_image_owner(
    session_id: str,
    origin_type: str,
    origin_ref: str,
) -> str:
    """Stable AttachmentStore owner for conversation and independent entries."""
    if session_id:
        return session_id
    digest = _sha256(f"{origin_type}:{origin_ref}".encode()).hexdigest()[:24]
    return f"question-notebook-{digest}"


async def _persist_answer_images(
    owner_id: str, images: list[AnswerImageUpload] | None
) -> list[dict[str, str]] | None:
    """Materialise base64 image uploads into the AttachmentStore.

    Returns a list of ``{id, url, filename, mime_type}`` records suitable
    for ``notebook_entries.user_answer_images_json``. ``None`` is returned
    when ``images`` is ``None`` (no change to existing stored images).
    Records whose bytes fail to upload are dropped from the result with
    a warning — losing an image is better than failing the whole upsert.
    """
    if images is None:
        return None

    attachment_store = get_attachment_store()
    records: list[dict[str, str]] = []
    for image in images:
        record_id = (image.id or _uuid.uuid4().hex[:12]).strip()
        filename = (image.filename or "answer.png").strip() or "answer.png"
        mime_type = (image.mime_type or "image/png").strip() or "image/png"
        url = (image.url or "").strip()

        if not url and image.base64:
            try:
                raw_bytes = _b64.b64decode(image.base64, validate=False)
            except Exception as exc:
                logger.warning("answer image %s rejected: invalid base64 (%s)", filename, exc)
                continue
            try:
                url = await attachment_store.put(
                    session_id=owner_id,
                    attachment_id=record_id,
                    filename=filename,
                    data=raw_bytes,
                    mime_type=mime_type,
                )
            except Exception as exc:
                logger.warning("attachment store rejected answer image %s: %s", filename, exc)
                continue

        if not url:
            # No url and no base64 — nothing usable.
            continue
        records.append(
            {
                "id": record_id,
                "url": url,
                "filename": filename,
                "mime_type": mime_type,
            }
        )
    return records


@router.post("/entries/upsert")
async def upsert_single_entry(payload: UpsertEntryRequest):
    store = get_sqlite_session_store()
    existing = await store.find_notebook_entry_by_origin(
        payload.origin_type,
        payload.origin_ref,
        payload.question_id,
        turn_id=payload.turn_id,
    )
    owner_id = _answer_image_owner(
        payload.session_id,
        payload.origin_type,
        payload.origin_ref,
    )
    images_records = await _persist_answer_images(owner_id, payload.user_answer_images)
    item = payload.model_dump()
    # The store expects ``user_answer_images`` as a plain list of dicts
    # (or absent to mean "leave the stored images alone"). Strip the
    # upload payload version and replace with the persisted records.
    item.pop("user_answer_images", None)
    if images_records is not None:
        item["user_answer_images"] = images_records
    try:
        await store.upsert_notebook_entries(payload.session_id or None, [item])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    entry = await store.find_notebook_entry_by_origin(
        payload.origin_type,
        payload.origin_ref,
        payload.question_id,
        turn_id=payload.turn_id,
    )
    if entry is None:
        raise HTTPException(status_code=500, detail="Upsert failed")
    if images_records is not None and existing is not None:
        retained = {str(image.get("id") or "") for image in images_records}
        old_owner = _answer_image_owner(
            str(existing.get("session_id") or ""),
            str(existing.get("origin_type") or "conversation"),
            str(existing.get("origin_ref") or ""),
        )
        attachment_store = get_attachment_store()
        for image in existing.get("user_answer_images") or []:
            image_id = str(image.get("id") or "")
            if image_id and image_id not in retained:
                await attachment_store.delete_attachment(old_owner, image_id)
    return entry


async def _course_session_ids(store: Any, course_id: str) -> list[str] | None:
    """Resolve a course to the sessions whose questions belong to it.

    Course membership remains conversation-derived until Question Bank entries
    gain an explicit course association. Independent origins are intentionally
    excluded. Returns ``None`` for no course (do not scope) and ``[]`` for a
    course with no conversations yet — which must scope to nothing rather than
    quietly fall back to the whole library.
    """
    if not course_id:
        return None
    from deeptutor.services.courses import CourseNotFoundError, get_course_service
    from deeptutor.services.session.organization import list_all_sessions_snapshot

    try:
        get_course_service().get(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc

    sessions = await list_all_sessions_snapshot(store)
    return [
        session["session_id"]
        for session in sessions
        if str((session.get("preferences") or {}).get("course_id") or "") == course_id
    ]


@router.get("/entries", response_model=NotebookEntryListResponse)
async def list_entries(
    category_id: int | None = Query(default=None),
    mistakes_only: bool = Query(default=False),
    uncategorized: bool = Query(
        default=False,
        description="Only entries filed under no category — the triage inbox. "
        "Ignored when category_id is set.",
    ),
    bookmarked: bool | None = Query(default=None),
    is_correct: bool | None = Query(default=None),
    course_id: str = Query(default=""),
    source: AssessmentSource | Literal[""] = Query(default=""),
    material_id: str = Query(default="", max_length=500),
    section_id: str = Query(default="", max_length=500),
    assessment_type: str = Query(default="", pattern="^(quiz|focus_check|qualitative|review)?$"),
    result: str = Query(default="", pattern="^(correct|incorrect|partial|ungraded)?$"),
    mastery_path_id: str = Query(default="", max_length=500),
    knowledge_point_id: str = Query(default="", max_length=500),
    resolved: bool | None = Query(default=None),
    score_trend: str = Query(default="", pattern="^(new|improved|declined|unchanged)?$"),
    search: str = Query(default="", max_length=200),
    sort: str = Query(default="recent", pattern="^(recent|oldest)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> NotebookEntryListResponse:
    store = get_sqlite_session_store()
    session_ids = await _course_session_ids(store, course_id)
    listing = await store.list_notebook_entries(
        category_id=category_id,
        mistakes_only=mistakes_only,
        uncategorized=uncategorized,
        bookmarked=bookmarked,
        is_correct=is_correct,
        session_ids=session_ids,
        source=source,
        material_id=material_id,
        section_id=section_id,
        assessment_type=assessment_type,
        result=result,
        mastery_path_id=mastery_path_id,
        knowledge_point_id=knowledge_point_id,
        resolved=resolved,
        score_trend=score_trend,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return NotebookEntryListResponse(
        items=[NotebookEntryItem(**item) for item in listing["items"]],
        total=listing["total"],
    )


@router.get("/entries/lookup/by-question")
async def lookup_entry(
    session_id: str = Query(default=""),
    origin_type: QuestionOriginType = Query(default="conversation"),
    origin_ref: str = Query(default=""),
    question_id: str = Query(...),
    turn_id: str | None = Query(default=None),
    missing_ok: bool = Query(
        default=False,
        description="Return 204 No Content instead of 404 when the entry is "
        "absent — used by the quiz viewer to probe not-yet-saved questions "
        "without logging noisy 404s.",
    ),
):
    store = get_sqlite_session_store()
    resolved_ref = origin_ref.strip() or session_id.strip()
    if not resolved_ref:
        raise HTTPException(status_code=400, detail="session_id or origin_ref is required")
    if origin_type == "conversation" and session_id.strip() and resolved_ref != session_id.strip():
        raise HTTPException(
            status_code=400,
            detail="conversation origin_ref must match session_id",
        )
    entry = await store.find_notebook_entry_by_origin(
        origin_type,
        resolved_ref,
        question_id,
        turn_id=turn_id,
    )
    if entry is None:
        if missing_ok:
            return Response(status_code=204)
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.get("/entries/{entry_id}", response_model=NotebookEntryItem)
async def get_entry(entry_id: int) -> NotebookEntryItem:
    store = get_sqlite_session_store()
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return NotebookEntryItem(**entry)


@router.patch("/entries/{entry_id}")
async def update_entry(entry_id: int, payload: EntryUpdateRequest):
    store = get_sqlite_session_store()
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await store.update_notebook_entry(entry_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"updated": True, "id": entry_id}


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int):
    store = get_sqlite_session_store()
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    deleted = await store.delete_notebook_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")
    owner_id = _answer_image_owner(
        str(entry.get("session_id") or ""),
        str(entry.get("origin_type") or "conversation"),
        str(entry.get("origin_ref") or ""),
    )
    attachment_store = get_attachment_store()
    for image in entry.get("user_answer_images") or []:
        image_id = str(image.get("id") or "")
        if image_id:
            await attachment_store.delete_attachment(owner_id, image_id)
    return {"deleted": True, "id": entry_id}


# ── Entry ↔ Category linking ────────────────────────────────────


@router.post("/entries/categories/bulk")
async def bulk_link_entries(payload: BulkCategoryRequest):
    store = get_sqlite_session_store()
    changed = await store.link_entries_to_category(
        payload.entry_ids, payload.category_id, link=payload.link
    )
    return {
        "changed": changed,
        "requested": len(payload.entry_ids),
        "category_id": payload.category_id,
        "link": payload.link,
    }


@router.post("/entries/{entry_id}/categories")
async def add_entry_to_category(entry_id: int, payload: CategoryAddRequest):
    store = get_sqlite_session_store()
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    ok = await store.add_entry_to_category(entry_id, payload.category_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to add to category")
    return {"added": True, "entry_id": entry_id, "category_id": payload.category_id}


@router.delete("/entries/{entry_id}/categories/{category_id}")
async def remove_entry_from_category(entry_id: int, category_id: int):
    store = get_sqlite_session_store()
    removed = await store.remove_entry_from_category(entry_id, category_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"removed": True, "entry_id": entry_id, "category_id": category_id}


# ── Overview ─────────────────────────────────────────────────────


@router.get("/stats", response_model=QuestionBankStats)
async def question_bank_stats(
    course_id: str = Query(default=""),
) -> QuestionBankStats:
    """Counts behind the filter chips; also the agent's one-call overview.

    Takes the same course scope as the listing: showing one course's questions
    next to whole-library counts would make the rail lie about how much is there.
    """
    store = get_sqlite_session_store()
    session_ids = await _course_session_ids(store, course_id)
    return QuestionBankStats(**await store.question_bank_stats(session_ids))


@router.get("/materials", response_model=list[QuestionBankMaterial])
async def list_question_bank_materials(
    course_id: str = Query(default=""),
) -> list[QuestionBankMaterial]:
    """Materials represented in the unified review history."""
    store = get_sqlite_session_store()
    session_ids = await _course_session_ids(store, course_id)
    return [
        QuestionBankMaterial(**item)
        for item in await store.list_question_bank_materials(session_ids)
    ]


# ── Category CRUD ────────────────────────────────────────────────


@router.get("/categories", response_model=list[CategoryItem])
async def list_categories(course_id: str = Query(default="")):
    """Categories, with their counts scoped the same way the listing is.

    Without the scope the rail would offer "Address translation 3" inside a
    course holding none of those three.
    """
    store = get_sqlite_session_store()
    session_ids = await _course_session_ids(store, course_id)
    return await store.list_categories(session_ids)


@router.post("/categories", response_model=CategoryItem, status_code=201)
async def create_category(payload: CategoryCreateRequest):
    store = get_sqlite_session_store()
    try:
        return await store.create_category(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.patch("/categories/{category_id}")
async def rename_category(category_id: int, payload: CategoryRenameRequest):
    store = get_sqlite_session_store()
    try:
        updated = await store.rename_category(category_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"updated": True, "id": category_id, "name": payload.name}


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int):
    store = get_sqlite_session_store()
    deleted = await store.delete_category(category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"deleted": True, "id": category_id}
