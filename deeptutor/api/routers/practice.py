"""Practice workflow. Every operation resolves the current user's scoped store."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import csv
import io
import time
from typing import Any, Literal
import zipfile

from defusedxml.ElementTree import ParseError
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from deeptutor.api.routers.question_notebook import NotebookEntryItem, _course_session_ids
from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user
from deeptutor.services.practice.answers import check_answer
from deeptutor.services.practice.importing import MAX_BYTES, preview
from deeptutor.services.practice.scheduler import Rating, day_bounds
from deeptutor.services.practice.storage import PracticeStore, ReviewConflict
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.session.sqlite_store import get_sqlite_session_store_for

router = APIRouter()


def _require_self_only(learner: str) -> None:
    """Write actions never accept a learner scope: only the learner writes."""
    if learner:
        raise HTTPException(status_code=403, detail="Write actions are limited to the learner")


def _practice_scope(learner: str) -> tuple[Any, Callable[[], LearningStore]]:
    """Resolve the practice store and a learning-store factory for a request.

    Without ``learner`` that is the caller's own scope, exactly as before. With
    a learner id the caller must be an admin or a guardian holding
    ``view_reports`` (the guardian-report permission), the learner's stores are
    resolved read-only, and the access lands in the supervisor audit log —
    mirroring ``GET /api/multi-user/learners/{id}/guardian-report``. The
    learning store is a factory because only analytics needs it.
    """
    if not learner:
        return get_sqlite_session_store(), lambda: LearningStore()
    from deeptutor.api.routers.multi_user import _log_supervisor_action, _require_guardian_access

    current = get_current_user()
    _username, _record, actor_user_id, is_admin = _require_guardian_access(
        current, learner, "view_reports"
    )
    service = get_path_service_for_scope(scope_for_user(learner, is_admin=False))
    _log_supervisor_action(
        "guardian_practice_view",
        actor_user_id=actor_user_id,
        learner_user_id=learner,
        is_admin=is_admin,
        summary={"scope": "practice"},
    )
    return get_sqlite_session_store_for(service), lambda: LearningStore.for_path_service(service)


class PracticeSummary(BaseModel):
    total: int
    mistakes: int
    due: int
    overdue: int
    reviewed_today: int
    next_due_at: float | None
    day_end: float
    timezone: str
    unavailable_workspaces: list[str] = Field(default_factory=list)


class PracticeQuestion(BaseModel):
    entry: NotebookEntryItem
    state: dict
    content_workspace_id: str = ""
    content_workspace_name: str = ""


class PracticeCounts(BaseModel):
    questions: int
    mistakes: int
    reviews: int
    reading_seconds: int = 0


class PracticeDailyCounts(PracticeCounts):
    date: str


class PracticeSourceCounts(PracticeCounts):
    source: str


class PracticeReadingMaterial(BaseModel):
    material_id: str
    reading_seconds: int


class PracticeAnalytics(BaseModel):
    timezone: str
    days: int
    start_date: str
    end_date: str
    updated_at: float
    daily: list[PracticeDailyCounts]
    sources: list[PracticeSourceCounts]
    totals: PracticeCounts
    materials: list[PracticeReadingMaterial] = Field(default_factory=list)


class AnswerRequest(BaseModel):
    answer: str = Field(default="", max_length=20000)


class ReviewRequest(AnswerRequest):
    self_report: bool = False
    request_id: str = Field(min_length=16, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    version: int = Field(ge=0)
    rating: Rating


class CommitRequest(BaseModel):
    token: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]+$")


def _validate_timezone(timezone: str) -> tuple[float, float]:
    try:
        return day_bounds(timezone, time.time())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _entry(entry_id: int, store: Any | None = None) -> dict:
    store = store or get_sqlite_session_store()
    if not await asyncio.to_thread(PracticeStore(store.db_path).is_visible, entry_id):
        raise HTTPException(404, "Question not found")
    entry = await store.get_notebook_entry(entry_id)
    if entry is None:
        raise HTTPException(404, "Question not found")
    return entry


@router.get("/summary", response_model=PracticeSummary)
async def summary(
    timezone: str = "UTC",
    course_id: str = "",
    all_workspaces: bool = False,
    learner: str = Query(default="", max_length=64),
):
    store, _learning_factory = _practice_scope(learner)
    if learner:
        course_id, all_workspaces = "", False  # the learner's own scope, not the caller's
    if all_workspaces and not course_id:
        from deeptutor.services.workspace.navigation import read_workspace_indexes

        _, end = _validate_timezone(timezone)

        async def read():
            return [await summary(timezone, course_id, learner="")]

        rows, unavailable = await read_workspace_indexes(read)
        return {
            **{
                key: sum(row[key] for row in rows)
                for key in ("total", "mistakes", "due", "overdue", "reviewed_today")
            },
            "next_due_at": min(
                (row["next_due_at"] for row in rows if row["next_due_at"]), default=None
            ),
            "day_end": end,
            "timezone": timezone,
            "unavailable_workspaces": unavailable,
        }

    sessions = await _course_session_ids(store, course_id)
    try:
        return await asyncio.to_thread(PracticeStore(store.db_path).overview, timezone, sessions)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/queue", response_model=list[PracticeQuestion])
async def queue(
    timezone: str = "UTC",
    course_id: str = "",
    category_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    all_workspaces: bool = False,
    learner: str = Query(default="", max_length=64),
):
    store, _learning_factory = _practice_scope(learner)
    if learner:
        course_id, all_workspaces = "", False
    if all_workspaces and not course_id:
        from deeptutor.services.workspace.navigation import read_workspace_indexes

        _validate_timezone(timezone)

        async def read():
            return await queue(timezone, course_id, category_id, limit, learner="")

        rows, _ = await read_workspace_indexes(read)
        rows.sort(
            key=lambda row: (
                row["state"].get("due_at") or row["entry"].get("created_at", 0),
                row["content_workspace_id"],
                row["entry"]["id"],
            )
        )
        return rows[:limit]

    practice = PracticeStore(store.db_path)
    sessions = await _course_session_ids(store, course_id)
    try:
        ids = await asyncio.to_thread(practice.queue, timezone, sessions, category_id, limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    from deeptutor.services.workspace.context import current_workspace_id

    questions = []
    for entry_id in ids:
        entry = await store.get_notebook_entry(entry_id)
        if entry:
            questions.append(
                {
                    "entry": entry,
                    "state": await asyncio.to_thread(practice.state, entry_id),
                    "content_workspace_id": current_workspace_id(),
                }
            )
    return questions


@router.get("/analytics", response_model=PracticeAnalytics)
async def practice_analytics(
    timezone: str = "UTC",
    days: int = 30,
    course_id: str = "",
    all_workspaces: bool = False,
    learner: str = Query(default="", max_length=64),
):
    _validate_timezone(timezone)
    if days not in {7, 30, 90}:
        raise HTTPException(422, "Days must be 7, 30, or 90")
    store, learning_factory = _practice_scope(learner)
    if learner:
        course_id, all_workspaces = "", False
    if all_workspaces and not course_id:
        from deeptutor.services.workspace.navigation import read_workspace_indexes

        async def read():
            return [await practice_analytics(timezone, days, course_id, learner="")]

        rows, _ = await read_workspace_indexes(read)
        if not rows:
            return await practice_analytics(timezone, days, course_id)
        result = dict(rows[0])
        for bucket, identity in (("daily", "date"), ("sources", "source")):
            combined = {}
            for row in rows:
                for item in row[bucket]:
                    target = combined.setdefault(
                        item[identity],
                        {
                            identity: item[identity],
                            "questions": 0,
                            "mistakes": 0,
                            "reviews": 0,
                            "reading_seconds": 0,
                        },
                    )
                    for metric in ("questions", "mistakes", "reviews", "reading_seconds"):
                        target[metric] += item[metric]
            result[bucket] = list(combined.values())
        result["totals"] = {
            metric: sum(row["totals"][metric] for row in rows)
            for metric in ("questions", "mistakes", "reviews", "reading_seconds")
        }
        materials: dict[str, int] = {}
        for row in rows:
            for item in row.get("materials", []):
                materials[item["material_id"]] = (
                    materials.get(item["material_id"], 0) + item["reading_seconds"]
                )
        result["materials"] = [
            {"material_id": material_id, "reading_seconds": seconds}
            for material_id, seconds in sorted(materials.items(), key=lambda pair: -pair[1])
        ]
        return result

    sessions = await _course_session_ids(store, course_id)
    try:
        result = await asyncio.to_thread(
            PracticeStore(store.db_path).analytics, timezone, days, sessions
        )
        reading = await asyncio.to_thread(learning_factory().reading_time_window, timezone, days)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for item in result["daily"]:
        item["reading_seconds"] = reading["daily"].get(item["date"], 0)
    result["totals"]["reading_seconds"] = sum(reading["daily"].values())
    result["materials"] = reading["materials"]
    return result


@router.get("/questions/{entry_id}", response_model=PracticeQuestion)
async def practice_question(entry_id: int, learner: str = Query(default="", max_length=64)):
    store, _learning_factory = _practice_scope(learner)
    entry = await _entry(entry_id, store)
    state = await asyncio.to_thread(PracticeStore(store.db_path).state, entry_id)
    return {"entry": entry, "state": state}


@router.post("/questions/{entry_id}/check")
async def check(entry_id: int, payload: AnswerRequest, learner: str = Query(default="")):
    _require_self_only(learner)
    entry = await _entry(entry_id)
    return {"correct": check_answer(entry, payload.answer)}


@router.post("/questions/{entry_id}/review")
async def review(entry_id: int, payload: ReviewRequest, learner: str = Query(default="")):
    _require_self_only(learner)
    try:
        return await asyncio.to_thread(
            PracticeStore(get_sqlite_session_store().db_path).review,
            entry_id,
            payload.request_id,
            payload.version,
            payload.rating,
            payload.answer,
            self_report=payload.self_report,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/import/template")
async def import_template(format: Literal["csv", "xlsx"] = "csv"):
    rows = [
        [
            "question",
            "question_type",
            "A",
            "B",
            "C",
            "D",
            "correct_answer",
            "explanation",
            "tags",
            "user_answer",
        ],
        ["2 + 2 = ?", "single_choice", "3", "4", "5", "6", "B", "2 + 2 = 4", "Math,Addition", ""],
        [
            "Select the prime numbers",
            "multi_choice",
            "2",
            "3",
            "4",
            "6",
            "A,B",
            "2 and 3 are prime",
            "Math",
            "",
        ],
        ["The Earth orbits the Sun", "true_false", "", "", "", "", "true", "", "Science", ""],
        [
            "Explain photosynthesis",
            "short_answer",
            "",
            "",
            "",
            "",
            "Plants convert light into chemical energy.",
            "",
            "Biology",
            "",
        ],
    ]
    if format == "xlsx":
        from openpyxl import Workbook

        book = Workbook()
        for row in rows:
            book.active.append(row)
        output = io.BytesIO()
        book.save(output)
        book.close()
        data = output.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        output = io.StringIO(newline="")
        csv.writer(output).writerows(rows)
        data, media = output.getvalue().encode("utf-8-sig"), "text/csv"
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="practice-template.{format}"'},
    )


@router.post("/import/preview")
async def import_preview(
    file: UploadFile = File(...),
    target: Literal["bank", "mistakes"] = Form("bank"),
    course_id: str = Form("", max_length=200),
    learner: str = Query(default=""),
):
    _require_self_only(learner)
    await _course_session_ids(get_sqlite_session_store(), course_id)
    try:
        data = await file.read(MAX_BYTES + 1)
        parsed = await asyncio.to_thread(preview, data, file.filename or "")
    except (ValueError, UnicodeError, OSError, zipfile.BadZipFile, KeyError, ParseError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()
    token = None
    if not parsed["errors"]:
        token = await asyncio.to_thread(
            PracticeStore(get_sqlite_session_store().db_path).stage_import,
            file.filename or "",
            target,
            parsed["questions"],
            course_id,
        )
    return {
        "token": token,
        "total": len(parsed["questions"]) + len(parsed["errors"]),
        "valid": len(parsed["questions"]),
        "errors": parsed["errors"],
        "samples": parsed["questions"][:5],
    }


@router.post("/import/commit")
async def import_commit(payload: CommitRequest, learner: str = Query(default="")):
    _require_self_only(learner)
    try:
        return await asyncio.to_thread(
            PracticeStore(get_sqlite_session_store().db_path).commit_import, payload.token
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
