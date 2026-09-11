"""Study-course CRUD and session organization endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.services.courses import (
    COURSE_COLORS,
    CourseNameConflictError,
    CourseNotFoundError,
    CourseResourceNotFoundError,
    UnknownResourceKindError,
    get_course_service,
)
from deeptutor.services.courses_state import (
    build_course_resource_candidates,
    build_course_state,
)
from deeptutor.services.session import get_session_store
from deeptutor.services.session.organization import list_all_sessions_snapshot

router = APIRouter()


class CreateCourseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field(default="", max_length=300)
    color: str = ""
    instructions: str = Field(default="", max_length=4000)
    # A course declares the mode and persona its conversations open in. Settable
    # at creation as well as on edit, so a course made for one way of studying
    # does not have to be created and then immediately reopened to say so.
    default_capability: str = Field(default="", max_length=64)
    default_persona: str = Field(default="", max_length=80)


class UpdateCourseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    color: str | None = None
    instructions: str | None = Field(default=None, max_length=4000)
    default_capability: str | None = None
    default_persona: str | None = None
    status: str | None = None


class SyllabusUnitRequest(BaseModel):
    id: str | None = None
    title: str
    topics: list[str] = Field(default_factory=list)
    covered: bool = False


class SetSyllabusRequest(BaseModel):
    units: list[SyllabusUnitRequest]


class UpdateSyllabusUnitRequest(BaseModel):
    covered: bool


class AttachCourseResourceRequest(BaseModel):
    kind: str
    ref_id: str
    label: str = ""


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


# Literal routes must remain above every /{course_id} route. FastAPI matches
# paths in declaration order, so otherwise "resource-candidates" can become a
# course id before this handler gets a chance to run.
@router.get("/resource-candidates")
async def list_resource_candidates() -> dict[str, object]:
    return {"candidates": await build_course_resource_candidates()}


@router.patch("/{course_id}")
async def update_course(course_id: str, payload: UpdateCourseRequest) -> dict[str, object]:
    from deeptutor.services.courses import COURSE_STATUSES

    changes = payload.model_dump(exclude_unset=True)
    status = changes.pop("status", None)
    try:
        if status is not None:
            status = status.strip()
            if status not in COURSE_STATUSES:
                raise ValueError(f"Unknown course status {status!r}; expected active or archived.")
        service = get_course_service()
        if changes or status is None:
            course = service.update(course_id, **changes)
        else:
            course = service.get(course_id)
        if status is not None:
            course = service.set_status(course_id, status)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CourseNameConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"course": course.to_dict()}


@router.put("/{course_id}/syllabus")
async def set_course_syllabus(
    course_id: str,
    payload: SetSyllabusRequest,
) -> dict[str, object]:
    service = get_course_service()
    try:
        course = service.get(course_id)
        covered_by_id = {unit.id: unit.covered for unit in course.syllabus}
        units = []
        for request_unit in payload.units:
            unit = request_unit.model_dump(exclude_unset=True)
            unit_id = str(unit.get("id") or "").strip()
            if unit_id in covered_by_id:
                unit["covered"] = covered_by_id[unit_id]
            units.append(unit)
        course = service.set_syllabus(course_id, units)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    return {"course": course.to_dict()}


@router.patch("/{course_id}/syllabus/{unit_id}")
async def update_syllabus_unit(
    course_id: str,
    unit_id: str,
    payload: UpdateSyllabusUnitRequest,
) -> dict[str, object]:
    from deeptutor.services.courses import SyllabusUnitNotFoundError

    try:
        unit = get_course_service().set_unit_covered(course_id, unit_id, payload.covered)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    except SyllabusUnitNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Syllabus unit not found") from exc
    return {"unit": unit.to_dict()}


@router.post("/{course_id}/resources")
async def attach_course_resource(
    course_id: str,
    payload: AttachCourseResourceRequest,
) -> dict[str, object]:
    try:
        resource = get_course_service().attach_resource(course_id, **payload.model_dump())
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    except UnknownResourceKindError as exc:
        raise HTTPException(status_code=400, detail="Unknown resource kind") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"resource": resource.to_dict()}


@router.delete("/{course_id}/resources/{resource_id}")
async def detach_course_resource(course_id: str, resource_id: str) -> dict[str, object]:
    try:
        get_course_service().detach_resource(course_id, resource_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc
    except CourseResourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course resource not found") from exc
    return {"deleted": True}


@router.get("/{course_id}/state")
async def get_course_state(course_id: str) -> dict[str, object]:
    try:
        return await build_course_state(course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Course not found") from exc


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
