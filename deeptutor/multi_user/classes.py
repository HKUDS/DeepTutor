"""Class rosters for the K12 layer — teacher-owned student groupings.

班级 = 老师账号名下的学生花名册。Stored as a dedicated JSON document next to
``users.json`` rather than as fields on account records, because
``identity.load_users`` canonicalizes (and rewrites) every record against a
strict whitelist — any extra field parked on a user record would be silently
stripped on the next write.

Cascade semantics (deliberately non-destructive):

* deleting a student account leaves a stale roster entry — reads skip it
  fail-open, mirroring the parent ``children`` linkage;
* deleting a teacher account orphans their classes — admins still see and
  manage them, other teachers never do (no automatic cascade deletes);
* deleting a class never touches user accounts.

Write paths validate the roster against live ``role=student`` accounts and
reject unknown names outright (a silently dropped typo would strand a real
student outside the class view); read paths re-verify and skip stale entries.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_text

from . import paths as mu_paths

logger = logging.getLogger(__name__)

#: Serialises read-modify-write cycles on the roster document, mirroring
#: ``identity._USERS_WRITE_LOCK`` for the same single-process reasoning.
_CLASSES_WRITE_LOCK = threading.Lock()

MAX_NAME_CHARS = 100
MAX_STUDENTS = 500
MAX_CLASSES_PER_TEACHER = 50


class ClassRosterError(ValueError):
    """Invalid class payload (bad name, oversized roster, unknown student)."""


class ClassNotFoundError(LookupError):
    """No class with the requested id."""


class ClassForbiddenError(PermissionError):
    """The caller does not own the class and is not an admin."""


def _classes_file() -> Any:
    # Resolved per call so a monkey-patched SYSTEM_ROOT (tests) is honored.
    return mu_paths.SYSTEM_ROOT / "auth" / "classes.json"


def _read_classes() -> dict[str, dict[str, Any]]:
    """Fail-open raw read of the roster document (never creates it)."""
    try:
        loaded = json.loads(_classes_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Class rosters: unreadable store %s: %s", _classes_file(), exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def read_user_store() -> dict[str, dict[str, Any]]:
    """Read the account store as JSON without writing anything.

    Prefers the canonical ``data/system/auth/users.json``; falls back to the
    legacy ``data/user/auth_users.json``. Malformed stores log and return
    empty — fail-open, never raising, and deliberately bypassing the
    canonicalizing loader so a read can never rewrite the store.
    """
    from .identity import LEGACY_USERS_FILE, USERS_FILE

    for path in (USERS_FILE, LEGACY_USERS_FILE):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Class rosters: unreadable user store %s: %s", path, exc)
            continue
        if isinstance(loaded, dict):
            return loaded
        logger.warning("Class rosters: user store %s is not a JSON object", path)
    return {}


def student_usernames(store: dict[str, Any]) -> set[str]:
    """Usernames of every live ``role=student`` account in the raw store."""
    return {
        str(username)
        for username, value in store.items()
        if isinstance(value, dict) and str(value.get("role") or "") == "student"
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_roster(students: Any) -> list[str]:
    """Strip/dedupe raw roster entries; raises when the shape is wrong."""
    if students is None:
        return []
    if not isinstance(students, list) or any(not isinstance(s, str) for s in students):
        raise ClassRosterError("students must be a list of usernames")
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in students:
        name = raw.strip()
        if name and name not in seen:
            seen.add(name)
            cleaned.append(name)
    if len(cleaned) > MAX_STUDENTS:
        raise ClassRosterError(f"roster exceeds the {MAX_STUDENTS}-student budget")
    return cleaned


def _validate_roster_live(cleaned: list[str], store: dict[str, Any]) -> None:
    """Reject roster entries that do not resolve to a live student account."""
    live = student_usernames(store)
    unknown = [name for name in cleaned if name not in live]
    if unknown:
        raise ClassRosterError(f"unknown or non-student accounts: {', '.join(unknown)}")


def get_class(class_id: str) -> dict[str, Any] | None:
    record = _read_classes().get(class_id)
    return record if isinstance(record, dict) else None


def list_classes(teacher: str | None = None) -> list[dict[str, Any]]:
    """All rosters, or only those owned by ``teacher`` when given.

    Sorted by creation time then id so the listing is stable across reads.
    """
    classes = [dict(record, id=cid) for cid, record in _read_classes().items() if isinstance(record, dict)]
    if teacher is not None:
        classes = [c for c in classes if str(c.get("teacher") or "") == teacher]
    classes.sort(key=lambda c: (str(c.get("created_at") or ""), str(c.get("id") or "")))
    return classes


def create_class(*, name: str, teacher: str, students: Any) -> dict[str, Any]:
    cleaned_name = str(name or "").strip()
    if not cleaned_name or len(cleaned_name) > MAX_NAME_CHARS:
        raise ClassRosterError(f"class name must be 1-{MAX_NAME_CHARS} characters")
    roster = _clean_roster(students)
    with _CLASSES_WRITE_LOCK:
        store = read_user_store()
        _validate_roster_live(roster, store)
        classes = _read_classes()
        owned = sum(
            1
            for record in classes.values()
            if isinstance(record, dict) and str(record.get("teacher") or "") == teacher
        )
        if owned >= MAX_CLASSES_PER_TEACHER:
            raise ClassRosterError(f"teacher already owns {MAX_CLASSES_PER_TEACHER} classes")
        record = {
            "name": cleaned_name,
            "teacher": teacher,
            "students": roster,
            "created_at": _utc_now(),
        }
        class_id = f"cls_{uuid4().hex}"
        classes[class_id] = record
        _write_classes(classes)
    logger.info("Class %s created for teacher %r (%d students)", class_id, teacher, len(roster))
    return dict(record, id=class_id)


def update_class(
    class_id: str,
    *,
    caller: str,
    is_admin: bool = False,
    name: str | None = None,
    students: Any = None,
) -> dict[str, Any]:
    with _CLASSES_WRITE_LOCK:
        classes = _read_classes()
        record = classes.get(class_id)
        if not isinstance(record, dict):
            raise ClassNotFoundError(class_id)
        if not is_admin and str(record.get("teacher") or "") != caller:
            raise ClassForbiddenError(class_id)
        if name is not None:
            cleaned_name = str(name).strip()
            if not cleaned_name or len(cleaned_name) > MAX_NAME_CHARS:
                raise ClassRosterError(f"class name must be 1-{MAX_NAME_CHARS} characters")
            record["name"] = cleaned_name
        if students is not None:
            roster = _clean_roster(students)
            _validate_roster_live(roster, read_user_store())
            record["students"] = roster
        classes[class_id] = record
        _write_classes(classes)
    return dict(record, id=class_id)


def delete_class(class_id: str, *, caller: str, is_admin: bool = False) -> None:
    """Remove the roster only — user accounts are never touched."""
    with _CLASSES_WRITE_LOCK:
        classes = _read_classes()
        record = classes.get(class_id)
        if not isinstance(record, dict):
            raise ClassNotFoundError(class_id)
        if not is_admin and str(record.get("teacher") or "") != caller:
            raise ClassForbiddenError(class_id)
        classes.pop(class_id, None)
        _write_classes(classes)
    logger.info("Class %s deleted by %r", class_id, caller)


def resolve_roster_live(class_record: dict[str, Any], store: dict[str, Any]) -> list[str]:
    """Roster entries that still resolve to live student accounts (fail-open).

    Read-time re-verification: an account deleted or re-roled after the class
    was saved is skipped rather than breaking the class view.
    """
    live = student_usernames(store)
    students = class_record.get("students")
    if not isinstance(students, list):
        return []
    return [str(name) for name in students if str(name) in live]


def _write_classes(classes: dict[str, dict[str, Any]]) -> None:
    path = _classes_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(classes, indent=2, ensure_ascii=False))
