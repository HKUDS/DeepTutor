"""Ingestion and grounded-retrieval API.

Two audiences again, and the split is the security boundary:

``router`` — mounted at ``/api/grounding`` with the ``learning`` policy.
    Retrieval scoped to the *caller's own* enrolment. There is no grade or major
    parameter: the scope comes from the authenticated profile, so a student
    cannot ask for another grade's material by editing a query string. This is
    the difference between a filter that is applied and a filter that is
    offered.

``admin_router`` — mounted at ``/api/grounding/admin`` with the ``admin``
    policy. Ingestion runs, run status and recovery. Ingestion is an operator
    action: it can publish content, so it must not be reachable by a student.

Why retrieval takes no scope arguments
-------------------------------------
A ``?grade=12`` parameter on a student-facing endpoint is a leak waiting for a
client bug. The enrolment is resolved server-side from the authenticated user,
and :func:`deeptutor.db.repositories.grounding.scope_sql` refuses an enrolment
without a grade. The only way to widen scope is to authenticate as somebody
else, which is a different (and already-tested) problem.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.db.repositories import grounding
from deeptutor.services.exam.scope import (
    Enrolment,
    ScopeError,
    as_http,
    caller_id,
    resolve_enrolment,
)
from deeptutor.services.ingestion import pipeline

logger = logging.getLogger(__name__)

#: Learner-facing retrieval. Mounted at ``/api/grounding`` (learning).
router = APIRouter()

#: Operator-facing ingestion. Mounted at ``/api/grounding/admin`` (admin).
admin_router = APIRouter()


def _enrolment(
    database: Any,
    *,
    user_id: str | None,
    grade_number: int | None,
    major_code: str | None,
) -> Enrolment:
    """The caller's enrolment, resolved the one way every scoped route resolves it.

    This router's docstring has always claimed the scope comes from the
    authenticated profile. Until Phase 6 was reviewed, it *did not*: the grade
    and major were read straight from the query string and the docstring was
    aspirational. Routing the values through the same resolver the exam center
    uses is what makes the claim true, and means the two surfaces cannot drift
    apart again.
    """
    try:
        return resolve_enrolment(
            database,
            user_id=caller_id(user_id),
            grade_number=grade_number,
            major_code=major_code,
        )
    except ScopeError as exc:
        raise as_http(exc) from exc


def _scope_dict(enrolment: Enrolment) -> dict[str, Any]:
    return {
        "grade_number": enrolment.grade_number,
        "major_code": enrolment.major_code,
        "unverified": enrolment.unverified,
    }


def _database() -> Any:
    """Per-request handle; settings resolved late so tests can redirect them."""
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
    if isinstance(exc, grounding.ScopeViolation):
        # A scope violation is the caller asking for something they may not
        # have. 403, not 422: the request is well-formed and refused.
        return HTTPException(
            status_code=403,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, pipeline.IngestionError):
        status = 409 if exc.rule in {"source_not_approved", "checksum_mismatch"} else 422
        return HTTPException(
            status_code=status,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, grounding.CitationError):
        return HTTPException(status_code=422, detail={"rule": exc.rule, "message": exc.detail})
    if isinstance(exc, grounding.GroundingError):
        # A bad query (blank, bad limit, bad threshold) is the caller's mistake,
        # not a server fault. Without this branch it surfaced as a 500, which is
        # both wrong and alarming in an ops dashboard.
        return HTTPException(
            status_code=422,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, DatabaseError):
        logger.warning("grounding database error: %s", type(exc).__name__)
        return HTTPException(status_code=503, detail="database unavailable")
    logger.exception("unexpected grounding error")
    return HTTPException(status_code=500, detail="internal error")


# ---------------------------------------------------------------------------
# Learner: retrieval and citation
# ---------------------------------------------------------------------------


class CitationRequest(BaseModel):
    answer: str = Field(..., min_length=0, max_length=20000)


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, max_length=500),
    user_id: str | None = Query(None),
    grade_number: int = Query(..., ge=1, le=20),
    major_code: str | None = Query(None),
    subject_code: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    min_score: float = Query(0.25, gt=0, le=1),
) -> dict:
    """Relevant chunks in this enrolment's scope, or a structured abstention.

    ``q`` is required because the question is the point: without it this is a
    corpus listing, and a corpus listing can never abstain. The out-of-source
    behaviour the roadmap requires ("asks something not in the books") is
    decided here, by whether any chunk in scope actually addresses the query.

    ``grade_number`` and ``major_code`` are accepted for the single-operator
    dev configuration. With authentication on they are ignored: the enrolment
    is resolved from the caller's stored profile, and an account with no
    profile is refused rather than trusted. Until this was wired the parameters
    *were* the scope, so the docstring described a guarantee the code did not
    make.
    """
    database = _database()
    try:
        enrolment = _enrolment(
            database, user_id=user_id, grade_number=grade_number, major_code=major_code
        )
        chunks = grounding.search(
            database,
            query=q,
            enrolment={"grade_number": enrolment.grade_number,
                       "major_code": enrolment.major_code},
            subject_code=subject_code,
            limit=limit,
            min_score=min_score,
        )
        for chunk in chunks:
            chunk["citation"] = grounding.render_citation(chunk)
        if not chunks:
            return {**grounding.abstain("no_relevant_source"), "scope": _scope_dict(enrolment)}
        return {
            "grounded": True,
            "abstained": False,
            "chunks": chunks,
            "count": len(chunks),
            "scope": _scope_dict(enrolment),
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/validate")
async def validate(
    answer: CitationRequest,
    user_id: str | None = Query(None),
    grade_number: int = Query(..., ge=1, le=20),
    major_code: str | None = Query(None),
) -> dict:
    """Check an answer's citations against what retrieval returns.

    This is the guard the roadmap's "hallucinated citations = 0" criterion rests
    on: a citation is valid only if the exact (book, chapter) pair is among the
    chunks retrieved for this scope.
    """
    database = _database()
    try:
        enrolment = _enrolment(
            database, user_id=user_id, grade_number=grade_number, major_code=major_code
        )
        retrieved = grounding.retrievable(
            database,
            enrolment={"grade_number": enrolment.grade_number,
                       "major_code": enrolment.major_code},
        )
        report = grounding.validate_citations(answer.answer, retrieved)
        return report
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/browse")
async def browse(
    user_id: str | None = Query(None),
    grade_number: int = Query(..., ge=1, le=20),
    major_code: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    """Everything in this enrolment's scope, regardless of relevance.

    The "what can I ask about" view: a student who wants to read rather than ask
    needs the table of contents, not a ranked answer. Kept separate from
    ``/search`` precisely so that ``/search`` can return nothing.
    """
    database = _database()
    try:
        enrolment = _enrolment(
            database, user_id=user_id, grade_number=grade_number, major_code=major_code
        )
        chunks = grounding.retrievable(
            database,
            enrolment={"grade_number": enrolment.grade_number,
                       "major_code": enrolment.major_code},
            limit=limit,
        )
        for chunk in chunks:
            chunk["citation"] = grounding.render_citation(chunk)
        return {"chunks": chunks, "count": len(chunks), "scope": _scope_dict(enrolment)}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/catalogue")
async def catalogue(
    user_id: str | None = Query(None),
    grade_number: int = Query(..., ge=1, le=20),
    major_code: str | None = Query(None),
) -> dict:
    """Which books are actually available to this enrolment, with counts.

    Useful for the UI's "which books can I ask about" panel, and for an operator
    to see why a student gets nothing: zero visible chunks is a very different
    answer from an empty library.

    The major predicate used to be ``(? IS NULL OR s.major_code = ?)``, which
    meant a caller who passed no major saw every major's books -- the same
    widening :func:`scope_sql` was written to forbid, reintroduced here in one
    line because it was spelled differently. It now mirrors the retrieval rule:
    no major means only books with no major.
    """
    database = _database()
    try:
        enrolment = _enrolment(
            database, user_id=user_id, grade_number=grade_number, major_code=major_code
        )
        with database.read() as conn:
            if enrolment.major_code is None:
                major_clause = "AND s.major_code IS NULL "
                params: tuple[Any, ...] = (enrolment.grade_number,)
            else:
                major_clause = "AND (s.major_code IS NULL OR s.major_code = ?) "
                params = (enrolment.grade_number, enrolment.major_code)
            rows = list(
                conn.query(
                    "SELECT s.id, s.title, s.source_type, COUNT(c.chunk_key) AS chunks "
                    "FROM catalog_sources s "
                    "LEFT JOIN ingestion_chunks c ON c.source_id = s.id "
                    "WHERE s.publicly_retrievable = 1 "
                    "AND (s.grade_number IS NULL OR s.grade_number = ?) "
                    + major_clause
                    + "GROUP BY s.id, s.title, s.source_type "
                    "ORDER BY s.title",
                    params,
                )
            )
        return {
            "grade_number": enrolment.grade_number,
            "major_code": enrolment.major_code,
            "sources": rows,
            "scope": _scope_dict(enrolment),
        }
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Admin: ingestion
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=200)
    markdown: str | None = Field(None, max_length=5_000_000)
    document_path: str | None = Field(None, max_length=2000)
    document_key: str = Field("", max_length=200)
    accept_checksum_change: bool = False


@admin_router.post("/ingest", status_code=201)
async def ingest(payload: IngestRequest) -> dict:
    """Run an ingestion. Returns the recorded run, including failures.

    A failed run still returns its outcome (with ``status='failed'``) rather
    than raising, because "the book needs OCR" is a result an operator must see,
    not an unexpected error.
    """
    database = _database()
    try:
        outcome = pipeline.run_ingestion(
            database,
            source_id=payload.source_id,
            markdown=payload.markdown,
            document_path=payload.document_path or None,
            document_key=payload.document_key,
            accept_checksum_change=payload.accept_checksum_change,
        )
        return outcome.as_dict()
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/runs")
async def list_runs(
    source_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    database = _database()
    try:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        params.append(limit)
        with database.read() as conn:
            rows = [
                dict(row)
                for row in conn.query(
                    "SELECT * FROM ingestion_runs WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at DESC LIMIT ?",
                    tuple(params),
                )
            ]
        return {"runs": rows, "count": len(rows)}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    database = _database()
    try:
        with database.read() as conn:
            row = conn.query_one("SELECT * FROM ingestion_runs WHERE id = ?", (run_id,))
            if row is None:
                raise HTTPException(status_code=404, detail="run not found")
            chunks = [
                dict(chunk)
                for chunk in conn.query(
                    "SELECT chunk_key, page_index, chapter_index, chapter_title, "
                    "block_kind, LENGTH(text) AS length FROM ingestion_chunks "
                    "WHERE run_id = ? ORDER BY page_index, ordinal LIMIT 500",
                    (run_id,),
                )
            ]
        return {"run": row, "chunks": chunks}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.post("/recover")
async def recover(older_than_seconds: int = Query(900, ge=60, le=86400)) -> dict:
    """Fail runs abandoned by a crashed process so their source can be retried."""
    database = _database()
    try:
        recovered = pipeline.recover_stale_runs(database, older_than_seconds=older_than_seconds)
        return {"recovered": recovered, "count": len(recovered)}
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    finally:
        database.close()
