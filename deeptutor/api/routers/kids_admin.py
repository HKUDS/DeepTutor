"""Parent management endpoints for kids profiles, book assignments, and reports.

All endpoints require adult authentication (require_auth).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.immersive_reading import get_immersive_reading_service
from deeptutor.immersive_reading.service import get_kids_manager

router = APIRouter()
logger = logging.getLogger(__name__)


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
    birth_date: str = Field(default="", pattern=r"^\d{4}-\d{2}-\d{2}$")
    help_language: Literal["en", "zh"] = "en"
    narration_rate: float = 0.8
    daily_limit_minutes: int = 30
    parent_pin: str = Field(default="", max_length=20)


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    avatar: str | None = None
    birth_date: str | None = None
    help_language: Literal["en", "zh"] | None = None
    narration_rate: float | None = None
    daily_limit_minutes: int | None = None
    parent_pin: str | None = None


@router.get("/profiles")
async def list_profiles() -> dict:
    manager = get_kids_manager()
    profiles = manager.list_profiles()
    return {
        "profiles": [
            _profile_dict(p)
            for p in profiles
        ]
    }


@router.post("/profiles")
async def create_profile(request: CreateProfileRequest) -> dict:
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


# ── Book assignments ────────────────────────────────────────────────────────

class AssignBookRequest(BaseModel):
    document_id: str
    available_through_section_id: str = ""
    available_through_section_index: int = 999


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
    assignment = manager.assign_book(
        profile_id,
        request.document_id,
        available_through_section_id=request.available_through_section_id,
        available_through_section_index=request.available_through_section_index,
    )
    return {"assignment": assignment.model_dump(mode="json")}


@router.put("/profiles/{profile_id}/books/{document_id}")
async def update_assignment(profile_id: str, document_id: str, request: UpdateAssignmentRequest) -> dict:
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


# ── Adult library (for parent to browse and pick books) ─────────────────────

@router.get("/library")
async def adult_library() -> dict:
    """List all imported documents that the parent can assign to children."""
    ir = get_immersive_reading_service()
    documents = ir.list_documents()
    manager = get_kids_manager()
    assignments = manager.list_assignments()
    # Annotate each document with which profiles it's assigned to
    for doc in documents:
        doc["assigned_profile_ids"] = [
            a.profile_id for a in assignments
            if a.document_id == doc["id"]
        ]
    return {"documents": documents}


# ── Learning reports ────────────────────────────────────────────────────────

@router.get("/profiles/{profile_id}/report")
async def learning_report(profile_id: str) -> dict:
    manager = get_kids_manager()
    try:
        return manager.get_report(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
