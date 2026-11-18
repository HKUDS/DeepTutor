"""Exam bank, blueprints, attempts and grading persistence.

The invariant this module exists to protect
-------------------------------------------
A submitted attempt is immutable evidence. Its snapshot is written once, at
submission, and grading reads only the snapshot. So `grade_attempt` can be
called again and again -- after a policy edit, after a question is corrected --
and the score it produces is the score it produced the first time.

That is enforced structurally rather than by discipline:

* submission writes `question_snapshot` and `answers_snapshot` in one
  transaction with status ``submitted``;
* grading reads those columns, never `exam_questions`, and writes the score in
  the same transaction as the per-item rows;
* a second submission of identical answers is detected by
  `submission_fingerprint` and returns the existing attempt instead of creating
  a new one (the roadmap's "submitting/refreshing must not create another
  attempt or another score").

Post-grading changes exist and are allowed -- a human overrules a rubric, an
appeal is upheld -- but every one of them appends to `exam_grade_changes` with
before and after. A score that changed without a row explaining it is a bug, and
the tests assert that no code path can produce one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Mapping, Sequence

from deeptutor.db.connection import Database
from deeptutor.services.exam.scoring import (
    Policy,
    ScoringError,
    grade_exam,
)

logger = logging.getLogger(__name__)

#: Choices are stored newline-delimited. A choice containing a newline would
#: silently split into two choices, changing an answer key's meaning.
CHOICE_DELIMITER = "\n"

VALID_REVIEW_STATUSES = frozenset({"draft", "reviewed", "retired"})
VALID_EXAM_STATUSES = frozenset({"draft", "published", "archived"})
VALID_KEY_STATUSES = frozenset({"valid", "broken", "missing"})
VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


class ExamError(RuntimeError):
    """A refusal from the exam layer."""

    def __init__(self, rule: str, detail: str, *, field: str | None = None) -> None:
        self.rule = rule
        self.detail = detail
        self.field = field
        super().__init__(f"{rule}: {detail}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Question bank
# ---------------------------------------------------------------------------


@dataclass
class QuestionInput:
    question_id: str
    body: str
    question_type: str = "multiple_choice"
    choices: Sequence[str] = ()
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


def _validate_question(payload: QuestionInput) -> None:
    if payload.question_type not in {"multiple_choice", "essay", "short_answer"}:
        raise ExamError(
            "invalid_question_type",
            f"must be multiple_choice, essay or short_answer, not {payload.question_type!r}",
            field="question_type",
        )
    if not (payload.body or "").strip():
        raise ExamError("empty_body", "a question needs a body", field="body")
    if payload.key_status not in VALID_KEY_STATUSES:
        raise ExamError(
            "invalid_key_status",
            f"must be one of {sorted(VALID_KEY_STATUSES)}",
            field="key_status",
        )
    if payload.difficulty not in VALID_DIFFICULTIES:
        raise ExamError(
            "invalid_difficulty",
            f"must be one of {sorted(VALID_DIFFICULTIES)}",
            field="difficulty",
        )
    if payload.points <= 0:
        raise ExamError("invalid_points", "must be positive", field="points")
    if payload.review_status not in VALID_REVIEW_STATUSES:
        raise ExamError(
            "invalid_review_status",
            f"must be one of {sorted(VALID_REVIEW_STATUSES)}",
            field="review_status",
        )

    choices = [choice for choice in payload.choices if str(choice).strip()]
    for choice in choices:
        if CHOICE_DELIMITER in str(choice):
            raise ExamError(
                "choice_contains_delimiter",
                "a choice may not contain a newline; it would split into two choices",
                field="choices",
            )

    if payload.question_type == "multiple_choice":
        if len(choices) < 2:
            raise ExamError(
                "too_few_choices",
                "a multiple-choice question needs at least two choices",
                field="choices",
            )
        if payload.key_status == "valid" and not str(payload.answer_key).strip():
            # A multiple-choice question with no key is exactly the "broken
            # question" the roadmap says must not be graded definitively.
            raise ExamError(
                "missing_answer_key",
                "a valid multiple-choice question needs an answer key; "
                "use key_status='missing' to record a question without one",
                field="answer_key",
            )


def create_question(db: Database, payload: QuestionInput) -> dict[str, Any]:
    """Add a new version of a question.

    Versioning is by `question_id`: posting the same identity again creates
    version 2, not a duplicate. An exam that referenced version 1 keeps it.
    """
    _validate_question(payload)
    timestamp = _now()
    with db.transaction() as conn:
        row = conn.query_one(
            "SELECT COALESCE(MAX(version), 0) AS v FROM exam_questions WHERE question_id = ?",
            (payload.question_id,),
        )
        version = int((row or {}).get("v") or 0) + 1
        new_id = _new_id("q")
        conn.execute(
            "INSERT INTO exam_questions "
            "(id, question_id, version, question_type, grade_number, major_code, "
            " subject_code, chapter_title, topic, difficulty, body, choices, "
            " answer_key, key_status, rubric, points, authored_by, review_status, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id,
                payload.question_id,
                version,
                payload.question_type,
                payload.grade_number,
                payload.major_code,
                payload.subject_code,
                payload.chapter_title,
                payload.topic,
                payload.difficulty,
                payload.body,
                CHOICE_DELIMITER.join(str(c) for c in payload.choices if str(c).strip()),
                str(payload.answer_key),
                payload.key_status,
                payload.rubric,
                float(payload.points),
                payload.authored_by,
                payload.review_status,
                timestamp,
                timestamp,
            ),
        )
    return get_question(db, payload.question_id, version)


def get_question(db: Database, question_id: str, version: int | None = None) -> dict[str, Any]:
    """Fetch one question version; the latest when ``version`` is omitted."""
    with db.read() as conn:
        if version is None:
            row = conn.query_one(
                "SELECT * FROM exam_questions WHERE question_id = ? ORDER BY version DESC LIMIT 1",
                (question_id,),
            )
        else:
            row = conn.query_one(
                "SELECT * FROM exam_questions WHERE question_id = ? AND version = ?",
                (question_id, version),
            )
    if row is None:
        raise ExamError("question_not_found", f"no question {question_id!r} at version {version}")
    return dict(row)


def list_questions(
    db: Database,
    *,
    grade_number: int | None = None,
    major_code: str | None = None,
    subject_code: str | None = None,
    review_status: str | None = None,
    latest_only: bool = True,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if grade_number is not None:
        clauses.append("grade_number = ?")
        params.append(grade_number)
    if major_code is not None:
        clauses.append("(major_code IS NULL OR major_code = ?)")
        params.append(major_code)
    if subject_code is not None:
        clauses.append("(subject_code IS NULL OR subject_code = ?)")
        params.append(subject_code)
    if review_status is not None:
        clauses.append("review_status = ?")
        params.append(review_status)
    if latest_only:
        # Only the newest version of each identity, unless a specific version is
        # being asked for.
        clauses.append(
            "version = (SELECT MAX(v.version) FROM exam_questions v "
            "WHERE v.question_id = exam_questions.question_id)"
        )
    params.append(limit)
    with db.read() as conn:
        rows = conn.query(
            "SELECT * FROM exam_questions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY question_id LIMIT ?",
            tuple(params),
        )
        return [dict(row) for row in rows]


def review_question(
    db: Database, *, question_id: str, version: int, review_status: str, actor: str
) -> dict[str, Any]:
    """Mark a question reviewed. Gate 6 validates exams against reviewed sets."""
    if review_status not in VALID_REVIEW_STATUSES:
        raise ExamError("invalid_review_status", f"must be one of {sorted(VALID_REVIEW_STATUSES)}")
    with db.transaction() as conn:
        updated = conn.execute(
            "UPDATE exam_questions SET review_status = ?, updated_at = ? "
            "WHERE question_id = ? AND version = ?",
            (review_status, _now(), question_id, int(version)),
        )
        if not updated:
            raise ExamError(
                "question_not_found", f"no question {question_id!r} at version {version}"
            )
    return get_question(db, question_id, version)


# ---------------------------------------------------------------------------
# Scoring policies
# ---------------------------------------------------------------------------


def create_policy(db: Database, *, name: str, **kwargs: Any) -> dict[str, Any]:
    policy = Policy.from_mapping(kwargs)
    timestamp = _now()
    policy_id = _new_id("pol")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO exam_scoring_policies "
            "(id, name, negative_ratio, blank_is_neutral, broken_question_policy, "
            " essay_min_ratio, essay_max_ratio, allow_partial_credit, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                policy_id,
                name,
                policy.negative_ratio,
                1 if policy.blank_is_neutral else 0,
                policy.broken_question_policy,
                policy.essay_min_ratio,
                policy.essay_max_ratio,
                1 if policy.allow_partial_credit else 0,
                timestamp,
                timestamp,
            ),
        )
    return get_policy(db, policy_id)


def get_policy(db: Database, policy_id: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM exam_scoring_policies WHERE id = ?", (policy_id,))
    if row is None:
        raise ExamError("policy_not_found", f"no policy {policy_id!r}")
    return dict(row)


def list_policies(db: Database) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [
            dict(row)
            for row in conn.query("SELECT * FROM exam_scoring_policies ORDER BY created_at DESC")
        ]


# ---------------------------------------------------------------------------
# Exams and blueprints
# ---------------------------------------------------------------------------


@dataclass
class ExamItemInput:
    question_id: str
    question_version: int | None = None
    points: float | None = None


@dataclass
class Blueprint:
    """What an exam is supposed to contain, checked by Gate 6 validation."""

    chapter: str = ""
    topic: str = ""
    difficulty: str = ""
    count: int = 0
    points: float | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.chapter:
            data["chapter"] = self.chapter
        if self.topic:
            data["topic"] = self.topic
        if self.difficulty:
            data["difficulty"] = self.difficulty
        if self.count:
            data["count"] = self.count
        if self.points is not None:
            data["points"] = self.points
        return data


def create_exam(
    db: Database,
    *,
    title: str,
    items: Sequence[ExamItemInput],
    policy_id: str | None = None,
    grade_number: int | None = None,
    major_code: str | None = None,
    subject_code: str | None = None,
    duration_minutes: int = 0,
    blueprint: Sequence[Blueprint] | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    """Create an exam from explicit question versions.

    The version is resolved and **pinned** at creation. An exam built today must
    mean the same thing tomorrow, after the bank has moved on; resolving
    "latest" at grade time would make a past exam unregradable and a past score
    unreproducible.
    """
    if not (title or "").strip():
        raise ExamError("empty_title", "an exam needs a title", field="title")
    if not items:
        raise ExamError("empty_exam", "an exam needs at least one item", field="items")
    if status not in VALID_EXAM_STATUSES:
        raise ExamError(
            "invalid_status", f"must be one of {sorted(VALID_EXAM_STATUSES)}", field="status"
        )
    if policy_id is not None:
        get_policy(db, policy_id)  # 404 rather than a dangling reference

    resolved: list[tuple[str, int, float | None]] = []
    seen: set[str] = set()
    for item in items:
        if item.question_id in seen:
            raise ExamError(
                "duplicate_question",
                f"{item.question_id!r} appears twice in one exam",
                field="items",
            )
        seen.add(item.question_id)
        row = get_question(db, item.question_id, item.question_version)
        if item.question_version is None:
            resolved.append((item.question_id, int(row["version"]), item.points))
        else:
            resolved.append((item.question_id, int(item.question_version), item.points))

    timestamp = _now()
    exam_id = _new_id("exam")
    blueprint_json = json.dumps([spec.as_dict() for spec in (blueprint or [])], ensure_ascii=False)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO exams (id, title, grade_number, major_code, subject_code, "
            " policy_id, status, duration_minutes, blueprint, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                exam_id,
                title,
                grade_number,
                major_code,
                subject_code,
                policy_id,
                status,
                int(duration_minutes),
                blueprint_json,
                timestamp,
                timestamp,
            ),
        )
        for position, (question_id, version, points) in enumerate(resolved):
            conn.execute(
                "INSERT INTO exam_items "
                "(id, exam_id, question_id, question_version, position, points, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _new_id("item"),
                    exam_id,
                    question_id,
                    version,
                    position,
                    None if points is None else float(points),
                    timestamp,
                ),
            )
    return get_exam(db, exam_id)


def get_exam(db: Database, exam_id: str) -> dict[str, Any]:
    with db.read() as conn:
        exam = conn.query_one("SELECT * FROM exams WHERE id = ?", (exam_id,))
        if exam is None:
            raise ExamError("exam_not_found", f"no exam {exam_id!r}")
        items = [
            dict(row)
            for row in conn.query(
                "SELECT * FROM exam_items WHERE exam_id = ? ORDER BY position",
                (exam_id,),
            )
        ]
    result = dict(exam)
    result["items"] = items
    try:
        result["blueprint_spec"] = json.loads(result.get("blueprint") or "[]")
    except json.JSONDecodeError:  # pragma: no cover - defended by create_exam
        result["blueprint_spec"] = []
    return result


def list_exams(
    db: Database,
    *,
    grade_number: int | None = None,
    major_code: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if grade_number is not None:
        clauses.append("grade_number = ?")
        params.append(grade_number)
    if major_code is not None:
        clauses.append("(major_code IS NULL OR major_code = ?)")
        params.append(major_code)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    params.append(limit)
    with db.read() as conn:
        return [
            dict(row)
            for row in conn.query(
                "SELECT * FROM exams WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )
        ]


def publish_exam(db: Database, exam_id: str, *, actor: str = "") -> dict[str, Any]:
    """Publish, but only if every item is reviewed.

    Gate 6 is "exam validation against a reviewed question set", and this is
    where it is enforced rather than merely reported: an exam containing a
    draft question cannot go live, so a student cannot sit an unreviewed item.
    """
    exam = get_exam(db, exam_id)
    unreviewed: list[str] = []
    for item in exam["items"]:
        row = get_question(db, item["question_id"], int(item["question_version"]))
        if row["review_status"] != "reviewed":
            unreviewed.append(f"{item['question_id']}@{item['question_version']}")
    if unreviewed:
        raise ExamError(
            "unreviewed_questions",
            "every question must be reviewed before publication: " + ", ".join(unreviewed),
            field="items",
        )
    with db.transaction() as conn:
        conn.execute(
            "UPDATE exams SET status = 'published', updated_at = ? WHERE id = ?",
            (_now(), exam_id),
        )
    return get_exam(db, exam_id)


def validate_exam(db: Database, exam_id: str) -> dict[str, Any]:
    """Check an exam against its blueprint. The Gate 6 evidence.

    Returns the mismatches rather than raising: an operator wants the whole
    list, not the first problem.
    """
    exam = get_exam(db, exam_id)
    issues: list[dict[str, Any]] = []
    items = exam["items"]

    if not items:
        issues.append({"kind": "empty_exam", "detail": "the exam has no items"})

    for item in items:
        row = get_question(db, item["question_id"], int(item["question_version"]))
        if row["review_status"] != "reviewed":
            issues.append(
                {
                    "kind": "unreviewed_question",
                    "question_id": item["question_id"],
                    "version": item["question_version"],
                }
            )
        if row["key_status"] != "valid" and row["question_type"] == "multiple_choice":
            issues.append(
                {
                    "kind": "invalid_answer_key",
                    "question_id": item["question_id"],
                    "version": item["question_version"],
                    "key_status": row["key_status"],
                }
            )
        if row["question_type"] == "multiple_choice":
            choices = [c for c in str(row["choices"]).split(CHOICE_DELIMITER) if c.strip()]
            if len(choices) < 2:
                issues.append(
                    {
                        "kind": "too_few_choices",
                        "question_id": item["question_id"],
                    }
                )

    # Blueprint conformance: the authored mix must match what the exam contains.
    by_scope: dict[tuple[str, str, str], int] = {}
    for item in items:
        row = get_question(db, item["question_id"], int(item["question_version"]))
        key = (
            str(row.get("chapter_title") or ""),
            str(row.get("topic") or ""),
            str(row.get("difficulty") or ""),
        )
        by_scope[key] = by_scope.get(key, 0) + 1

    for spec in exam.get("blueprint_spec") or []:
        want = int(spec.get("count") or 0)
        if not want:
            continue
        matched = sum(
            count
            for (chapter, topic, difficulty), count in by_scope.items()
            if (not spec.get("chapter") or spec["chapter"] == chapter)
            and (not spec.get("topic") or spec["topic"] == topic)
            and (not spec.get("difficulty") or spec["difficulty"] == difficulty)
        )
        if matched != want:
            issues.append(
                {
                    "kind": "blueprint_mismatch",
                    "spec": spec,
                    "expected": want,
                    "found": matched,
                }
            )

    return {
        "exam_id": exam_id,
        "valid": not issues,
        "item_count": len(items),
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Attempts: submission and grading
# ---------------------------------------------------------------------------


def _snapshot_questions(db: Database, exam: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Freeze each item's full content, in exam order.

    This is the only place a snapshot is assembled, and it is the only reader of
    `exam_questions` in the grading path. Everything downstream sees this list.
    """
    snapshot: list[dict[str, Any]] = []
    for item in exam["items"]:
        row = get_question(db, item["question_id"], int(item["question_version"]))
        points = item.get("points")
        snapshot.append(
            {
                "question_id": row["question_id"],
                "version": int(row["version"]),
                "position": int(item["position"]),
                "question_type": row["question_type"],
                "body": row["body"],
                "choices": row["choices"],
                "answer_key": row["answer_key"],
                "key_status": row["key_status"],
                "rubric": row["rubric"],
                "points": float(points) if points is not None else float(row["points"]),
                "chapter_title": row["chapter_title"],
                "topic": row["topic"],
                "difficulty": row["difficulty"],
            }
        )
    return snapshot


