"""Durable scheduling state for web-source synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
from typing import Any


@dataclass(slots=True)
class WebSourceSyncJob:
    """One durable row per account-scoped knowledge-base source."""

    owner_id: str
    kb_name: str
    source_id: str
    next_run_at_ms: int
    updated_at_ms: int
    state: str = "pending"
    last_run_at_ms: int | None = None
    attempt: int = 0
    error: str | None = None
    cancel_requested: bool = False
    runner_id: str = ""
    lease_until_ms: int | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "WebSourceSyncJob":
        return cls(
            owner_id=str(row["owner_id"]),
            kb_name=str(row["kb_name"]),
            source_id=str(row["source_id"]),
            state=str(row["state"]),
            next_run_at_ms=int(row["next_run_at_ms"]),
            last_run_at_ms=(
                int(row["last_run_at_ms"]) if row["last_run_at_ms"] is not None else None
            ),
            attempt=int(row["attempt"]),
            error=str(row["error"]) if row["error"] is not None else None,
            cancel_requested=bool(row["cancel_requested"]),
            runner_id=str(row["runner_id"]),
            lease_until_ms=(
                int(row["lease_until_ms"]) if row["lease_until_ms"] is not None else None
            ),
            updated_at_ms=int(row["updated_at_ms"]),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "kb_name": self.kb_name,
            "source_id": self.source_id,
            "state": self.state,
            "next_run_at": self.next_run_at_ms,
            "last_run_at": self.last_run_at_ms,
            "attempt": self.attempt,
            "error": self.error,
            "cancel_requested": self.cancel_requested,
        }


class SQLiteWebSourceSyncRepository:
    """WAL-backed job state shared by API requests and the scheduler."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS web_source_sync_jobs (
                    owner_id TEXT NOT NULL,
                    kb_name TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    next_run_at_ms INTEGER NOT NULL,
                    last_run_at_ms INTEGER,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    runner_id TEXT NOT NULL DEFAULT '',
                    lease_until_ms INTEGER,
                    updated_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (owner_id, kb_name, source_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_web_source_sync_due "
                "ON web_source_sync_jobs(next_run_at_ms, state)"
            )

    @staticmethod
    def key(job: WebSourceSyncJob) -> tuple[str, str, str]:
        return job.owner_id, job.kb_name, job.source_id

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def reconcile_sources(self, source_keys: set[tuple[str, str, str]]) -> None:
        """Create missing rows and remove jobs whose source no longer exists."""
        now = self._now_ms()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    "SELECT owner_id, kb_name, source_id FROM web_source_sync_jobs"
                ).fetchall()
                existing = {
                    (str(row["owner_id"]), str(row["kb_name"]), str(row["source_id"]))
                    for row in rows
                }
                for owner_id, kb_name, source_id in source_keys - existing:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO web_source_sync_jobs
                            (owner_id, kb_name, source_id, state, next_run_at_ms,
                             updated_at_ms)
                        VALUES (?, ?, ?, 'pending', ?, ?)
                        """,
                        (owner_id, kb_name, source_id, now, now),
                    )
                for owner_id, kb_name, source_id in existing - source_keys:
                    connection.execute(
                        """
                        DELETE FROM web_source_sync_jobs
                        WHERE owner_id=? AND kb_name=? AND source_id=?
                        """,
                        (owner_id, kb_name, source_id),
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def ensure_source(self, source_key: tuple[str, str, str]) -> WebSourceSyncJob:
        """Create a due job for one source without touching unrelated rows."""
        now = self._now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO web_source_sync_jobs
                    (owner_id, kb_name, source_id, state, next_run_at_ms,
                     updated_at_ms)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (*source_key, now, now),
            )
        job = self.get(source_key)
        if job is None:
            raise RuntimeError("Web source synchronization job could not be created")
        return job

    def recover_interrupted(self, runner_id: str) -> None:
        """Mark jobs left running by a prior process or expired lease as retryable."""
        now = self._now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE web_source_sync_jobs
                   SET state='interrupted',
                       error='Synchronization was interrupted by a restart',
                       runner_id='',
                       lease_until_ms=NULL,
                       next_run_at_ms=?,
                       updated_at_ms=?
                     WHERE state='running' AND runner_id<>?
                       AND (lease_until_ms IS NULL OR lease_until_ms<=?)
                """,
                (now, now, runner_id, now),
            )

    def list_jobs(self, owner_id: str, kb_name: str) -> list[WebSourceSyncJob]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM web_source_sync_jobs
                 WHERE owner_id=? AND kb_name=?
                 ORDER BY next_run_at_ms, source_id
                """,
                (owner_id, kb_name),
            ).fetchall()
        return [WebSourceSyncJob.from_row(row) for row in rows]

    def due_jobs(self, now_ms: int | None = None) -> list[WebSourceSyncJob]:
        now = self._now_ms() if now_ms is None else now_ms
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM web_source_sync_jobs
                 WHERE state IN ('pending', 'interrupted', 'error')
                   AND next_run_at_ms<=?
                 ORDER BY next_run_at_ms, owner_id, kb_name, source_id
                """,
                (now,),
            ).fetchall()
        return [WebSourceSyncJob.from_row(row) for row in rows]

    def claim(
        self,
        job: WebSourceSyncJob,
        *,
        runner_id: str,
        lease_until_ms: int,
    ) -> WebSourceSyncJob | None:
        """Claim one job only when its durable state still matches."""
        now = self._now_ms()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT * FROM web_source_sync_jobs
                     WHERE owner_id=? AND kb_name=? AND source_id=?
                    """,
                    self.key(job),
                ).fetchone()
                if row is None:
                    connection.execute("COMMIT")
                    return None
                current = WebSourceSyncJob.from_row(row)
                runnable = current.state in {"pending", "interrupted", "cancelled", "error"}
                lease_expired = (
                    current.state == "running"
                    and current.lease_until_ms is not None
                    and current.lease_until_ms <= now
                )
                if not (runnable or lease_expired):
                    connection.execute("COMMIT")
                    return None
                connection.execute(
                    """
                    UPDATE web_source_sync_jobs
                       SET state='running', runner_id=?, lease_until_ms=?,
                           cancel_requested=0, updated_at_ms=?
                     WHERE owner_id=? AND kb_name=? AND source_id=?
                    """,
                    (runner_id, lease_until_ms, now, *self.key(job)),
                )
                connection.execute("COMMIT")
                current.state = "running"
                current.runner_id = runner_id
                current.lease_until_ms = lease_until_ms
                current.cancel_requested = False
                return current
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def _update(
        self,
        job: WebSourceSyncJob,
        **fields: Any,
    ) -> None:
        assignments = list(fields)
        if not assignments:
            return
        fields["updated_at_ms"] = self._now_ms()
        assignments.append("updated_at_ms")
        values = list(fields.values())
        set_sql = ", ".join(f"{name}=?" for name in assignments)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE web_source_sync_jobs
                   SET {set_sql}
                 WHERE owner_id=? AND kb_name=? AND source_id=?
                """,
                (*values, *self.key(job)),
            )

    def mark_success(self, job: WebSourceSyncJob, next_run_at_ms: int) -> None:
        self._update(
            job,
            state="pending",
            next_run_at_ms=next_run_at_ms,
            last_run_at_ms=self._now_ms(),
            attempt=0,
            error=None,
            cancel_requested=False,
            runner_id="",
            lease_until_ms=None,
        )

    def mark_failure(
        self,
        job: WebSourceSyncJob,
        *,
        error: str,
        next_run_at_ms: int,
    ) -> None:
        self._update(
            job,
            state="error",
            next_run_at_ms=next_run_at_ms,
            last_run_at_ms=self._now_ms(),
            attempt=job.attempt + 1,
            error=error[:2000],
            cancel_requested=False,
            runner_id="",
            lease_until_ms=None,
        )

    def mark_cancelled(self, job: WebSourceSyncJob, next_run_at_ms: int | None = None) -> None:
        now = self._now_ms()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE web_source_sync_jobs
                   SET state='cancelled', cancel_requested=0, runner_id='',
                       lease_until_ms=NULL, last_run_at_ms=?, updated_at_ms=?,
                       next_run_at_ms=COALESCE(?, next_run_at_ms)
                 WHERE owner_id=? AND kb_name=? AND source_id=?
                """,
                (now, now, next_run_at_ms, *self.key(job)),
            )

    def request_cancel(self, job_key: tuple[str, str, str]) -> bool:
        now = self._now_ms()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    """
                    SELECT state FROM web_source_sync_jobs
                     WHERE owner_id=? AND kb_name=? AND source_id=?
                    """,
                    job_key,
                ).fetchone()
                if row is None:
                    connection.execute("COMMIT")
                    return False
                state = str(row["state"])
                if state not in {"pending", "running", "interrupted", "error"}:
                    connection.execute("COMMIT")
                    return False
                cancel_requested = 1 if state == "running" else 0
                if state == "pending":
                    connection.execute(
                        """
                        UPDATE web_source_sync_jobs
                           SET state='cancelled', cancel_requested=0, runner_id='',
                               lease_until_ms=NULL, updated_at_ms=?
                         WHERE owner_id=? AND kb_name=? AND source_id=?
                        """,
                        (now, *job_key),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE web_source_sync_jobs
                           SET cancel_requested=?, updated_at_ms=?
                         WHERE owner_id=? AND kb_name=? AND source_id=?
                        """,
                        (cancel_requested, now, *job_key),
                    )
                connection.execute("COMMIT")
                return True
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def delete(self, job_key: tuple[str, str, str]) -> bool:
        """Remove a job after its source has been deleted."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM web_source_sync_jobs
                 WHERE owner_id=? AND kb_name=? AND source_id=?
                """,
                job_key,
            )
            return int(cursor.rowcount or 0) > 0

    def retry(self, job_key: tuple[str, str, str]) -> WebSourceSyncJob | None:
        now = self._now_ms()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE web_source_sync_jobs
                   SET state='pending', next_run_at_ms=?, attempt=0, error=NULL,
                       cancel_requested=0, runner_id='', lease_until_ms=NULL,
                       updated_at_ms=?
                 WHERE owner_id=? AND kb_name=? AND source_id=?
                """,
                (now, now, *job_key),
            )
            changed = int(cursor.rowcount or 0) > 0
        if not changed:
            return None
        return self.get(job_key)

    def get(self, job_key: tuple[str, str, str]) -> WebSourceSyncJob | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM web_source_sync_jobs
                 WHERE owner_id=? AND kb_name=? AND source_id=?
                """,
                job_key,
            ).fetchone()
        return WebSourceSyncJob.from_row(row) if row else None


__all__ = ["SQLiteWebSourceSyncRepository", "WebSourceSyncJob"]
