"""Read-only report projection for a learner already authorized by the caller."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Any

from deeptutor.multi_user.paths import get_path_service_for_scope, scope_for_user

_LIMIT = 50
_QUIZ_FIELDS = (
    "id",
    "question_id",
    "material_id",
    "material_title",
    "section_id",
    "section_title",
    "question",
    "is_correct",
    "hints_used",
    "attempt_count",
    "updated_at",
)
_PROGRESS_FIELDS = (
    "material_id",
    "latest_locator",
    "latest_percentage",
    "furthest_locator",
    "furthest_percentage",
    "updated_at",
)
_ACTIVITY_FIELDS = (
    "activity_id",
    "material_id",
    "extension_id",
    "action",
    "locator",
    "result_type",
    "created_at",
)


def _open_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_columns(conn: sqlite3.Connection, table: str, required: tuple[str, ...]) -> bool:
    columns = {
        row["name"] for row in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))
    }
    return set(required).issubset(columns)


def _read_report(paths: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "reading_status": "not_initialized",
        "quiz_status": "not_initialized",
        "progress_total": 0,
        "progress": [],
        "activities": [],
        "quiz_total": 0,
        "quizzes": [],
        "limit": _LIMIT,
    }
    learning = paths.get_workspace_dir() / "learning"
    mastery = learning / "mastery" / "mastery.sqlite3"
    if mastery.exists():
        with closing(_open_readonly(mastery)) as conn:
            if not (
                _has_columns(conn, "reading_progress", _PROGRESS_FIELDS)
                and _has_columns(conn, "reading_activities", _ACTIVITY_FIELDS)
            ):
                result["reading_status"] = "migration_required"
            else:
                conn.execute("BEGIN")
                result["reading_status"] = "available"
                result["progress_total"] = conn.execute(
                    "SELECT COUNT(*) FROM reading_progress"
                ).fetchone()[0]
                result["progress"] = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT material_id, latest_locator, latest_percentage, furthest_locator, "
                        "furthest_percentage, updated_at FROM reading_progress "
                        "ORDER BY updated_at DESC, material_id LIMIT ?",
                        (_LIMIT,),
                    )
                ]
                result["activities"] = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT activity_id, material_id, extension_id, action, locator, result_type, "
                        "created_at FROM reading_activities ORDER BY created_at DESC, activity_id LIMIT ?",
                        (_LIMIT,),
                    )
                ]
    elif (learning / "mastery.sqlite3").exists():
        result["reading_status"] = "migration_required"

    chat_db = paths.get_chat_history_db()
    if chat_db.exists():
        with closing(_open_readonly(chat_db)) as conn:
            if not (
                _has_columns(
                    conn, "notebook_entries", _QUIZ_FIELDS + ("source", "session_id", "created_at")
                )
                and _has_columns(conn, "sessions", ("id", "deleted_at"))
            ):
                result["quiz_status"] = "migration_required"
            else:
                # Match the Question Bank's source and recycle-bin visibility.
                where = "n.source = ? AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.id = n.session_id AND s.deleted_at IS NOT NULL)"
                conn.execute("BEGIN")
                result["quiz_status"] = "available"
                result["quiz_total"] = conn.execute(
                    "SELECT COUNT(*) FROM notebook_entries n WHERE " + where,
                    ("immersive_reading",),
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT "
                    + ", ".join("n." + field for field in _QUIZ_FIELDS)
                    + " FROM notebook_entries n WHERE "
                    + where
                    + " ORDER BY n.created_at DESC, n.id DESC LIMIT ?",
                    ("immersive_reading", _LIMIT),
                )
                for row in rows:
                    item = dict(row)
                    item["is_correct"] = (
                        None if item["is_correct"] is None else bool(item["is_correct"])
                    )
                    result["quizzes"].append(item)
    for item in result["progress"]:
        item["material_title"] = ""
    catalog = paths.get_workspace_dir() / "reading" / "_catalog.sqlite3"
    if result["progress"] and catalog.exists():
        with closing(_open_readonly(catalog)) as conn:
            if _has_columns(conn, "reading_materials", ("material_id", "title", "filename")):
                for item in result["progress"]:
                    row = conn.execute(
                        "SELECT title, filename FROM reading_materials WHERE material_id = ?",
                        (item["material_id"],),
                    ).fetchone()
                    if row:
                        item["material_title"] = row["title"] or row["filename"] or ""
    return result


async def reading_report_for(learner_user_id: str) -> dict[str, Any]:
    """Caller enforces view_reports; do not migrate or initialize learner stores."""
    paths = get_path_service_for_scope(scope_for_user(learner_user_id, is_admin=False))
    return await asyncio.to_thread(_read_report, paths)