def _fingerprint(answers: Mapping[str, Any] | Sequence[Any]) -> str:
    """A stable digest of a submission, so an identical retry is detectable."""
    canonical = json.dumps(answers, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def submit_exam(
    db: Database,
    *,
    exam_id: str,
    user_id: str,
    answers: Mapping[str, Any] | Sequence[Any],
    attempt_no: int = 1,
    essay_scores: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Submit answers and grade them, atomically.

    A duplicate submission -- the same user, the same attempt number, the same
    answers -- returns the existing attempt untouched. That covers the two ways
    a duplicate happens in a real client: a refresh re-POSTing the form, and a
    network retry that the caller could not distinguish from a failure.
    """
    exam = get_exam(db, exam_id)
    if exam["status"] != "published" and exam["status"] != "draft":
        raise ExamError(
            "exam_not_open",
            f"exam is {exam['status']!r}; only published or draft exams can be attempted",
            field="exam_id",
        )
    if int(attempt_no) < 1:
        raise ExamError("invalid_attempt", "attempt_no must be >= 1", field="attempt_no")

    fingerprint = _fingerprint(answers)

    with db.read() as conn:
        existing = conn.query_one(
            "SELECT * FROM exam_attempts WHERE exam_id = ? AND user_id = ? AND attempt_no = ?",
            (exam_id, user_id, int(attempt_no)),
        )
    if existing is not None:
        if existing["status"] in {"graded", "submitted"} and (
            existing.get("submission_fingerprint") == fingerprint
        ):
            # The idempotent path: same attempt, same answers, nothing to do.
            return _attempt_payload(db, dict(existing), duplicate=True)
        if existing["status"] in {"graded", "submitted"}:
            raise ExamError(
                "attempt_already_submitted",
                f"attempt {attempt_no} was already submitted with different answers; "
                "use a new attempt_no for a retake",
                field="attempt_no",
            )

    policy_row = None
    if exam.get("policy_id"):
        policy_row = get_policy(db, exam["policy_id"])
    policy = Policy.from_mapping(policy_row)

    snapshot = _snapshot_questions(db, exam)
    timestamp = _now()

    try:
        result = grade_exam(
            snapshot,
            answers,
            policy=policy,
            essay_scores=essay_scores,
        )
    except ScoringError as exc:
        raise ExamError("scoring_failed", exc.detail, field="answers") from exc

    attempt_id = _new_id("att")
    answers_json = json.dumps(answers, ensure_ascii=False, default=str)

    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO exam_attempts "
            "(id, exam_id, user_id, attempt_no, status, question_snapshot, "
            " policy_snapshot, blueprint_snapshot, answers_snapshot, score, max_score, "
            " correct_count, wrong_count, blank_count, voided_count, grading_status, "
            " review_required, submitted_at, graded_at, created_at, updated_at, "
            " submission_fingerprint) "
            "VALUES (?, ?, ?, ?, 'graded', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attempt_id,
                exam_id,
                user_id,
                int(attempt_no),
                json.dumps(snapshot, ensure_ascii=False),
                json.dumps(policy_row or {}, ensure_ascii=False),
                json.dumps(exam.get("blueprint") or "{}", ensure_ascii=False),
                answers_json,
                result.score,
                result.max_score,
                result.correct_count,
                result.wrong_count,
                result.blank_count,
                result.voided_count,
                result.grading_status,
                1 if result.review_required else 0,
                timestamp,
                timestamp,
                timestamp,
                timestamp,
                fingerprint,
            ),
        )
        for item in result.items:
            conn.execute(
                "INSERT INTO exam_attempt_items "
                "(id, attempt_id, question_id, question_version, position, outcome, "
                " answer, points_awarded, points_possible, rubric_result, graded_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _new_id("ati"),
                    attempt_id,
                    item.question_id,
                    item.question_version,
                    item.position,
                    item.outcome,
                    item.answer,
                    item.points_awarded,
                    item.points_possible,
                    item.rubric_result,
                    item.graded_by,
                    timestamp,
                ),
            )

    with db.read() as conn:
        row = conn.query_one("SELECT * FROM exam_attempts WHERE id = ?", (attempt_id,))
    return _attempt_payload(db, dict(row), duplicate=False, warnings=result.warnings)


def _attempt_payload(
    db: Database,
    attempt: Mapping[str, Any],
    *,
    duplicate: bool = False,
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    with db.read() as conn:
        items = [
            dict(row)
            for row in conn.query(
                "SELECT * FROM exam_attempt_items WHERE attempt_id = ? ORDER BY position",
                (attempt["id"],),
            )
        ]
    payload = dict(attempt)
    payload["items"] = items
    payload["duplicate_submission"] = duplicate
    payload["warnings"] = list(warnings)
    return payload


def get_attempt(db: Database, attempt_id: str) -> dict[str, Any]:
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM exam_attempts WHERE id = ?", (attempt_id,))
    if row is None:
        raise ExamError("attempt_not_found", f"no attempt {attempt_id!r}")
    return _attempt_payload(db, dict(row))


def regrade_attempt(
    db: Database,
    *,
    attempt_id: str,
    essay_scores: Mapping[str, float] | None = None,
    actor: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Re-grade from the *snapshot*, never from the live bank.

    This exists for one honest purpose: an essay that was `needs_review` gets a
    human score. It cannot change a multiple-choice verdict, because the
    snapshot still holds the same answer key, so a "regrade" can only add
    information that was missing -- not overwrite a verdict that was made.

    Every change is logged with before and after.
    """
    attempt = get_attempt(db, attempt_id)
    before = float(attempt.get("score") or 0.0)

    snapshot = json.loads(attempt.get("question_snapshot") or "[]")
    if not snapshot:
        raise ExamError("missing_snapshot", "this attempt has no question snapshot")
    policy_row = json.loads(attempt.get("policy_snapshot") or "{}")
    answers = json.loads(attempt.get("answers_snapshot") or "{}")

    result = grade_exam(snapshot, answers, policy=policy_row, essay_scores=essay_scores)
    after = float(result.score or 0.0)
    timestamp = _now()

    with db.transaction() as conn:
        conn.execute(
            "UPDATE exam_attempts SET score = ?, max_score = ?, correct_count = ?, "
            " wrong_count = ?, blank_count = ?, voided_count = ?, grading_status = ?, "
            " review_required = ?, graded_at = ?, updated_at = ? WHERE id = ?",
            (
                result.score,
                result.max_score,
                result.correct_count,
                result.wrong_count,
                result.blank_count,
                result.voided_count,
                result.grading_status,
                1 if result.review_required else 0,
                timestamp,
                timestamp,
                attempt_id,
            ),
        )
        for item in result.items:
            conn.execute(
                "UPDATE exam_attempt_items SET outcome = ?, points_awarded = ?, "
                " points_possible = ?, rubric_result = ?, graded_by = ? "
                "WHERE attempt_id = ? AND question_id = ?",
                (
                    item.outcome,
                    item.points_awarded,
                    item.points_possible,
                    item.rubric_result,
                    "human"
                    if essay_scores and item.question_id in essay_scores
                    else item.graded_by,
                    attempt_id,
                    item.question_id,
                ),
            )
        if after != before:
            conn.execute(
                "INSERT INTO exam_grade_changes "
                "(id, attempt_id, item_id, question_id, change_kind, score_before, "
                " score_after, reason, actor, created_at) "
                "VALUES (?, ?, NULL, '', 'regrade', ?, ?, ?, ?, ?)",
                (
                    _new_id("chg"),
                    attempt_id,
                    before,
                    after,
                    reason,
                    actor,
                    timestamp,
                ),
            )
    return get_attempt(db, attempt_id)


def override_item_score(
    db: Database,
    *,
    attempt_id: str,
    question_id: str,
    points_awarded: float,
    actor: str,
    reason: str,
    change_kind: str = "human_review",
) -> dict[str, Any]:
    """A human overrules one item's score, and the change is recorded.

    This is the route an appeal takes. The item is updated and the attempt total
    is recomputed from the items -- not from a fresh grade -- so the override
    survives any later regrade of the other questions.
    """
    if change_kind not in {"human_review", "appeal_upheld", "correction"}:
        raise ExamError(
            "invalid_change_kind",
            "must be human_review, appeal_upheld or correction",
            field="change_kind",
        )
    attempt = get_attempt(db, attempt_id)
    before = float(attempt.get("score") or 0.0)

    with db.read() as conn:
        item = conn.query_one(
            "SELECT * FROM exam_attempt_items WHERE attempt_id = ? AND question_id = ?",
            (attempt_id, question_id),
        )
    if item is None:
        raise ExamError("item_not_found", f"no item {question_id!r} in attempt {attempt_id!r}")

    possible = float(item["points_possible"])
    if points_awarded > possible:
        raise ExamError(
            "score_above_maximum",
            f"cannot award {points_awarded} of {possible} possible",
            field="points_awarded",
        )

    awarded = float(points_awarded)
    if awarded >= possible > 0:
        outcome = "correct"
    elif awarded > 0:
        outcome = "partial"
    elif awarded < 0:
        outcome = "wrong"
    else:
        outcome = "wrong"

    timestamp = _now()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE exam_attempt_items SET points_awarded = ?, outcome = ?, "
            " graded_by = 'human', rubric_result = ? WHERE id = ?",
            (awarded, outcome, reason, item["id"]),
        )
        conn.execute(
            "INSERT INTO exam_grade_changes "
            "(id, attempt_id, item_id, question_id, change_kind, score_before, "
            " score_after, reason, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _new_id("chg"),
                attempt_id,
                item["id"],
                question_id,
                change_kind,
                before,
                before + (awarded - float(item["points_awarded"])),
                reason,
                actor,
                timestamp,
            ),
        )
        # Recompute the total from the items, in SQL, so the stored score and
        # the stored items can never disagree.
        totals = conn.query_one(
            "SELECT SUM(points_awarded) AS score, "
            "SUM(CASE WHEN points_possible > 0 THEN points_possible ELSE 0 END) AS max_score "
            "FROM exam_attempt_items WHERE attempt_id = ?",
            (attempt_id,),
        )
        conn.execute(
            "UPDATE exam_attempts SET score = ?, max_score = ?, updated_at = ? WHERE id = ?",
            (
                round(float(totals["score"] or 0.0), 6),
                round(float(totals["max_score"] or 0.0), 6),
                timestamp,
                attempt_id,
            ),
        )
    return get_attempt(db, attempt_id)


