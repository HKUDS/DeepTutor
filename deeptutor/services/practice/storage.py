"""Transactional review history and import staging in the user's notebook DB."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .scheduler import DAY, Rating, day_bounds, schedule

# Legacy correct or manually mastered questions start with a three-day interval.
# Once reviewed, the saved adaptive schedule is authoritative.
_DUE_AT_SQL = """(CASE WHEN (n.resolved=1 OR n.is_correct=1)
    AND COALESCE(r.review_count, 0)=0 THEN n.updated_at + 259200
    ELSE COALESCE(r.due_at, n.created_at) END)"""


class ReviewConflict(ValueError):
    """A different tab or source changed this question since it was opened."""


def initialize_practice(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='practice_review_state'"
    ).fetchone()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS practice_review_state (
            entry_id INTEGER PRIMARY KEY REFERENCES notebook_entries(id) ON DELETE CASCADE,
            is_mistake INTEGER NOT NULL DEFAULT 1,
            first_wrong_at REAL NOT NULL,
            due_at REAL NOT NULL,
            interval_days REAL NOT NULL DEFAULT 1,
            ease REAL NOT NULL DEFAULT 2.5,
            streak INTEGER NOT NULL DEFAULT 0,
            lapses INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            last_review_at REAL,
            version INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_practice_due ON practice_review_state(due_at, entry_id);
        CREATE TABLE IF NOT EXISTS practice_review_events (
            request_id TEXT PRIMARY KEY,
            entry_id INTEGER NOT NULL REFERENCES notebook_entries(id) ON DELETE CASCADE,
            rating TEXT NOT NULL,
            answer TEXT NOT NULL,
            reviewed_at REAL NOT NULL,
            outcome_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_practice_history ON practice_review_events(entry_id, reviewed_at);
        CREATE TABLE IF NOT EXISTS practice_imports (
            token TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            target TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            result_json TEXT
        );
        CREATE TRIGGER IF NOT EXISTS practice_capture_insert
        AFTER INSERT ON notebook_entries
        WHEN NEW.is_correct = 0 AND COALESCE(NEW.result, '') != 'ungraded'
        BEGIN
            INSERT INTO practice_review_state(entry_id, first_wrong_at, due_at)
            SELECT NEW.id, NEW.created_at, NEW.created_at + 86400
            WHERE NOT EXISTS(SELECT 1 FROM practice_review_state WHERE entry_id=NEW.id);
        END;
        CREATE TRIGGER IF NOT EXISTS practice_invalidate_question
        AFTER UPDATE OF question, options_json, correct_answer ON notebook_entries
        WHEN OLD.question != NEW.question OR OLD.options_json != NEW.options_json OR OLD.correct_answer != NEW.correct_answer
        BEGIN
            UPDATE practice_review_state SET version=version+1 WHERE entry_id=NEW.id;
        END;
        DROP TRIGGER IF EXISTS practice_capture_update;
        CREATE TRIGGER practice_capture_update
        AFTER UPDATE OF is_correct, result ON notebook_entries
        WHEN NEW.is_correct = 0 AND COALESCE(NEW.result, '') != 'ungraded'
        BEGIN
            INSERT INTO practice_review_state(entry_id, first_wrong_at, due_at)
            SELECT NEW.id, NEW.updated_at, NEW.updated_at + 86400
            WHERE NOT EXISTS(SELECT 1 FROM practice_review_state WHERE entry_id=NEW.id);
            UPDATE practice_review_state SET
                first_wrong_at = CASE WHEN is_mistake=0 THEN NEW.updated_at ELSE first_wrong_at END,
                is_mistake = 1,
                due_at = NEW.updated_at + 86400, interval_days = 1, streak = 0,
                version = version + 1
            WHERE entry_id = NEW.id AND (OLD.is_correct = 1 OR OLD.result = 'ungraded');
        END;
    """)
    if not existing:
        # Additive migration: original IDs, answers, timestamps and categories stay intact.
        conn.execute("""
            INSERT OR IGNORE INTO practice_review_state(entry_id, first_wrong_at, due_at)
            SELECT id, created_at, created_at + 86400 FROM notebook_entries
            WHERE is_correct = 0 AND COALESCE(result, '') != 'ungraded'
        """)


class PracticeStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _scope(session_ids: list[str] | None) -> tuple[str, list]:
        # Independent imports/document questions have no chat to delete. They
        # stay visible in the global bank, while an explicit course/session
        # scope continues to select conversation-backed entries only.
        sql = "(n.session_id IS NULL OR s.deleted_at IS NULL)"
        params: list = []
        if session_ids is not None:
            sql += " AND n.session_id IN (" + (",".join("?" for _ in session_ids) or "NULL") + ")"
            params.extend(session_ids)
        return sql, params

    def overview(
        self, timezone: str, session_ids: list[str] | None = None, now: float | None = None
    ) -> dict:
        now = time.time() if now is None else now
        start, end = day_bounds(timezone, now)
        scope, params = self._scope(session_ids)
        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS total,
                    COALESCE(SUM(r.is_mistake = 1), 0) AS mistakes,
                    COALESCE(SUM({_DUE_AT_SQL} <= ?), 0) AS due,
                    COALESCE(SUM({_DUE_AT_SQL} <= ?), 0) AS overdue,
                    MIN({_DUE_AT_SQL}) AS next_due_at
                FROM notebook_entries n LEFT JOIN sessions s ON s.id = n.session_id
                LEFT JOIN practice_review_state r ON r.entry_id = n.id WHERE {scope}
            """,  # nosec B608 - fixed scope SQL; values bound
                [now, start, *params],
            ).fetchone()  # nosec B608 - bound scope values
            completed = conn.execute(
                f"""
                SELECT COUNT(DISTINCT e.entry_id) FROM practice_review_events e
                JOIN notebook_entries n ON n.id = e.entry_id LEFT JOIN sessions s ON s.id = n.session_id
                WHERE e.reviewed_at >= ? AND e.reviewed_at < ? AND {scope}
            """,  # nosec B608 - fixed scope SQL; values bound
                [start, end, *params],
            ).fetchone()[0]  # nosec B608
        return {**dict(row), "reviewed_today": completed, "day_end": end, "timezone": timezone}

    def analytics(
        self,
        timezone: str,
        days: int = 30,
        session_ids: list[str] | None = None,
        now: float | None = None,
    ) -> dict:
        from .analytics import analytics

        scope, params = self._scope(session_ids)
        with self.connect() as conn:
            return analytics(
                conn, timezone, days, time.time() if now is None else now, scope, params
            )

    def queue(
        self,
        timezone: str,
        session_ids: list[str] | None = None,
        category_id: int | None = None,
        limit: int = 20,
        now: float | None = None,
    ) -> list[int]:
        now = time.time() if now is None else now
        day_bounds(timezone, now)
        scope, params = self._scope(session_ids)
        if category_id is not None:
            scope += " AND EXISTS(SELECT 1 FROM notebook_entry_categories c WHERE c.entry_id=n.id AND c.category_id=?)"
            params.append(category_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT n.id FROM notebook_entries n LEFT JOIN sessions s ON s.id=n.session_id
                LEFT JOIN practice_review_state r ON r.entry_id=n.id
                WHERE {_DUE_AT_SQL} <= ? AND {scope}
                ORDER BY {_DUE_AT_SQL}, n.id LIMIT ?
            """,  # nosec B608 - fixed scope SQL; values bound
                [now, *params, limit],
            ).fetchall()  # nosec B608
        return [row["id"] for row in rows]

    def state(self, entry_id: int) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM practice_review_state WHERE entry_id=?", (entry_id,)
            ).fetchone()
        return (
            dict(row)
            if row
            else {
                "entry_id": entry_id,
                "is_mistake": 0,
                "version": 0,
                "review_count": 0,
                "interval_days": 1,
                "due_at": None,
            }
        )

    def is_visible(self, entry_id: int) -> bool:
        with self.connect() as conn:
            return (
                conn.execute(
                    """SELECT 1 FROM notebook_entries n LEFT JOIN sessions s ON s.id=n.session_id
                WHERE n.id=? AND (n.session_id IS NULL OR s.deleted_at IS NULL)""",
                    (entry_id,),
                ).fetchone()
                is not None
            )

    def review(
        self,
        entry_id: int,
        request_id: str,
        version: int,
        rating: Rating,
        answer: str,
        now: float | None = None,
        *,
        self_report: bool = False,
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT * FROM practice_review_events WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if (
                    previous["entry_id"] != entry_id
                    or previous["rating"] != rating
                    or previous["answer"] != answer
                    or bool(json.loads(previous["outcome_json"]).get("self_report")) != self_report
                ):
                    raise ReviewConflict(
                        "This submission ID was already used for a different answer"
                    )
                return json.loads(previous["outcome_json"])
            entry = conn.execute(
                """SELECT n.* FROM notebook_entries n LEFT JOIN sessions s ON s.id=n.session_id
                WHERE n.id=? AND (n.session_id IS NULL OR s.deleted_at IS NULL)""",
                (entry_id,),
            ).fetchone()
            if not entry:
                raise LookupError("Question not found")
            row = conn.execute(
                "SELECT * FROM practice_review_state WHERE entry_id=?", (entry_id,)
            ).fetchone()
            state = dict(row) if row else {"version": 0}
            if state["version"] != version:
                raise ReviewConflict(
                    "This question changed in another tab. Reload it before reviewing again."
                )
            # Objective answers are checked again at the transaction boundary.
            from .answers import check_answer

            correct = None if self_report else check_answer(dict(entry), answer)
            if correct is False and rating != "again":
                raise ValueError("An incorrect answer must be reviewed again")
            next_state = schedule(state, rating, now)
            mistake = bool(state.get("is_mistake")) or rating == "again"
            conn.execute(
                """
                INSERT INTO practice_review_state(entry_id, is_mistake, first_wrong_at, due_at,
                    interval_days, ease, streak, lapses, review_count, last_review_at, version)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET is_mistake=excluded.is_mistake, due_at=excluded.due_at,
                    first_wrong_at=CASE WHEN practice_review_state.is_mistake=0 AND excluded.is_mistake=1
                        THEN excluded.first_wrong_at ELSE practice_review_state.first_wrong_at END,
                    interval_days=excluded.interval_days, ease=excluded.ease, streak=excluded.streak,
                    lapses=excluded.lapses, review_count=excluded.review_count,
                    last_review_at=excluded.last_review_at, version=excluded.version
            """,
                (
                    entry_id,
                    int(mistake),
                    now,
                    *(
                        next_state[key]
                        for key in (
                            "due_at",
                            "interval_days",
                            "ease",
                            "streak",
                            "lapses",
                            "review_count",
                            "last_review_at",
                            "version",
                        )
                    ),
                ),
            )
            if rating == "again":
                conn.execute("UPDATE notebook_entries SET resolved=0 WHERE id=?", (entry_id,))
            outcome = {
                **next_state,
                "entry_id": entry_id,
                "is_mistake": mistake,
                "correct": correct,
                "rating": rating,
                "self_report": self_report,
                "mastered": rating in {"good", "easy"},
            }
            conn.execute(
                "INSERT INTO practice_review_events VALUES(?, ?, ?, ?, ?, ?)",
                (request_id, entry_id, rating, answer, now, json.dumps(outcome)),
            )
        return outcome

    def stage_import(
        self, filename: str, target: str, questions: list[dict], course_id: str = ""
    ) -> str:
        token, now = uuid.uuid4().hex, time.time()
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM practice_imports WHERE created_at < ? AND result_json IS NULL",
                (now - DAY,),
            )
            conn.execute(
                "INSERT INTO practice_imports VALUES(?, ?, ?, ?, ?, NULL)",
                (
                    token,
                    filename[:200],
                    target,
                    json.dumps(
                        {"questions": questions, "course_id": course_id}, ensure_ascii=False
                    ),
                    now,
                ),
            )
        return token

    def commit_import(self, token: str) -> dict:
        now = time.time()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            staged = conn.execute(
                "SELECT * FROM practice_imports WHERE token=?", (token,)
            ).fetchone()
            if not staged:
                raise LookupError("Import preview not found. Select the file again.")
            if staged["result_json"]:
                return json.loads(staged["result_json"])
            if now - staged["created_at"] > DAY:
                raise ValueError("Import preview expired. Select the file again.")
            payload = json.loads(staged["payload_json"])
            questions = payload if isinstance(payload, list) else payload["questions"]
            # All practice-file imports share one durable origin namespace.
            # ``question_id`` is a content hash, so re-importing the same
            # question remains idempotent without tying ownership to an
            # ephemeral preview receipt or a synthetic chat session.
            origin_ref = "practice-import"
            created, skipped = 0, 0
            for question in questions:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO notebook_entries(
                        session_id, origin_type, origin_ref, question_id, question, question_type,
                        options_json, correct_answer, explanation, difficulty, user_answer, source,
                        result, assessment_type, created_at, updated_at, material_title, material_id)
                    VALUES(NULL, 'external_import', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'import', ?, 'quiz', ?, ?, ?, ?)
                """,
                    (
                        origin_ref,
                        question["question_id"],
                        question["question"],
                        question["question_type"],
                        json.dumps(question["options"], ensure_ascii=False),
                        question["correct_answer"],
                        question["explanation"],
                        question["difficulty"],
                        question["user_answer"],
                        "incorrect" if staged["target"] == "mistakes" else "ungraded",
                        now,
                        now,
                        staged["filename"],
                        "import:" + token,
                    ),
                )
                created += cursor.rowcount
                skipped += 1 - cursor.rowcount
                entry_id = conn.execute(
                    """SELECT id FROM notebook_entries
                    WHERE origin_type='external_import' AND origin_ref=?
                      AND question_id=? AND turn_id=''""",
                    (origin_ref, question["question_id"]),
                ).fetchone()[0]
                if staged["target"] == "mistakes":
                    conn.execute(
                        "INSERT OR IGNORE INTO practice_review_state(entry_id, first_wrong_at, due_at) VALUES(?, ?, ?)",
                        (entry_id, now, now + DAY),
                    )
                    conn.execute(
                        """UPDATE practice_review_state SET is_mistake=1, first_wrong_at=?,
                            due_at=?, interval_days=1, version=version+1
                            WHERE entry_id=? AND is_mistake=0""",
                        (now, now + DAY, entry_id),
                    )
                for tag in question["tags"]:
                    conn.execute(
                        "INSERT OR IGNORE INTO notebook_categories(name, created_at) VALUES(?, ?)",
                        (tag, now),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO notebook_entry_categories(entry_id, category_id) SELECT ?, id FROM notebook_categories WHERE name=?",
                        (entry_id, tag),
                    )
            result = {"created": created, "duplicates": skipped, "total": created + skipped}
            conn.execute(
                "UPDATE practice_imports SET result_json=?, payload_json='[]' WHERE token=?",
                (json.dumps(result), token),
            )
        return result
