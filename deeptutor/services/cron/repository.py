"""Process-safe SQLite persistence for scheduled jobs."""

from __future__ import annotations

from collections.abc import Iterable
import contextlib
import fcntl
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Protocol


class CronRepository(Protocol):
    """Narrow persistence contract used by :class:`CronService`."""

    def revision(self) -> int: ...

    def list_payloads(self) -> list[dict[str, Any]]: ...

    def upsert(self, payload: dict[str, Any]) -> None: ...

    def delete(self, job_id: str, *, owner_key: str | None = None) -> bool: ...

    def delete_owner(self, owner_key: str) -> int: ...


class SQLiteCronRepository:
    """WAL-backed cron repository shared by all backend workers.

    ``path`` may point at the old ``jobs.json`` location. On first open that
    file is imported under an inter-process migration lock, archived beside the
    database, and replaced by SQLite without losing job identifiers or state.
    """

    def __init__(self, path: Path, *, legacy_path: Path | None = None) -> None:
        self.path = Path(path).expanduser().resolve()
        self.legacy_path = Path(legacy_path).expanduser().resolve() if legacy_path else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initial = self._prepare_legacy_file()
        self._initialize(initial)

    @property
    def _migration_lock_path(self) -> Path:
        return self.path.with_name(f".{self.path.name}.migration.lock")

    @contextlib.contextmanager
    def _migration_lock(self):
        self._migration_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._migration_lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _is_sqlite(path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                return handle.read(16) == b"SQLite format 3\x00"
        except OSError:
            return False

    def _prepare_legacy_file(self) -> list[dict[str, Any]]:
        with self._migration_lock():
            if self.path.exists() and self._is_sqlite(self.path):
                return []
            source = self.path if self.path.exists() else self.legacy_path
            if source is None or not source.exists():
                return []
            timestamp = int(time.time() * 1000)
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
                jobs = raw.get("jobs", []) if isinstance(raw, dict) else []
                if not isinstance(jobs, list):
                    raise ValueError("legacy cron jobs must be a list")
                payloads = [dict(job) for job in jobs if isinstance(job, dict)]
                archive = source.with_name(f"{source.stem}.legacy-{timestamp}.json")
            except Exception:
                payloads = []
                archive = source.with_name(f"{source.stem}.corrupt-{timestamp}.json")
            source.replace(archive)
            return payloads

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self, initial: Iterable[dict[str, Any]]) -> None:
        with self._migration_lock(), self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    next_run_at_ms INTEGER,
                    payload TEXT NOT NULL,
                    updated_at_ms INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cron_jobs_owner ON cron_jobs(owner_key)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cron_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    revision INTEGER NOT NULL
                )
                """
            )
            connection.execute("INSERT OR IGNORE INTO cron_meta(singleton, revision) VALUES (1, 0)")
            if not initial:
                return
            connection.execute("BEGIN IMMEDIATE")
            try:
                for payload in initial:
                    self._upsert_row(connection, payload)
                connection.execute("UPDATE cron_meta SET revision = revision + 1 WHERE singleton=1")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _owner_key(payload: dict[str, Any]) -> str:
        owner = payload.get("owner") or {}
        if owner.get("kind") == "partner":
            return f"partner:{owner.get('partner_id') or ''}"
        return f"chat:{owner.get('user_id') or 'local-admin'}"

    @classmethod
    def _upsert_row(cls, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        job_id = str(payload.get("id") or "").strip()
        if not job_id:
            raise ValueError("cron job id is required")
        state = payload.get("state") or {}
        next_run = state.get("next_run_at_ms")
        connection.execute(
            """
            INSERT INTO cron_jobs(id, owner_key, next_run_at_ms, payload, updated_at_ms)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                owner_key=excluded.owner_key,
                next_run_at_ms=excluded.next_run_at_ms,
                payload=excluded.payload,
                updated_at_ms=excluded.updated_at_ms
            """,
            (
                job_id,
                cls._owner_key(payload),
                int(next_run) if next_run is not None else None,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                int(time.time() * 1000),
            ),
        )

    def revision(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT revision FROM cron_meta WHERE singleton=1").fetchone()
        return int(row[0]) if row else 0

    def list_payloads(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM cron_jobs ORDER BY COALESCE(next_run_at_ms, 0), id"
            ).fetchall()
        return [json.loads(str(row[0])) for row in rows]

    def upsert(self, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._upsert_row(connection, payload)
                connection.execute("UPDATE cron_meta SET revision = revision + 1 WHERE singleton=1")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def delete(self, job_id: str, *, owner_key: str | None = None) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if owner_key is None:
                    cursor = connection.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
                else:
                    cursor = connection.execute(
                        "DELETE FROM cron_jobs WHERE id=? AND owner_key=?",
                        (job_id, owner_key),
                    )
                changed = int(cursor.rowcount or 0) > 0
                if changed:
                    connection.execute(
                        "UPDATE cron_meta SET revision = revision + 1 WHERE singleton=1"
                    )
                connection.execute("COMMIT")
                return changed
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def delete_owner(self, owner_key: str) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = connection.execute("DELETE FROM cron_jobs WHERE owner_key=?", (owner_key,))
                count = max(0, int(cursor.rowcount or 0))
                if count:
                    connection.execute(
                        "UPDATE cron_meta SET revision = revision + 1 WHERE singleton=1"
                    )
                connection.execute("COMMIT")
                return count
            except Exception:
                connection.execute("ROLLBACK")
                raise


__all__ = ["CronRepository", "SQLiteCronRepository"]
