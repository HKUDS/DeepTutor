"""Parent management endpoints for kids profiles, book assignments, family kids library, and device pairing.

All endpoints require adult authentication (require_auth).
"""

from __future__ import annotations

from datetime import date
import logging
import re
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.service import MAX_UPLOAD_BYTES, get_kids_manager

router = APIRouter()
logger = logging.getLogger(__name__)


def _normalize_birth_date(v: object) -> str:
    if not v:
        return ""
    val = str(v).strip()
    if not val:
        return ""
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$", val)
    if m:
        y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}"
    try:
        return date.fromisoformat(val).isoformat()
    except Exception:
        raise ValueError(f"Invalid birth_date format: {val}. Expected YYYY-MM-DD")


def _profile_dict(profile) -> dict:
    """Serialize profile with computed age and age_band included."""
    return {
        **profile.model_dump(mode="json"),
        "age": profile.age,
        "age_band": profile.age_band,
        "has_pin": bool(profile.pin_hash),
        "device_url": f"/kids/p/{profile.id}",
    }


# ── Profile CRUD ────────────────────────────────────────────────────────────


class CreateProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    avatar: str = "default"
    birth_date: str = ""
    help_language: Literal["en", "zh"] = "en"
    narration_rate: float = 0.8
    daily_limit_minutes: int = 30
    parent_pin: str = Field(default="", max_length=20)

    @field_validator("birth_date", mode="before")
    @classmethod
    def validate_birth_date(cls, v: object) -> str:
        return _normalize_birth_date(v)


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    avatar: str | None = None
    birth_date: str | None = None
    help_language: Literal["en", "zh"] | None = None
    narration_rate: float | None = None
    daily_limit_minutes: int | None = None
    parent_pin: str | None = None

    @field_validator("birth_date", mode="before")
    @classmethod
    def validate_birth_date(cls, v: object) -> str | None:
        if v is None:
            return None
        return _normalize_birth_date(v)


@router.get("/profiles")
async def list_profiles() -> dict:
    manager = get_kids_manager()
    profiles = manager.list_profiles()
    return {"profiles": [_profile_dict(p) for p in profiles]}


@router.post("/profiles")
async def create_profile(request: CreateProfileRequest) -> dict:
    if request.parent_pin and len(request.parent_pin) < 4:
        raise HTTPException(status_code=422, detail="Parent PIN must contain at least 4 characters")
    manager = get_kids_manager()
    profile = manager.create_profile(
        request.name,
        avatar=request.avatar,
        birth_date=request.birth_date,
        help_language=request.help_language,
        narration_rate=request.narration_rate,
        daily_limit_minutes=request.daily_limit_minutes,
        parent_pin=request.parent_pin,
    )
    return {"profile": _profile_dict(profile)}


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: str, request: UpdateProfileRequest) -> dict:
    if request.parent_pin and len(request.parent_pin) < 4:
        raise HTTPException(status_code=422, detail="Parent PIN must contain at least 4 characters")
    manager = get_kids_manager()
    try:
        profile = manager.update_profile(profile_id, **request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"profile": _profile_dict(profile)}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict:
    get_kids_manager().delete_profile(profile_id)
    return {"deleted": True, "profile_id": profile_id}


# ── PIN management ──────────────────────────────────────────────────────────


class VerifyPinRequest(BaseModel):
    pin: str = Field(min_length=4, max_length=20)


@router.post("/profiles/{profile_id}/verify-pin")
async def verify_pin(profile_id: str, request: VerifyPinRequest) -> dict:
    ok = get_kids_manager().verify_parent_pin(profile_id, request.pin)
    if not ok:
        raise HTTPException(status_code=403, detail="Invalid PIN or too many attempts")
    return {"verified": True}


@router.post("/profiles/{profile_id}/usage/reset")
async def reset_daily_usage(profile_id: str) -> dict:
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    usage = manager.reset_daily_usage(profile_id)
    return {"usage": {**usage.model_dump(mode="json"), **manager.usage_status(profile_id)}}


class ExtendUsageRequest(BaseModel):
    minutes: int = Field(ge=1, le=120)


@router.post("/profiles/{profile_id}/usage/extend")
async def extend_daily_usage(profile_id: str, request: ExtendUsageRequest) -> dict:
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    manager.extend_daily_usage(profile_id, request.minutes)
    usage = manager.load_daily_usage(profile_id)
    return {"usage": {**usage.model_dump(mode="json"), **manager.usage_status(profile_id)}}