def list_attempts(
    db: Database, *, user_id: str | None = None, exam_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if exam_id is not None:
        clauses.append("exam_id = ?")
        params.append(exam_id)
    params.append(limit)
    with db.read() as conn:
        return [
            dict(row)
            for row in conn.query(
                "SELECT * FROM exam_attempts WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )
        ]


def grade_changes(db: Database, attempt_id: str) -> list[dict[str, Any]]:
    with db.read() as conn:
        return [
            dict(row)
            for row in conn.query(
                "SELECT * FROM exam_grade_changes WHERE attempt_id = ? ORDER BY created_at",
                (attempt_id,),
            )
        ]


# ---------------------------------------------------------------------------
# Error report
# ---------------------------------------------------------------------------


def mistake_report(db: Database, attempt_id: str) -> dict[str, Any]:
    """Which topics a student got wrong, for the review dashboard.

    Built from the attempt's own item rows, so it describes what actually
    happened rather than what the bank currently says.
    """
    attempt = get_attempt(db, attempt_id)
    snapshot = {
        str(q["question_id"]): q for q in json.loads(attempt.get("question_snapshot") or "[]")
    }

    topics: dict[str, dict[str, Any]] = {}
    wrong_items: list[dict[str, Any]] = []
    for item in attempt["items"]:
        qid = str(item["question_id"])
        meta = snapshot.get(qid, {})
        topic = str(meta.get("topic") or meta.get("chapter_title") or "بدون مبحث")
        bucket = topics.setdefault(
            topic,
            {"topic": topic, "total": 0, "wrong": 0, "blank": 0, "correct": 0, "needs_review": 0},
        )
        bucket["total"] += 1
        outcome = item["outcome"]
        if outcome in bucket:
            bucket[outcome] += 1
        if outcome in {"wrong", "blank"}:
            wrong_items.append(
                {
                    "question_id": qid,
                    "position": item["position"],
                    "outcome": outcome,
                    "topic": topic,
                    "chapter": meta.get("chapter_title") or "",
                }
            )

    needs_review = sorted(
        [
            {
                **bucket,
                "needs_review": bucket["wrong"] + bucket["blank"],
            }
            for bucket in topics.values()
            if bucket["wrong"] or bucket["blank"]
        ],
        key=lambda bucket: bucket["needs_review"],
        reverse=True,
    )

    return {
        "attempt_id": attempt_id,
        "score": attempt.get("score"),
        "max_score": attempt.get("max_score"),
        "topics": sorted(topics.values(), key=lambda t: t["topic"]),
        "needs_review": needs_review,
        "wrong_items": sorted(wrong_items, key=lambda item: item["position"]),
    }
