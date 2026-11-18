"""Exam center API.

Three audiences, and the split is the security model:

``router`` — mounted at ``/api/exam`` with the ``learning`` policy.
    What a student does: see published exams, submit answers, read their own
    attempt and mistake report.

``admin_router`` — mounted at ``/api/exam/admin`` with the ``admin`` policy.
    What an operator does: author questions, build exams, publish, validate.

``review_router`` — mounted at ``/api/exam/review`` with the ``admin`` policy.
    Grading overrides and appeals. Separated from ``admin`` because it is the
    only surface that can change a *recorded* score, and putting it behind its
    own prefix makes it visible in a log and easy to restrict further.

Why a student's attempt lookup checks ownership
-----------------------------------------------
``GET /api/exam/attempts/{id}`` takes an opaque id. If any authenticated student
could read any attempt, a guessed or shared id would expose another student's
score and answers. The check is explicit at every read, not assumed from the
route's prefix: a route that is "probably fine" is how an IDOR ships.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.db.repositories import exam as repo
from deeptutor.services.exam.scope import ScopeError, as_http, caller_id
from deeptutor.services.exam.scoring import ScoringError

router = APIRouter()
admin_router = APIRouter()
review_router = APIRouter()


def _database() -> Any:
    from deeptutor.db.config import get_database_settings

    settings = get_database_settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=503, detail="database is not configured; set DEEPTUTOR_DATABASE_URL"
        )
    database = open_database(settings)
    if database is None:  # pragma: no cover
        raise HTTPException(status_code=503, detail="database is unavailable")
    return database


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, repo.ExamError):
        not_found = {
            "question_not_found",
            "policy_not_found",
            "exam_not_found",
            "attempt_not_found",
            "item_not_found",
        }
        if exc.rule in not_found:
            return HTTPException(
                status_code=404,
                detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
            )
        conflict = {
            "attempt_already_submitted",
            "exam_not_open",
            "unreviewed_questions",
            "duplicate_question",
        }
        status = 409 if exc.rule in conflict else 422
        return HTTPException(
            status_code=status,
            detail={"rule": exc.rule, "message": exc.detail, "field": exc.field},
        )
    if isinstance(exc, ScoringError):
        return HTTPException(status_code=422, detail={"rule": exc.rule, "message": exc.detail})
    if isinstance(exc, ScopeError):
        # 403, not 404: the exam is publicly listed, so pretending it does not
        # exist would hide a scoping bug behind a plausible-looking 404.
        return as_http(exc)
    if isinstance(exc, DatabaseError):
        return HTTPException(status_code=503, detail="database unavailable")
    raise exc


def _actor(request_actor: str | None) -> str:
    """Who performed an action, for the audit trail.

    A blank actor is allowed on the dev path but is a bad idea in production: an
    override with no name attached is indistinguishable from a bug.
    """
    return (request_actor or "").strip() or "unknown"


# ---------------------------------------------------------------------------
# Student surface
# ---------------------------------------------------------------------------


class SubmitRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=200)
    answers: dict[str, str] | list[str] = Field(default_factory=dict)
    attempt_no: int = Field(1, ge=1, le=100)


@router.get("/exams")
async def list_published(
    user_id: str | None = Query(None),
    grade_number: int | None = Query(None, ge=1, le=20),
    major_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Published exams a student can sit, limited to their own enrolment.

    Deliberately excludes drafts: an unpublished exam may still contain
    unreviewed questions, and letting a student see it would defeat Gate 6.

    The listing is filtered by the enrolment resolved from the caller's stored
    profile, not by the query parameters. ``grade_number``/``major_code`` are
    still accepted so an existing client keeps working, but they are ignored
    once a profile exists -- the same rule submission follows, so the listing
    cannot show a paper the guard will refuse.
    """
    database = _database()
    try:
        enrolment = repo.resolve_enrolment(
            database,
            user_id=caller_id(user_id),
            grade_number=grade_number,
            major_code=major_code,
        )
        exams = repo.list_exams_in_scope(database, enrolment, status="published", limit=limit)
        return {
            "exams": exams,
            "count": len(exams),
            "scope": enrolment.as_dict(),
        }
    except ScopeError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/exams/{exam_id}")
