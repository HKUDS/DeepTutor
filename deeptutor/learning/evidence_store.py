"""SQLite-backed append-only store for learning evidence.

The mastery engine's decision side (``policy.py``) stays a pure function; this
module is the collection side's durable, queryable layer. ``LearningService``
writes one row per graded quiz / qualitative gate through the fail-open hooks
in ``service.py``; ``count_for_kp`` feeds the engine's "is there enough
evidence" checks.

Connection handling follows ``deeptutor.services.session.sqlite_store``
(one connection per operation) with WAL journaling and a busy timeout. The
table is append-only: rows are never updated or deleted.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from deeptutor.learning.models import LearningEvidence
from deeptutor.services.path_service import get_path_service

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    book_id TEXT NOT NULL DEFAULT '',
    kp_id TEXT NOT NULL DEFAULT '',
    question_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    evidence_type TEXT NOT NULL,
    is_correct INTEGER,
    passed INTEGER,
    cognitive_gate TEXT DEFAULT '',
    confidence_before INTEGER,
    confidence_after INTEGER,
    hint_level_reached INTEGER,
    error_type TEXT DEFAULT '',
    detail_json TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_evidence_user_time
    ON learning_evidence(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_kp
    ON learning_evidence(kp_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_book
    ON learning_evidence(book_id, created_at DESC);
"""


def _json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


class EvidenceStore:
    """Append-only SQLite persistence for learning evidence rows."""

    def __init__(self, db_path: Path | None = None) -> None:
        path_service = get_path_service()
        self.db_path = db_path or (path_service.user_data_dir / "learning_evidence.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def append(self, evidence: LearningEvidence) -> int:
        """Append one immutable evidence row; returns its row id."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO learning_evidence (
                    created_at, user_id, book_id, kp_id, question_id, session_id,
                    evidence_type, is_correct, passed, cognitive_gate,
                    confidence_before, confidence_after, hint_level_reached,
                    error_type, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.created_at,
                    evidence.user_id or "",
                    evidence.book_id or "",
                    evidence.kp_id or "",
                    evidence.question_id or "",
                    evidence.session_id or "",
                    evidence.evidence_type,
                    _bool_to_int(evidence.is_correct),
                    _bool_to_int(evidence.passed),
                    evidence.cognitive_gate or "",
                    evidence.confidence_before,
                    evidence.confidence_after,
                    evidence.hint_level_reached,
                    evidence.error_type or "",
                    json.dumps(evidence.detail_json or {}, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def query_evidence(
        self,
        user_id: str | None = None,
        kp_id: str | None = None,
        book_id: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[LearningEvidence]:
        """Return evidence rows newest-first, filtered by any provided
        criterion (``None`` means "no filter"). ``since`` keeps rows with
        ``created_at >= since``."""
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if kp_id is not None:
            clauses.append("kp_id = ?")
            params.append(kp_id)
        if book_id is not None:
            clauses.append("book_id = ?")
            params.append(book_id)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM learning_evidence{where} ORDER BY created_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    def count_for_kp(self, user_id: str, kp_id: str) -> int:
        """Count evidence rows for one user on one knowledge point."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM learning_evidence WHERE user_id = ? AND kp_id = ?",
                (user_id or "", kp_id or ""),
            ).fetchone()
            return int(row["n"])

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> LearningEvidence:
        detail = _json_loads(row["detail_json"], {})
        return LearningEvidence(
            id=row["id"],
            created_at=row["created_at"],
            user_id=row["user_id"] or "",
            book_id=row["book_id"] or "",
            kp_id=row["kp_id"] or "",
            question_id=row["question_id"] or "",
            session_id=row["session_id"] or "",
            evidence_type=row["evidence_type"],
            is_correct=_int_to_bool(row["is_correct"]),
            passed=_int_to_bool(row["passed"]),
            cognitive_gate=row["cognitive_gate"] or "",
            confidence_before=row["confidence_before"],
            confidence_after=row["confidence_after"],
            hint_level_reached=row["hint_level_reached"],
            error_type=row["error_type"] or "",
            detail_json=detail if isinstance(detail, dict) else {},
        )


__all__ = ["EvidenceStore"]
