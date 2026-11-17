"""Academic catalog: grades, tracks, majors, subjects and curriculum versions.

Why this is not a table of enums
--------------------------------
Phase 2 carried the learner's ``grade_level`` and ``curriculum`` as free text on
the profile. That works for one student and breaks for a product: "دهم" and
"10" and "پایه دهم" are three strings for one grade, and nothing can prove they
mean the same thing. Phase 4 replaces the free text with a resolved catalog
row, so scope checks become exact rather than best-effort.

The archive rule (D-007)
------------------------
The current system (1-12) and the archives (pre-university, retired systems)
live in the same tree, separated by ``curriculum_systems.status``. Two rules keep
them apart at runtime:

* :func:`resolve_enrolment` refuses an archived system outright -- a student
  cannot enrol into a retired curriculum by asking for it.
* :func:`list_grade_subjects` resolves through a system, so an archived system's
  subjects are reachable only by naming that system explicitly.

The second rule is the one that matters for correctness. A query that filters
"current only" by accident is a query that silently drops a historical student's
data; a query that requires an explicit system cannot do that by accident.

Enrolment rules (D-006)
-----------------------
Grades 1-9 have no track. From grade 10 a track/major choice is required. The
catalog encodes this as ``curriculum_grades.requires_track`` rather than a range
comparison in code, so a system that numbers its grades differently (the archive
does) cannot be misread as "grade >= 10".

Why the validators raise ``CatalogError`` rather than ``ValueError``
-------------------------------------------------------------------
``CatalogError`` carries the field and the offending value so the HTTP layer can
turn it into a 422 naming what was wrong. A bare ``ValueError`` loses that and
forces the router to guess.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from deeptutor.db.connection import Database, DatabaseError

logger = logging.getLogger(__name__)

#: The three stages of the current Iranian education system.
VALID_STAGES = frozenset({"elementary", "lower_secondary", "upper_secondary"})

#: Broad branch kinds. ``vocational`` (هنرستان) does not follow the
#: theoretical majors, which is why it is a kind rather than a fourth entry in
#: the theoretical list.
VALID_TRACK_KINDS = frozenset({"theoretical", "vocational"})

VALID_SYSTEM_STATUSES = frozenset({"current", "archived"})
VALID_VERSION_STATUSES = frozenset({"draft", "published", "retired"})
VALID_REQUIREMENTS = frozenset({"mandatory", "elective"})

#: New enrolments may only use a system in this status.
_ENROLLABLE = "current"


class CatalogError(RuntimeError):
    """A catalog rule was violated.

    A plain ``RuntimeError`` subclass rather than a frozen dataclass: CPython
    assigns ``__traceback__`` on raise, which a frozen dataclass forbids.

    Carries enough context for the HTTP layer to render a field-level 422.
    """

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


class CatalogNotFound(LookupError):
    """A catalog entity was named but does not exist."""

    def __init__(self, kind: str, identifier: Any) -> None:
        self.kind = kind
        self.identifier = identifier
        super().__init__(f"{kind} not found: {identifier!r}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: Any, field: str, *, max_length: int = 200) -> str:
    if value is None:
        raise CatalogError("required_field", "must not be empty", field=field)
    text = str(value).strip()
    if not text:
        raise CatalogError("required_field", "must not be empty", field=field)
    if len(text) > max_length:
        raise CatalogError(
            "field_too_long", f"must be at most {max_length} characters", field=field
        )
    return text


def parse_selectable_grades(raw: str) -> tuple[int, ...]:
    """Parse the denormalised ``'10,11,12'`` column into integers.

    Tolerant of spaces and empty entries because the column is written by
    importers, but strict about the values being integers: a non-integer here
    means the importer mangled the row, and silently dropping it would hide that.
    """
    if not raw:
        return ()
    grades: list[int] = []
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        try:
            grades.append(int(chunk))
        except ValueError as exc:
            raise CatalogError(
                "invalid_selectable_grades",
                f"not an integer: {chunk!r}",
                field="selectable_grades",
            ) from exc
    return tuple(sorted(set(grades)))


# ---------------------------------------------------------------------------
# Systems, grades
# ---------------------------------------------------------------------------


def create_system(
    db: Database,
    *,
    code: str,
    title: str,
    status: str = "current",
    effective_from_year: int | None = None,
    effective_to_year: int | None = None,
    sort_order: int = 0,
    system_id: str | None = None,
) -> str:
    """Register an education system (current or archived)."""
    code = _require_text(code, "code", max_length=60)
    title = _require_text(title, "title")
    if status not in VALID_SYSTEM_STATUSES:
        raise CatalogError(
            "invalid_status",
            f"must be one of {sorted(VALID_SYSTEM_STATUSES)}",
            field="status",
        )
    if (
        effective_from_year is not None
        and effective_to_year is not None
        and effective_to_year < effective_from_year
    ):
        raise CatalogError(
            "invalid_year_window",
            "effective_to_year precedes effective_from_year",
            field="effective_to_year",
        )
    identifier = system_id or f"sys_{code}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO curriculum_systems "
            "(id, code, title, status, effective_from_year, effective_to_year, "
            " sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                code,
                title,
                status,
                effective_from_year,
                effective_to_year,
                sort_order,
                _now(),
            ),
        )
    return identifier


def get_system(db: Database, code: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM curriculum_systems WHERE code = ?", (code,))
    if row is None:
        raise CatalogNotFound("system", code)
    return row


def list_systems(db: Database, *, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM curriculum_systems"
    params: list[Any] = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY sort_order, code"
    with db.read() as conn:
        return list(conn.query(sql, tuple(params)))


def add_grade(
    db: Database,
    *,
    system_code: str,
    grade_number: int,
    title: str,
    stage_code: str,
    requires_track: bool = False,
) -> str:
    """Add a grade to a system.

    ``stage_code`` is validated against :data:`VALID_STAGES` and against the
    grade number *within the current system only*: the archive numbers its
    grades differently, so imposing the current system's stage boundaries on it
    would reject valid historical data.
    """
    if not isinstance(grade_number, int) or isinstance(grade_number, bool):
        raise CatalogError("invalid_grade", "must be an integer", field="grade_number")
    if grade_number < 1 or grade_number > 20:
        raise CatalogError("invalid_grade", "must be between 1 and 20", field="grade_number")
    title = _require_text(title, "title")
    if stage_code not in VALID_STAGES:
        raise CatalogError(
            "invalid_stage",
            f"must be one of {sorted(VALID_STAGES)}",
            field="stage_code",
        )
    system = get_system(db, system_code)
    expected_stage = _stage_for_current_grade(grade_number)
    if system["status"] == _ENROLLABLE and expected_stage and stage_code != expected_stage:
        raise CatalogError(
            "stage_mismatch",
            f"grade {grade_number} belongs to {expected_stage}, not {stage_code}",
            field="stage_code",
        )
    identifier = f"grd_{system['id']}_{grade_number}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO curriculum_grades "
            "(id, system_id, grade_number, title, stage_code, requires_track) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                identifier,
                system["id"],
                grade_number,
                title,
                stage_code,
                1 if requires_track else 0,
            ),
        )
    return identifier


def _stage_for_current_grade(grade_number: int) -> str | None:
    """Stage of a grade in the *current* system, or ``None`` outside 1-12."""
    if 1 <= grade_number <= 6:
        return "elementary"
    if 7 <= grade_number <= 9:
        return "lower_secondary"
    if 10 <= grade_number <= 12:
        return "upper_secondary"
    return None


def list_grades(db: Database, system_code: str = "current") -> list[dict[str, Any]]:
    system = get_system(db, system_code)
    with db.read() as conn:
        return list(
            conn.query(
                "SELECT * FROM curriculum_grades WHERE system_id = ? ORDER BY grade_number",
                (system["id"],),
            )
        )


# ---------------------------------------------------------------------------
# Tracks and majors
# ---------------------------------------------------------------------------


def create_track(
    db: Database, *, code: str, title: str, kind: str = "theoretical", sort_order: int = 0
) -> str:
    code = _require_text(code, "code", max_length=60)
    title = _require_text(title, "title")
    if kind not in VALID_TRACK_KINDS:
        raise CatalogError(
            "invalid_track_kind",
            f"must be one of {sorted(VALID_TRACK_KINDS)}",
            field="kind",
        )
    identifier = f"trk_{code}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO curriculum_tracks (id, code, title, kind, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (identifier, code, title, kind, sort_order),
        )
    return identifier


def create_major(
    db: Database,
    *,
    track_code: str,
    code: str,
    title: str,
    selectable_grades: tuple[int, ...] = (),
    sort_order: int = 0,
) -> str:
    code = _require_text(code, "code", max_length=60)
    title = _require_text(title, "title")
    with db.read() as conn:
        track = conn.query_one("SELECT id FROM curriculum_tracks WHERE code = ?", (track_code,))
    if track is None:
        raise CatalogNotFound("track", track_code)
    for grade in selectable_grades:
        if not isinstance(grade, int) or isinstance(grade, bool) or grade < 1:
            raise CatalogError(
                "invalid_selectable_grades",
                f"not a positive integer: {grade!r}",
                field="selectable_grades",
            )
    identifier = f"maj_{code}"
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO curriculum_majors "
            "(id, track_id, code, title, selectable_grades, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                identifier,
                track["id"],
                code,
                title,
                ",".join(str(g) for g in selectable_grades),
                sort_order,
            ),
        )
    return identifier


def list_majors(
    db: Database, *, track_code: str | None = None, grade_number: int | None = None
) -> list[dict[str, Any]]:
    """Majors, optionally filtered to those selectable at a grade.

    The grade filter is applied in Python rather than SQL because
    ``selectable_grades`` is a denormalised list; a SQL ``LIKE`` on it would
    match grade 1 against '10,11,12'.
    """
    sql = (
        "SELECT m.*, t.code AS track_code, t.title AS track_title, t.kind AS track_kind "
        "FROM curriculum_majors m JOIN curriculum_tracks t ON t.id = m.track_id"
    )
    params: list[Any] = []
    if track_code is not None:
        sql += " WHERE t.code = ?"
        params.append(track_code)
    sql += " ORDER BY t.sort_order, m.sort_order, m.code"
    with db.read() as conn:
        rows = [dict(row) for row in conn.query(sql, tuple(params))]
    if grade_number is None:
        return rows
    return [
        row
        for row in rows
        if grade_number in parse_selectable_grades(row.get("selectable_grades") or "")
    ]


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


def create_subject(
    db: Database,
    *,
    code: str,
    title: str,
    grade_number: int,
    major_code: str | None = None,
    curriculum_version_id: str | None = None,
    language: str = "fa",
    requirement: str = "mandatory",
    weekly_hours: int | None = None,
    sort_order: int = 0,
) -> str:
    code = _require_text(code, "code", max_length=80)
    title = _require_text(title, "title")
    if not isinstance(grade_number, int) or isinstance(grade_number, bool):
        raise CatalogError("invalid_grade", "must be an integer", field="grade_number")
    if grade_number < 1 or grade_number > 20:
        raise CatalogError("invalid_grade", "must be between 1 and 20", field="grade_number")
    if requirement not in VALID_REQUIREMENTS:
        raise CatalogError(
            "invalid_requirement",
            f"must be one of {sorted(VALID_REQUIREMENTS)}",
            field="requirement",
        )
    if major_code is not None:
        with db.read() as conn:
            exists = conn.query_one(
                "SELECT 1 AS ok FROM curriculum_majors WHERE code = ?", (major_code,)
            )
        if exists is None:
            raise CatalogNotFound("major", major_code)
    identifier = f"sub_{grade_number}_{major_code or 'all'}_{code}"
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO curriculum_subjects "
                "(id, curriculum_version_id, grade_number, major_code, code, title, "
                " language, requirement, weekly_hours, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    curriculum_version_id,
                    grade_number,
                    major_code,
                    code,
                    title,
                    language,
                    requirement,
                    weekly_hours,
                    sort_order,
                ),
            )
    except DatabaseError as exc:
        # The unique constraint is the duplicate detector. Translating it here
        # keeps the message actionable instead of surfacing a driver error.
        raise CatalogError(
            "duplicate_subject",
            f"subject {code!r} already exists for grade {grade_number} and major {major_code!r}",
            field="code",
        ) from exc
    return identifier


def list_grade_subjects(
    db: Database,
    *,
    grade_number: int,
    major_code: str | None = None,
    system_code: str = "current",
) -> list[dict[str, Any]]:
    """Subjects available at a grade, optionally narrowed to a major.

    A subject with ``major_code IS NULL`` is available to every major, so it is
    always included. A subject tied to another major is excluded -- this is the
    scope boundary that Phase 5 relies on to prevent grade/track leakage.
    """
    get_system(db, system_code)  # validates the system exists
    with db.read() as conn:
        rows = conn.query(
            "SELECT * FROM curriculum_subjects WHERE grade_number = ? ORDER BY sort_order, code",
            (grade_number,),
        )
        subjects = [dict(row) for row in rows]
    if major_code is None:
        return subjects
    return [subject for subject in subjects if subject.get("major_code") in (None, "", major_code)]


# ---------------------------------------------------------------------------
# Curriculum versions
# ---------------------------------------------------------------------------


def create_version(
    db: Database,
    *,
    label: str,
    school_year: str,
    status: str = "draft",
    version_id: str | None = None,
) -> str:
    label = _require_text(label, "label")
    school_year = _require_text(school_year, "school_year", max_length=20)
    if status not in VALID_VERSION_STATUSES:
        raise CatalogError(
            "invalid_status",
            f"must be one of {sorted(VALID_VERSION_STATUSES)}",
            field="status",
        )
    identifier = version_id or f"ver_{school_year}_{label}"
    published_at = _now() if status == "published" else None
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO curriculum_versions "
                "(id, label, school_year, status, published_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, label, school_year, status, published_at, _now()),
            )
    except DatabaseError as exc:
        raise CatalogError(
            "duplicate_version",
            f"version {label!r} already exists for {school_year}",
            field="label",
        ) from exc
    return identifier


# ---------------------------------------------------------------------------
# Enrolment resolution
# ---------------------------------------------------------------------------


def resolve_enrolment(
    db: Database,
    *,
    grade_number: int,
    major_code: str | None = None,
    system_code: str = "current",
) -> dict[str, Any]:
    """Resolve a learner's grade and major into a catalog row.

    This is the function the profile and the retrieval scope both call, so the
    "is this combination valid" rule exists once.

    Refusals:

    * an archived system cannot accept a new enrolment (D-007);
    * a grade that requires a track must come with one, and a major must be
      selectable at that grade (D-006);
    * a major may not be supplied for a grade that has no track at all.
    """
    system = get_system(db, system_code)
    if system["status"] != _ENROLLABLE:
        raise CatalogError(
            "archived_system",
            f"system {system_code!r} is archived and cannot accept enrolments",
            field="system_code",
        )
    if not isinstance(grade_number, int) or isinstance(grade_number, bool):
        raise CatalogError("invalid_grade", "must be an integer", field="grade_number")
    with db.read() as conn:
        grade = conn.query_one(
            "SELECT * FROM curriculum_grades WHERE system_id = ? AND grade_number = ?",
            (system["id"], grade_number),
        )
    if grade is None:
        raise CatalogNotFound("grade", grade_number)
    requires_track = bool(grade["requires_track"])
    if requires_track and not major_code:
        raise CatalogError(
            "major_required",
            f"grade {grade_number} requires a track/major",
            field="major_code",
        )
    if not requires_track and major_code:
        raise CatalogError(
            "major_not_applicable",
            f"grade {grade_number} has no track, so a major cannot be chosen",
            field="major_code",
        )
    if major_code:
        candidates = list_majors(db, grade_number=grade_number)
        match = next((m for m in candidates if m["code"] == major_code), None)
        if match is None:
            raise CatalogError(
                "major_not_selectable",
                f"major {major_code!r} is not selectable at grade {grade_number}",
                field="major_code",
            )
        return {
            "system_code": system_code,
            "grade_number": grade_number,
            "stage_code": grade["stage_code"],
            "major_code": match["code"],
            "track_code": match["track_code"],
        }
    return {
        "system_code": system_code,
        "grade_number": grade_number,
        "stage_code": grade["stage_code"],
        "major_code": None,
        "track_code": None,
    }