async def get_published_exam(exam_id: str, user_id: str | None = Query(None)) -> dict:
    """The exam as a student sees it: questions with choices, and no answer keys.

    Scoped like submission is. An exam a student cannot sit is an exam they
    should not be able to read either -- otherwise the questions of every grade
    leak through an id that the listing was careful not to show.
    """
    database = _database()
    try:
        exam = repo.get_exam(database, exam_id)
        if exam["status"] != "published":
            raise HTTPException(status_code=404, detail="exam not found")
        enrolment = repo.resolve_enrolment(database, user_id=caller_id(user_id))
        repo.require_scope_reaches(
            enrolment,
            grade_number=exam.get("grade_number"),
            major_code=exam.get("major_code"),
            what="این آزمون",
        )
        items = []
        for item in exam["items"]:
            question = repo.get_question(
                database, item["question_id"], int(item["question_version"])
            )
            items.append(
                {
                    "question_id": question["question_id"],
                    "version": question["version"],
                    "position": item["position"],
                    "question_type": question["question_type"],
                    "body": question["body"],
                    # The answer key is *never* sent to a student. Withholding it
                    # here rather than in the client is the only version of this
                    # rule that a modified client cannot undo.
                    "choices": [
                        choice for choice in str(question["choices"]).split("\n") if choice.strip()
                    ],
                    "points": float(
                        item["points"] if item["points"] is not None else question["points"]
                    ),
                }
            )
        return {
            "id": exam["id"],
            "title": exam["title"],
            "duration_minutes": exam["duration_minutes"],
            "items": items,
        }
    except (repo.ExamError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.post("/exams/{exam_id}/submit")
async def submit(exam_id: str, payload: SubmitRequest) -> dict:
    """Submit answers and receive the graded attempt.

    Safe to retry: identical answers to the same attempt return the existing
    result instead of a second attempt.

    Raises 403 when the exam's grade or major is outside the caller's
    enrolment. The check lives in the repository, next to the write, so no
    future caller can reach the insert without passing through it.
    """
    database = _database()
    try:
        attempt = repo.submit_exam(
            database,
            exam_id=exam_id,
            # With authentication on this is the session's user id; the body
            # value is discarded, so a student cannot submit as someone else.
            user_id=caller_id(payload.user_id),
            answers=payload.answers,
            attempt_no=payload.attempt_no,
        )
        return _attempt_view(attempt, reveal_keys=True)
    except (repo.ExamError, ScopeError) as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: str, user_id: str = Query(..., min_length=1)) -> dict:
    """One attempt, only for its owner.

    ``user_id`` is required and compared against the stored owner. This is the
    ownership check described in the module docstring: an attempt id is opaque
    but not secret, and treating it as a capability would be an IDOR.
    """
    database = _database()
    try:
        attempt = repo.get_attempt(database, attempt_id)
        if attempt["user_id"] != user_id:
            # 404, not 403: telling a stranger that the attempt exists is itself
            # a small disclosure, and they have no legitimate use for the answer.
            raise HTTPException(status_code=404, detail="attempt not found")
        return _attempt_view(attempt, reveal_keys=True)
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@router.get("/attempts")
async def list_my_attempts(
    user_id: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=200)
) -> dict:
    database = _database()
    try:
        attempts = repo.list_attempts(database, user_id=user_id, limit=limit)
        return {
            "attempts": [
                {key: value for key, value in attempt.items() if key != "question_snapshot"}
                for attempt in attempts
            ],
            "count": len(attempts),
        }
    finally:
        database.close()


@router.get("/attempts/{attempt_id}/mistakes")
async def get_mistakes(attempt_id: str, user_id: str = Query(..., min_length=1)) -> dict:
    """Which topics this student should review."""
    database = _database()
    try:
        attempt = repo.get_attempt(database, attempt_id)
        if attempt["user_id"] != user_id:
            raise HTTPException(status_code=404, detail="attempt not found")
        return repo.mistake_report(database, attempt_id)
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