# ── Book assignments ────────────────────────────────────────────────────────


class AssignBookRequest(BaseModel):
    document_id: str
    available_through_section_id: str = ""
    available_through_section_index: int = 999
    content_confirmed: bool = False


class UpdateAssignmentRequest(BaseModel):
    status: Literal["active", "hidden"] | None = None
    sort_order: int | None = None
    is_next_read: bool | None = None
    available_through_section_id: str | None = None
    available_through_section_index: int | None = None


@router.get("/profiles/{profile_id}/books")
async def list_assigned_books(profile_id: str) -> dict:
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"library": manager.get_kids_library(profile_id)}


@router.post("/profiles/{profile_id}/books")
async def assign_book(profile_id: str, request: AssignBookRequest) -> dict:
    manager = get_kids_manager()
    if manager.get_profile(profile_id) is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    ir = get_immersive_reading_service()
    if ir.load_document(request.document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not request.content_confirmed:
        raise HTTPException(status_code=422, detail="A parent must confirm the book is appropriate")
    # Ensure book is in kids_family scope and approved
    ir.add_to_kids_family(request.document_id, status="approved")
    assignment = manager.assign_book(
        profile_id,
        request.document_id,
        available_through_section_id=request.available_through_section_id,
        available_through_section_index=request.available_through_section_index,
        content_confirmed=request.content_confirmed,
    )
    return {"assignment": assignment.model_dump(mode="json")}


@router.put("/profiles/{profile_id}/books/{document_id}")
async def update_assignment(
    profile_id: str, document_id: str, request: UpdateAssignmentRequest
) -> dict:
    manager = get_kids_manager()
    try:
        assignment = manager.update_assignment(
            profile_id, document_id, **request.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"assignment": assignment.model_dump(mode="json")}


@router.delete("/profiles/{profile_id}/books/{document_id}")
async def unassign_book(profile_id: str, document_id: str) -> dict:
    get_kids_manager().unassign_book(profile_id, document_id)
    return {"deleted": True}


# ── Family Kids Library Management ──────────────────────────────────────────


@router.get("/library")
async def family_kids_library() -> dict:
    """List all books in the Family Kids Library (isolated from adult personal bookshelf)."""
    manager = get_kids_manager()
    items = manager.get_family_kids_library()
    # Also provide backwards-compatible documents array for existing clients
    docs = [
        {
            **item["document"],
            "kids_review_status": item["entry"]["kids_review_status"],
            "approved_age_bands": item["entry"]["approved_age_bands"],
            "assigned_profile_ids": [p["id"] for p in item["assigned_profiles"]],
            "assigned_profiles": item["assigned_profiles"],
        }
        for item in items
    ]
    return {"documents": docs, "items": items}


@router.post("/library/import")
async def import_kids_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    auto_approve: bool = False,
    age_bands: str = "6-8",
) -> dict:
    """Import a book directly into the Family Kids Library with initial pending status."""
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        parsed_age_bands = [b.strip() for b in age_bands.split(",") if b.strip()]
        if not parsed_age_bands:
            parsed_age_bands = ["6-8"]
        service = get_immersive_reading_service()
        document = service.import_document(
            file.filename or "kids-book.epub",
            raw,
            scope="kids_family",
            kids_review_status="approved" if auto_approve else "pending",
            approved_age_bands=parsed_age_bands,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Book import failed: {exc}") from exc
    background_tasks.add_task(service.build_fast_index, document["id"])
    return {"document": document}


class ReviewBookRequest(BaseModel):
    status: Literal["pending", "approved", "archived"] = "approved"
    approved_age_bands: list[Literal["3-5", "6-8", "9-12"]] = Field(default_factory=list)
    reviewer_note: str = ""


@router.put("/library/{document_id}/review")
async def review_kids_book(document_id: str, request: ReviewBookRequest) -> dict:
    service = get_immersive_reading_service()
    if service.load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    entry = service.add_to_kids_family(
        document_id,
        status=request.status,
        approved_age_bands=request.approved_age_bands,
        reviewer_note=request.reviewer_note,
    )
    return {"entry": entry.model_dump(mode="json")}


class AssignMultipleProfilesRequest(BaseModel):
    profile_ids: list[str]
    available_through_section_index: int = 999
    content_confirmed: bool = True


@router.post("/library/{document_id}/assign")
async def assign_book_to_children(
    document_id: str, request: AssignMultipleProfilesRequest
) -> dict:
    service = get_immersive_reading_service()
    if service.load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not request.content_confirmed:
        raise HTTPException(status_code=422, detail="A parent must confirm the book is appropriate")
    # Approve in kids family library
    service.add_to_kids_family(document_id, status="approved")
    manager = get_kids_manager()
    assignments = []
    for pid in request.profile_ids:
        if manager.get_profile(pid):
            a = manager.assign_book(
                pid,
                document_id,
                available_through_section_index=request.available_through_section_index,
                content_confirmed=True,
            )
            assignments.append(a.model_dump(mode="json"))
    return {"assignments": assignments, "assigned_profile_ids": request.profile_ids}


class SharePersonalRequest(BaseModel):
    auto_approve: bool = False
    approved_age_bands: list[Literal["3-5", "6-8", "9-12"]] = Field(default_factory=list)
    reviewer_note: str = ""


@router.post("/library/from-personal/{document_id}")
async def share_from_personal_bookshelf(
    document_id: str, request: SharePersonalRequest | None = None
) -> dict:
    service = get_immersive_reading_service()
    if service.load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    req = request or SharePersonalRequest()
    status = "approved" if req.auto_approve else "pending"
    entry = service.add_to_kids_family(
        document_id,
        status=status,
        approved_age_bands=req.approved_age_bands,
        reviewer_note=req.reviewer_note,
    )
    return {"entry": entry.model_dump(mode="json")}


@router.post("/library/{document_id}/add-to-personal")
async def share_to_personal_bookshelf(document_id: str) -> dict:
    service = get_immersive_reading_service()
    if service.load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    entry = service.add_to_personal(document_id)
    return {"entry": entry.model_dump(mode="json")}


@router.post("/library/{document_id}/archive")
async def archive_kids_book(document_id: str) -> dict:
    service = get_immersive_reading_service()
    if service.load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    entry = service.archive_from_kids_family(document_id)
    return {"entry": entry.model_dump(mode="json")}


@router.post("/library/{document_id}/unarchive")
async def unarchive_kids_book(document_id: str) -> dict:
    service = get_immersive_reading_service()
    if service.load_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    entry = service.unarchive_to_kids_family(document_id)
    return {"entry": entry.model_dump(mode="json")}


class PurgeBookRequest(BaseModel):
    confirm_title: str = ""


@router.post("/library/{document_id}/purge")
async def purge_kids_book(document_id: str, request: PurgeBookRequest | None = None) -> dict:
    service = get_immersive_reading_service()
    doc = service.load_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if request and request.confirm_title and request.confirm_title.strip() != doc.title.strip():
        raise HTTPException(
            status_code=400, detail="Book title confirmation does not match"
        )
    result = service.purge_kids_document(document_id)
    return result


@router.get("/library/personal-candidates")
async def list_personal_candidates() -> dict:
    """List personal bookshelf documents that can be shared to the kids library."""
    service = get_immersive_reading_service()
    personal_docs = service.list_documents(scope="personal")
    index = service.get_library_index()
    candidates = [
        doc
        for doc in personal_docs
        if "kids_family" not in (index.entries.get(doc["id"]).scopes if doc["id"] in index.entries else ["personal"])
    ]
    return {"candidates": candidates}


# ── Device Pairing Management ───────────────────────────────────────────────


class PairDeviceRequest(BaseModel):
    profile_id: str
    ttl_seconds: int = 600


@router.post("/devices/pair")
async def create_device_pairing(request: PairDeviceRequest) -> dict:
    manager = get_kids_manager()
    try:
        pairing = manager.create_pairing_code(request.profile_id, ttl_seconds=request.ttl_seconds)
        return {"pairing": pairing}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/devices")
async def list_device_sessions() -> dict:
    manager = get_kids_manager()
    return {"devices": manager.list_device_sessions_for_admin()}


@router.delete("/devices/{session_id}")
async def revoke_device_session(session_id: str) -> dict:
    manager = get_kids_manager()
    ok = manager.revoke_device_session_by_id(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"revoked": True}


# ── Learning reports ────────────────────────────────────────────────────────


@router.get("/profiles/{profile_id}/report")
async def learning_report(profile_id: str) -> dict:
    manager = get_kids_manager()
    try:
        return manager.get_report(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
