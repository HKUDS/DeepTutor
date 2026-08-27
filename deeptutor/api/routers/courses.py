"""Study-course CRUD and session organization endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.services.courses import (
    COURSE_COLORS,
    CourseNameConflictError,
    CourseNotFoundError,
    get_course_service,
)
from deeptutor.services.session import get_session_store
from deeptutor.services.session.organization import list_all_sessions_snapshot

router = APIRouter()


class CreateCourseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    color: str = ""


class UpdateCourseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    color: str | None = None


@router.get("")
async def list_courses() -> dict[str, object]:
    return {
        "courses": [course.to_dict() for course in get_course_service().list_courses()],
        "colors": list(COURSE_COLORS),
    }


@router.post("")
async def create_course(payload: CreateCourseRequest) -> dict[str, object]:
    try:
        course = get_course_service().create(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CourseNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"course": course.to_dict()}


@router.patch("/{course_id}")
async def update_course(course_id: str, payload: UpdateCourseRequest) -> dict[str, object]:
    try:
        course = get_course_service().update(
            course_id,
            **payload.model_dump(exclude_unset=True),
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CourseNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"course": course.to_dict()}


@router.delete("/{course_id}")
async def delete_course(course_id: str) -> dict[str, object]:
    service = get_course_service()
    try:
        service.get(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc

    # Course deletion is non-destructive: conversations become unclassified.
    store = get_session_store()
    sessions = await list_all_sessions_snapshot(store)
    for session in sessions:
        preferences = session.get("preferences") or {}
        if str(preferences.get("course_id") or "") == course_id:
            await store.update_session_preferences(session["session_id"], {"course_id": ""})
    service.delete(course_id)
    return {"deleted": True, "course_id": course_id}