def _attempt_view(attempt: dict[str, Any], *, reveal_keys: bool) -> dict[str, Any]:
    """Shape an attempt for a response.

    Answer keys are stripped from the *item* rows the student sees and kept only
    in the score breakdown, because after submission the key is no longer secret
    -- the student has already answered, and hiding it would make the feedback
    useless. Showing it *before* submission is what must never happen, and that
    is enforced in `get_published_exam`.
    """
    view = {key: value for key, value in attempt.items() if key != "question_snapshot"}
    return view


# ---------------------------------------------------------------------------
# Operator surface
# ---------------------------------------------------------------------------


class QuestionPayload(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    question_type: str = "multiple_choice"
    choices: list[str] = Field(default_factory=list)
    answer_key: str = ""
    key_status: str = "valid"
    points: float = 1.0
    difficulty: str = "medium"
    grade_number: int | None = None
    major_code: str | None = None
    subject_code: str | None = None
    chapter_title: str = ""
    topic: str = ""
    rubric: str = ""
    authored_by: str = ""
    review_status: str = "draft"


@admin_router.post("/questions", status_code=201)
async def create_question(payload: QuestionPayload) -> dict:
    database = _database()
    try:
        return repo.create_question(
            database,
            repo.QuestionInput(
                question_id=payload.question_id,
                body=payload.body,
                question_type=payload.question_type,
                choices=tuple(payload.choices),
                answer_key=payload.answer_key,
                key_status=payload.key_status,
                points=payload.points,
                difficulty=payload.difficulty,
                grade_number=payload.grade_number,
                major_code=payload.major_code,
                subject_code=payload.subject_code,
                chapter_title=payload.chapter_title,
                topic=payload.topic,
                rubric=payload.rubric,
                authored_by=payload.authored_by,
                review_status=payload.review_status,
            ),
        )
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/questions")
async def list_questions(
    grade_number: int | None = Query(None, ge=1, le=20),
    major_code: str | None = Query(None),
    review_status: str | None = Query(None),
    latest_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    database = _database()
    try:
        questions = repo.list_questions(
            database,
            grade_number=grade_number,
            major_code=major_code,
            review_status=review_status,
            latest_only=latest_only,
            limit=limit,
        )
        return {"questions": questions, "count": len(questions)}
    finally:
        database.close()


class ReviewQuestionPayload(BaseModel):
    version: int = Field(..., ge=1)
    review_status: str
    actor: str = ""


@admin_router.post("/questions/{question_id}/review")
async def review_question(question_id: str, payload: ReviewQuestionPayload) -> dict:
    database = _database()
    try:
        return repo.review_question(
            database,
            question_id=question_id,
            version=payload.version,
            review_status=payload.review_status,
            actor=_actor(payload.actor),
        )
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


class PolicyPayload(BaseModel):
    name: str = ""
    negative_ratio: float = Field(0.0, ge=0, le=1)
    blank_is_neutral: bool = True
    broken_question_policy: str = "void"
    essay_min_ratio: float = Field(0.0, ge=0, le=1)
    essay_max_ratio: float = Field(1.0, ge=0, le=1)
    allow_partial_credit: bool = True


@admin_router.post("/policies", status_code=201)
async def create_policy(payload: PolicyPayload) -> dict:
    database = _database()
    try:
        return repo.create_policy(
            database,
            name=payload.name,
            negative_ratio=payload.negative_ratio,
            blank_is_neutral=payload.blank_is_neutral,
            broken_question_policy=payload.broken_question_policy,
            essay_min_ratio=payload.essay_min_ratio,
            essay_max_ratio=payload.essay_max_ratio,
            allow_partial_credit=payload.allow_partial_credit,
        )
    except ScoringError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/policies")
async def list_policies() -> dict:
    database = _database()
    try:
        policies = repo.list_policies(database)
        return {"policies": policies, "count": len(policies)}
    finally:
        database.close()


class ExamItemPayload(BaseModel):
    question_id: str = Field(..., min_length=1)
    question_version: int | None = Field(None, ge=1)
    points: float | None = Field(None, gt=0)


class BlueprintPayload(BaseModel):
    chapter: str = ""
    topic: str = ""
    difficulty: str = ""
    count: int = 0
    points: float | None = None


class ExamPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    items: list[ExamItemPayload] = Field(default_factory=list)
    policy_id: str | None = None
    grade_number: int | None = None
    major_code: str | None = None
    subject_code: str | None = None
    duration_minutes: int = Field(0, ge=0)
    blueprint: list[BlueprintPayload] = Field(default_factory=list)
    status: str = "draft"


@admin_router.post("/exams", status_code=201)
async def create_exam(payload: ExamPayload) -> dict:
    database = _database()
    try:
        return repo.create_exam(
            database,
            title=payload.title,
            items=[
                repo.ExamItemInput(
                    question_id=item.question_id,
                    question_version=item.question_version,
                    points=item.points,
                )
                for item in payload.items
            ],
            policy_id=payload.policy_id,
            grade_number=payload.grade_number,
            major_code=payload.major_code,
            subject_code=payload.subject_code,
            duration_minutes=payload.duration_minutes,
            blueprint=[
                repo.Blueprint(
                    chapter=spec.chapter,
                    topic=spec.topic,
                    difficulty=spec.difficulty,
                    count=spec.count,
                    points=spec.points,
                )
                for spec in payload.blueprint
            ],
            status=payload.status,
        )
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/exams")
async def list_all_exams(
    grade_number: int | None = Query(None, ge=1, le=20),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    database = _database()
    try:
        exams = repo.list_exams(database, grade_number=grade_number, status=status, limit=limit)
        return {"exams": exams, "count": len(exams)}
    finally:
        database.close()


@admin_router.post("/exams/{exam_id}/publish")
async def publish_exam(exam_id: str, actor: str = Query("")) -> dict:
    database = _database()
    try:
        return repo.publish_exam(database, exam_id, actor=_actor(actor))
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/exams/{exam_id}/validate")
async def validate_exam(exam_id: str) -> dict:
    """Gate 6 evidence: an exam checked against its blueprint and review set."""
    database = _database()
    try:
        return repo.validate_exam(database, exam_id)
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@admin_router.get("/attempts")
async def list_attempts(
    exam_id: str | None = Query(None),
    user_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    database = _database()
    try:
        attempts = repo.list_attempts(database, exam_id=exam_id, user_id=user_id, limit=limit)
        return {
            "attempts": [
                {key: value for key, value in attempt.items() if key != "question_snapshot"}
                for attempt in attempts
            ],
            "count": len(attempts),
        }
    finally:
        database.close()


# ---------------------------------------------------------------------------
# Review surface: the only way a recorded score may change
# ---------------------------------------------------------------------------


class RegradePayload(BaseModel):
    essay_scores: dict[str, float] = Field(default_factory=dict)
    actor: str = ""
    reason: str = ""


@review_router.post("/attempts/{attempt_id}/regrade")
async def regrade(attempt_id: str, payload: RegradePayload) -> dict:
    """Re-grade from the frozen snapshot, with an audit row.

    Cannot change a multiple-choice verdict: the snapshot holds the same key it
    always did, so this can only supply information that was missing (an essay
    score). That restriction is a property of what is stored, not of this code.
    """
    database = _database()
    try:
        return repo.regrade_attempt(
            database,
            attempt_id=attempt_id,
            essay_scores=payload.essay_scores or None,
            actor=_actor(payload.actor),
            reason=payload.reason,
        )
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


class OverridePayload(BaseModel):
    question_id: str = Field(..., min_length=1)
    points_awarded: float
    actor: str = ""
    reason: str = Field(..., min_length=1)
    change_kind: str = "human_review"


@review_router.post("/attempts/{attempt_id}/override")
async def override(attempt_id: str, payload: OverridePayload) -> dict:
    """A human overrules one item. Requires a reason: an unexplained override is a bug."""
    database = _database()
    try:
        return repo.override_item_score(
            database,
            attempt_id=attempt_id,
            question_id=payload.question_id,
            points_awarded=payload.points_awarded,
            actor=_actor(payload.actor),
            reason=payload.reason,
            change_kind=payload.change_kind,
        )
    except repo.ExamError as exc:
        raise _translate(exc) from exc
    finally:
        database.close()


@review_router.get("/attempts/{attempt_id}/changes")
async def changes(attempt_id: str) -> dict:
    database = _database()
    try:
        rows = repo.grade_changes(database, attempt_id)
        return {"changes": rows, "count": len(rows)}
    finally:
        database.close()
