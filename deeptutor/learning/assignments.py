"""Assignment store for the K12 教师作业闭环 — JSON file warehouse.

教师布置 → 学生作答 → 自动判分 → 教师看统计 needs a small amount of durable
state, and per the v1 design no new database table is introduced: assignments
live in one JSON document next to ``classes.json``/``device_credentials.json``
(``data/system/auth/assignments.json``), following the same fail-open read /
atomic-write / single-process write lock conventions as the roster store.

Record shape (one entry per assignment id)::

    { assignment_id, class_id, book_id?, teacher_id, title, created_at, due_at?,
      items: [{kp_id, question: {stem, type: "choice"|"short", options[],
               answer, explanation?}}],
      submissions: { student_id: {submitted_at, results: [{kp_id, q_idx,
                    answer, correct}] } } }

``items`` are a snapshot taken at assignment time from the teacher-readable
question source (``KP.meta["question_bank"]``), so later edits to the bank
never rewrite an assignment a student already sees. Submissions are keyed by
the roster username (what classes.json stores), and a resubmission replaces
the previous attempt wholesale — the store stays last-attempt-wins and
idempotent rather than growing an attempt log v1 does not use.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_text

logger = logging.getLogger(__name__)

#: Serialises read-modify-write cycles on the document, mirroring the roster
#: store's ``_CLASSES_WRITE_LOCK`` (single-process FastAPI deployments are
#: fully covered; multi-worker deployments race, as documented for classes).
_ASSIGNMENTS_WRITE_LOCK = threading.Lock()

#: Hard caps that keep one malformed client from unbounding the document.
MAX_ITEMS_PER_ASSIGNMENT = 50
MAX_SUBMISSIONS_PER_ASSIGNMENT = 500


def _assignments_file() -> Any:
    # Resolved per call so a monkey-patched SYSTEM_ROOT (tests) is honored,
    # the same way classes.py resolves its roster document.
    from deeptutor.multi_user import paths as mu_paths

    return mu_paths.SYSTEM_ROOT / "auth" / "assignments.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_assignment_id() -> str:
    return f"asg_{uuid4().hex}"


def read_assignments() -> dict[str, dict[str, Any]]:
    """Fail-open raw read of the assignment document (never creates it)."""
    path = _assignments_file()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Assignments: unreadable store %s: %s", path, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_assignments(assignments: dict[str, dict[str, Any]]) -> None:
    """Atomically replace the document (caller holds a coherent snapshot)."""
    path = _assignments_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(assignments, indent=2, ensure_ascii=False))


def get_assignment(assignment_id: str) -> dict[str, Any] | None:
    record = read_assignments().get(str(assignment_id or ""))
    return record if isinstance(record, dict) else None


def save_assignment(record: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace one assignment under its own id (idempotent upsert)."""
    assignment_id = str(record.get("assignment_id") or new_assignment_id())
    stored = dict(record, assignment_id=assignment_id)
    with _ASSIGNMENTS_WRITE_LOCK:
        assignments = read_assignments()
        assignments[assignment_id] = stored
        write_assignments(assignments)
    return stored


def add_submission(
    assignment_id: str,
    student_id: str,
    results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Record (or replace) one student's submission, last attempt wins.

    Returns the updated assignment, or ``None`` when the assignment vanished
    between the caller's read and this write.
    """
    student_id = str(student_id or "").strip()
    if not student_id:
        return None
    with _ASSIGNMENTS_WRITE_LOCK:
        assignments = read_assignments()
        record = assignments.get(str(assignment_id or ""))
        if not isinstance(record, dict):
            return None
        submissions = record.get("submissions")
        if not isinstance(submissions, dict):
            submissions = {}
        if student_id not in submissions and len(submissions) >= MAX_SUBMISSIONS_PER_ASSIGNMENT:
            raise ValueError("assignment submission budget exceeded")
        submissions[student_id] = {
            "submitted_at": utc_now_iso(),
            "results": list(results),
        }
        record["submissions"] = submissions
        assignments[record["assignment_id"]] = record
        write_assignments(assignments)
    return record
