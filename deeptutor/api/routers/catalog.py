"""Academic catalog and source-rights API.

Two audiences, two routers
--------------------------
``router`` — mounted at ``/api/catalog`` with the ``learning`` policy.
    Read-only lookup for an authenticated learner: grades, majors and the
    subjects available at a grade. It deliberately exposes **no** source
    listings: what a learner may be shown is decided by retrieval scope
    (Phase 5), not by a browsing endpoint.

``admin_router`` — mounted at ``/api/catalog/admin`` with the ``admin`` policy.
    The review workflow: create sources, inspect duplicates, approve/reject/
    archive, and read the audit trail. Everything that changes what may be
    published lives here.

Why the read side is ``learning`` and not ``public``
---------------------------------------------------
The catalog itself is not secret, but it is scoped data: a grade/major list
rendered to an anonymous caller would let anyone enumerate the curriculum and,
more importantly, would establish a pattern where catalog reads need not be
authenticated. The learner endpoints are cheap to authenticate; keeping them
behind ``learning`` costs nothing and removes a class of accidental leaks.

Error mapping
-------------
The repositories raise typed errors (:class:`CatalogError`,
:class:`RightsError`, ``*NotFound``). They are translated here into 404/409/422
with the field name preserved, so a client can highlight the offending input
instead of showing a generic failure. An unexpected ``DatabaseError`` becomes
503 -- a database problem is not the caller's fault.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.db.repositories import catalog as catalog_repo
from deeptutor.db.repositories import sources as sources_repo

logger = logging.getLogger(__name__)

#: Learner-facing lookups. Mounted at ``/api/catalog`` with the ``learning``
#: policy: an authenticated user, no admin rights required.
router = APIRouter()

#: Review workflow. Mounted at ``/api/catalog/admin`` with the ``admin`` policy.
admin_router = APIRouter()


def _database() -> Any:
    """Open the database for one request, or fail with a clear 503.

    Opened per request rather than kept module-level: a module-level handle
    would survive a reconnect and hold a stale connection, and the pool already
    makes per-request acquisition cheap.

    The settings are imported *inside* the function rather than at module
    scope. A module-level ``from ... import get_database_settings`` binds the
    function object at import time, which makes the settings impossible to
    redirect in a test -- the call keeps reaching the original. Importing here
    keeps the lookup late, which is also what ``platform_health`` does.
    """
    from deeptutor.db.config import get_database_settings

    settings = get_database_settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=503,
            detail="database is not configured; set DEEPTUTOR_DATABASE_URL",
        )
    database = open_database(settings)
    if database is None:  # pragma: no cover - enabled implies a database
        raise HTTPException(status_code=503, detail="database is unavailable")
    return database


def _translate(exc: Exception) -> HTTPException:
    """Map a repository error onto the closest HTTP status.

    Kept as one function so every endpoint reports the same way. The field name
    is carried through because the client uses it to mark the offending input.
    """
    if isinstance(exc, (catalog_repo.CatalogNotFound, sources_repo.SourceNotFound)):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, sources_repo.RightsTransitionError):
        # A workflow violation is a conflict with current state, not bad input.
        return HTTPException(
            status_code=409,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, (catalog_repo.CatalogError, sources_repo.RightsError)):
        return HTTPException(
            status_code=422,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, DatabaseError):
        logger.warning("catalog database error: %s", type(exc).__name__)
        return HTTPException(status_code=503, detail="database unavailable")
    logger.exception("unexpected catalog error")
    return HTTPException(status_code=500, detail="internal error")


# ---------------------------------------------------------------------------
# Learner-facing read models
# ---------------------------------------------------------------------------


class EnrolmentResponse(BaseModel):
    system_code: str
    grade_number: int
    stage_code: str
    major_code: str | None = None
    track_code: str | None = None


@router.get("/grades")
async def get_grades(system: str = Query("current")) -> dict:
    """Grades of a system. ``system=current`` is the default; archives are opt-in."""
    database = _database()
    try:
        return {"system": system, "grades": catalog_repo.list_grades(database, system)}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/majors")
async def get_majors(
    track: str | None = Query(None),
    grade_number: int | None = Query(None, ge=1, le=20),
) -> dict:
    """Tracks and majors, optionally narrowed to those selectable at a grade."""
    database = _database()
    try:
        return {
            "majors": catalog_repo.list_majors(
                database, track_code=track, grade_number=grade_number
            )
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/subjects")
async def get_subjects(
    grade_number: int = Query(..., ge=1, le=20),
    major: str | None = Query(None),
    system: str = Query("current"),
) -> dict:
    """Subjects at a grade, narrowed to a major when one is given.

    A subject scoped to no major is included for every major; a subject scoped
    to another major is excluded. That boundary is what Phase 5 retrieval
    relies on to prevent track leakage.
    """
    database = _database()
    try:
        return {
            "grade_number": grade_number,
            "major_code": major,
            "subjects": catalog_repo.list_grade_subjects(
                database, grade_number=grade_number, major_code=major, system_code=system
            ),
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/enrolment", response_model=EnrolmentResponse)
async def get_enrolment(
    grade_number: int = Query(..., ge=1, le=20),
    major: str | None = Query(None),
    system: str = Query("current"),
) -> EnrolmentResponse:
    """Resolve a grade/major combination, or explain why it is invalid.

    This is the endpoint a profile form calls before saving, so an invalid
    combination is caught with a field-level message rather than a generic
    "could not save".
    """
    database = _database()
    try:
        resolved = catalog_repo.resolve_enrolment(
            database, grade_number=grade_number, major_code=major, system_code=system
        )
        return EnrolmentResponse(**resolved)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Admin: catalog maintenance
# ---------------------------------------------------------------------------


class SystemCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=60)
    title: str = Field(..., min_length=1, max_length=200)
    status: str = Field("current")
    effective_from_year: int | None = None
    effective_to_year: int | None = None
    sort_order: int = 0


class GradeCreate(BaseModel):
    system_code: str = Field(..., min_length=1, max_length=60)
    grade_number: int = Field(..., ge=1, le=20)
    title: str = Field(..., min_length=1, max_length=200)
    stage_code: str = Field(..., min_length=1, max_length=40)
    requires_track: bool = False


class TrackCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=60)
    title: str = Field(..., min_length=1, max_length=200)
    kind: str = Field("theoretical")
    sort_order: int = 0


class MajorCreate(BaseModel):
    track_code: str = Field(..., min_length=1, max_length=60)
    code: str = Field(..., min_length=1, max_length=60)
    title: str = Field(..., min_length=1, max_length=200)
    selectable_grades: list[int] = Field(default_factory=list)
    sort_order: int = 0


class SubjectCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=200)
    grade_number: int = Field(..., ge=1, le=20)
    major_code: str | None = None
    curriculum_version_id: str | None = None
    language: str = Field("fa", min_length=2, max_length=10)
    requirement: str = Field("mandatory")
    weekly_hours: int | None = Field(None, ge=0, le=60)
    sort_order: int = 0


class VersionCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    school_year: str = Field(..., min_length=1, max_length=20)
    status: str = Field("draft")


@admin_router.post("/systems", status_code=201)
async def create_system(payload: SystemCreate) -> dict:
    database = _database()
    try:
        identifier = catalog_repo.create_system(
            database,
            code=payload.code,
            title=payload.title,
            status=payload.status,
            effective_from_year=payload.effective_from_year,
            effective_to_year=payload.effective_to_year,
            sort_order=payload.sort_order,
        )
        return {"id": identifier}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/systems")
async def list_systems(status: str | None = Query(None)) -> dict:
    database = _database()
    try:
        return {"systems": catalog_repo.list_systems(database, status=status)}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/grades", status_code=201)
async def create_grade(payload: GradeCreate) -> dict:
    database = _database()
    try:
        identifier = catalog_repo.add_grade(
            database,
            system_code=payload.system_code,
            grade_number=payload.grade_number,
            title=payload.title,
            stage_code=payload.stage_code,
            requires_track=payload.requires_track,
        )
        return {"id": identifier}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/tracks", status_code=201)
async def create_track(payload: TrackCreate) -> dict:
    database = _database()
    try:
        identifier = catalog_repo.create_track(
            database,
            code=payload.code,
            title=payload.title,
            kind=payload.kind,
            sort_order=payload.sort_order,
        )
        return {"id": identifier}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/majors", status_code=201)
async def create_major(payload: MajorCreate) -> dict:
    database = _database()
    try:
        identifier = catalog_repo.create_major(
            database,
            track_code=payload.track_code,
            code=payload.code,
            title=payload.title,
            selectable_grades=tuple(payload.selectable_grades),
            sort_order=payload.sort_order,
        )
        return {"id": identifier}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/subjects", status_code=201)
async def create_subject(payload: SubjectCreate) -> dict:
    database = _database()
    try:
        identifier = catalog_repo.create_subject(
            database,
            code=payload.code,
            title=payload.title,
            grade_number=payload.grade_number,
            major_code=payload.major_code,
            curriculum_version_id=payload.curriculum_version_id,
            language=payload.language,
            requirement=payload.requirement,
            weekly_hours=payload.weekly_hours,
            sort_order=payload.sort_order,
        )
        return {"id": identifier}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/versions", status_code=201)
async def create_version(payload: VersionCreate) -> dict:
    database = _database()
    try:
        identifier = catalog_repo.create_version(
            database,
            label=payload.label,
            school_year=payload.school_year,
            status=payload.status,
        )
        return {"id": identifier}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Admin: sources and rights
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=400)
    source_type: str = Field(..., min_length=1, max_length=40)
    grade_number: int | None = Field(None, ge=1, le=20)
    major_code: str | None = None
    subject_code: str | None = None
    edition: str | None = Field(None, max_length=100)
    content_checksum: str | None = Field(None, max_length=128)
    page_count: int | None = Field(None, ge=0)
    provenance_kind: str = Field("unknown", max_length=60)
    provenance_note: str = Field("", max_length=2000)
    rights_status: str = Field("unknown", max_length=40)
    review_status: str = Field("draft", max_length=40)
    supersedes_id: str | None = None


class ReviewRequest(BaseModel):
    decision: str = Field(..., min_length=1, max_length=20)
    reviewer: str = Field(..., min_length=1, max_length=200)
    reason: str = Field("", max_length=2000)
    rights_status: str | None = Field(None, max_length=40)


@admin_router.post("/sources", status_code=201)
async def create_source(payload: SourceCreate) -> dict:
    """Register a source. It is not retrievable until rights and review allow it."""
    database = _database()
    try:
        identifier = sources_repo.create_source(
            database,
            title=payload.title,
            source_type=payload.source_type,
            grade_number=payload.grade_number,
            major_code=payload.major_code,
            subject_code=payload.subject_code,
            edition=payload.edition,
            content_checksum=payload.content_checksum,
            page_count=payload.page_count,
            provenance_kind=payload.provenance_kind,
            provenance_note=payload.provenance_note,
            rights_status=payload.rights_status,
            review_status=payload.review_status,
            supersedes_id=payload.supersedes_id,
        )
        return {"id": identifier, "source": sources_repo.get_source(database, identifier)}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/sources")
async def list_sources(
    grade_number: int | None = Query(None, ge=1, le=20),
    major_code: str | None = Query(None),
    rights_status: str | None = Query(None),
    review_status: str | None = Query(None),
) -> dict:
    """Every source with its review state, including non-retrievable ones.

    Admin-only because it shows unreviewed and rejected material. The learner
    side has no equivalent, by design.
    """
    database = _database()
    try:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if grade_number is not None:
            clauses.append("grade_number = ?")
            params.append(grade_number)
        if major_code is not None:
            clauses.append("major_code = ?")
            params.append(major_code)
        if rights_status is not None:
            clauses.append("rights_status = ?")
            params.append(rights_status)
        if review_status is not None:
            clauses.append("review_status = ?")
            params.append(review_status)
        with database.read() as conn:
            rows = [
                dict(row)
                for row in conn.query(
                    "SELECT * FROM catalog_sources WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC",
                    tuple(params),
                )
            ]
        return {"sources": rows}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/sources/duplicates")
async def find_duplicates(
    title: str = Query(..., min_length=1),
    source_type: str = Query(...),
    grade_number: int | None = Query(None),
    major_code: str | None = Query(None),
    subject_code: str | None = Query(None),
    edition: str | None = Query(None),
) -> dict:
    """Check for an existing source before importing, so an import can report.

    Advisory only: the unique index is the authority, because this check races
    with a concurrent import and the index does not.
    """
    database = _database()
    try:
        return {
            "duplicates": sources_repo.find_duplicates(
                database,
                title=title,
                source_type=source_type,
                grade_number=grade_number,
                major_code=major_code,
                subject_code=subject_code,
                edition=edition,
            )
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/sources/{source_id}")
async def get_source(source_id: str) -> dict:
    database = _database()
    try:
        return {
            "source": sources_repo.get_source(database, source_id),
            "reviews": sources_repo.review_history(database, source_id),
            "versions": sources_repo.version_history(database, source_id),
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/sources/{source_id}/review")
async def review_source(source_id: str, payload: ReviewRequest) -> dict:
    """Apply a rights decision and record it in the append-only audit log.

    A 409 means the decision is not legal from the source's current state --
    for example approving something that is already approved, or restoring
    something that was never archived.
    """
    database = _database()
    try:
        updated = sources_repo.review_source(
            database,
            source_id=source_id,
            decision=payload.decision,
            reviewer=payload.reviewer,
            reason=payload.reason,
            rights_status=payload.rights_status,
        )
        return {
            "source": updated,
            "history": sources_repo.review_history(database, source_id),
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/sources/{source_id}/history")
async def source_history(source_id: str) -> dict:
    database = _database()
    try:
        sources_repo.get_source(database, source_id)  # 404 when unknown
        return {
            "reviews": sources_repo.review_history(database, source_id),
            "versions": sources_repo.version_history(database, source_id),
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()
