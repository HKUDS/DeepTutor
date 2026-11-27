"""Table-backed job queue with at-least-once delivery and idempotent effects.

The contract
------------
``enqueue`` is idempotent on ``dedupe_key``: enqueueing the same key twice
returns the *same* job id and does not create a second job. That is the
mechanism that satisfies "retrying a job must not duplicate its effect" — the
retry collapses instead of forking.

``claim`` is a conditional ``UPDATE ... WHERE status = 'queued'``. Two workers
racing on one row means exactly one gets ``rowcount == 1``; the loser moves on.
Expired leases (``lease_expires_at < now()``) are claimable again, which is how
a killed worker's job is recovered with no external watchdog.

Delivery is at-least-once, not exactly-once: a worker can crash after doing its
side effect but before marking the job succeeded, so the job runs again. That
is unavoidable without distributed transactions, and it is why every job
handler must itself be idempotent. :func:`deeptutor.db.jobs.handlers` documents
the pattern; the queue cannot enforce it.

Timestamps are ISO-8601 UTC strings, lexicographically comparable, identical in
both engines. Lease comparison is therefore a plain string comparison, which
keeps the claim a single portable statement instead of a dialect switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Any, Callable, Iterable, Literal
import uuid

from deeptutor.db.config import get_database_settings
from deeptutor.db.connection import Database, DatabaseError, DatabaseUnavailable

logger = logging.getLogger(__name__)

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]

DEFAULT_LEASE_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 5

#: Exponential backoff base for retries, in seconds. Attempt *n* waits
#: ``base * 2**(n-1)`` capped at :data:`MAX_BACKOFF_SECONDS`.
BACKOFF_BASE_SECONDS = 10
MAX_BACKOFF_SECONDS = 3600


class JobQueueUnavailable(RuntimeError):
    """The queue was requested but no database is configured."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _row_to_job(row: dict[str, Any]) -> Job:
    return Job(
        id=str(row["id"]),
        kind=str(row["kind"]),
        dedupe_key=row.get("dedupe_key"),
        payload=json.loads(row.get("payload") or "{}"),
        status=str(row["status"]),  # type: ignore[arg-type]
        priority=int(row["priority"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        run_after=str(row["run_after"]),
        lease_owner=row.get("lease_owner"),
        lease_expires_at=row.get("lease_expires_at"),
        last_error=row.get("last_error"),
        result=json.loads(row["result"]) if row.get("result") else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        completed_at=row.get("completed_at"),
    )


@dataclass
class Job:
    """A job as read back from the queue."""

    id: str
    kind: str
    dedupe_key: str | None
    payload: dict[str, Any]
    status: JobState
    priority: int
    attempts: int
    max_attempts: int
    run_after: str
    lease_owner: str | None
    lease_expires_at: str | None
    last_error: str | None
    result: Any
    created_at: str
    updated_at: str
    completed_at: str | None

    @property
    def is_terminal(self) -> bool:
        return self.status in {"succeeded", "failed", "cancelled"}


@dataclass
class ClaimedJob(Job):
    """A job this worker owns for the length of its lease."""

    lease_token: str = ""

    def to_event(self, event: str, detail: str | None = None) -> dict[str, Any]:
        return {"job_id": self.id, "event": event, "detail": detail}


class JobQueue:
    """Durable queue bound to one :class:`Database`."""

    def __init__(self, db: Database, *, worker_id: str | None = None) -> None:
        self._db = db
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    # -- enqueue ------------------------------------------------------------

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        dedupe_key: str | None = None,
        priority: int = 100,
        delay_seconds: int = 0,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> Job:
        """Create a job, or return the existing one with the same ``dedupe_key``.

        The select-then-insert runs inside one transaction. On Postgres the
        ``ON CONFLICT DO NOTHING`` plus re-select would be the cleaner spelling,
        but SQLite's conflict handling on a *partial* unique index differs, so
        the portable version relies on the unique index to abort the insert and
        then re-reads. The unique index — not the read — is what provides the
        guarantee; the read is only the fast path.
        """
        now = _utc_now()
        run_after = _iso(now + timedelta(seconds=max(0, delay_seconds)))
        job_id = f"job_{uuid.uuid4().hex}"
        with self._db.transaction() as conn:
            existing = self._select_by_dedupe(conn, dedupe_key)
            if existing is not None:
                return _row_to_job(existing)
            try:
                conn.execute(
                    "INSERT INTO jobs (id, kind, dedupe_key, payload, status, priority, "
                    "attempts, max_attempts, run_after, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?, ?)",
                    (
                        job_id,
                        kind,
                        dedupe_key,
                        json.dumps(payload or {}, ensure_ascii=False),
                        priority,
                        max_attempts,
                        run_after,
                        _iso(now),
                        _iso(now),
                    ),
                )
            except DatabaseError:
                # Lost a race against a concurrent insert of the same dedupe
                # key. The unique index rejected us; the rule is to collapse.
                raced = self._select_by_dedupe(conn, dedupe_key)
                if raced is not None:
                    return _row_to_job(raced)
                raise
            self._append_event(conn, job_id, "enqueued", self.worker_id)
            row = conn.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:  # pragma: no cover - defensive
            raise DatabaseError("job vanished immediately after insert")
        return _row_to_job(row)

    @staticmethod
    def _select_by_dedupe(conn: Any, dedupe_key: str | None) -> dict[str, Any] | None:
        if not dedupe_key:
            return None
        return conn.query_one("SELECT * FROM jobs WHERE dedupe_key = ?", (dedupe_key,))

    # -- claim / heartbeat --------------------------------------------------

    def claim(
        self,
        *,
        kinds: Iterable[str] | None = None,
        limit: int = 1,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
    ) -> list[ClaimedJob]:
        """Atomically claim up to *limit* runnable jobs.

        A job is runnable when it is ``queued`` and due, or ``running`` with an
        expired lease. Both cases are covered by the same predicate, so a
        crashed worker needs no separate recovery pass.
        """
        moment = now or _utc_now()
        now_iso = _iso(moment)
        lease_until = _iso(moment + timedelta(seconds=lease_seconds))
        claimed: list[ClaimedJob] = []
        # ``kinds=None`` means "any kind". An empty list is a caller bug: it
        # would silently claim nothing, so treat it as "any kind" too rather
        # than letting a worker spin on an empty queue forever.
        kind_list = [k for k in kinds if k] if kinds else None

        for _ in range(max(0, limit)):
            with self._db.transaction() as conn:
                params: list[Any] = [now_iso, now_iso]
                kind_clause = ""
                if kind_list:
                    placeholders = ", ".join("?" for _ in kind_list)
                    kind_clause = f" AND kind IN ({placeholders})"
                    params.extend(kind_list)
                row = conn.query_one(
                    "SELECT id FROM jobs "
                    "WHERE ((status = 'queued' AND run_after <= ?) "
                    "   OR (status = 'running' AND lease_expires_at IS NOT NULL "
                    "       AND lease_expires_at < ?)) "
                    f"{kind_clause} "
                    "ORDER BY priority ASC, run_after ASC LIMIT 1",
                    tuple(params),
                )
                if row is None:
                    break
                job_id = str(row["id"])
                token = uuid.uuid4().hex
                updated = conn.execute(
                    "UPDATE jobs SET status = 'running', lease_owner = ?, "
                    "lease_expires_at = ?, attempts = attempts + 1, updated_at = ? "
                    "WHERE id = ? AND (status = 'queued' OR status = 'running')",
                    (f"{self.worker_id}:{token}", lease_until, now_iso, job_id),
                )
                if updated != 1:
                    # Another worker won the race for this row.
                    continue
                self._append_event(conn, job_id, "claimed", self.worker_id)
                full = conn.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
            if full is None:  # pragma: no cover - defensive
                continue
            job = _row_to_job(full)
            claimed.append(
                ClaimedJob(
                    id=job.id,
                    kind=job.kind,
                    dedupe_key=job.dedupe_key,
                    payload=job.payload,
                    status=job.status,
                    priority=job.priority,
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    run_after=job.run_after,
                    lease_owner=job.lease_owner,
                    lease_expires_at=job.lease_expires_at,
                    last_error=job.last_error,
                    result=job.result,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    completed_at=job.completed_at,
                    lease_token=token,
                )
            )
        return claimed

    def heartbeat(self, job: ClaimedJob, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
        """Extend a lease. False means the lease was already lost."""
        lease_until = _iso(_utc_now() + timedelta(seconds=lease_seconds))
        with self._db.transaction() as conn:
            changed = conn.execute(
                "UPDATE jobs SET lease_expires_at = ?, updated_at = ? "
                "WHERE id = ? AND lease_owner = ? AND status = 'running'",
                (lease_until, _iso(_utc_now()), job.id, job.lease_owner),
            )
        return changed == 1

    # -- completion ---------------------------------------------------------

    def succeed(self, job: ClaimedJob, result: Any = None) -> bool:
        """Mark a job done. Guarded on the lease so a zombie worker cannot win."""
        now = _iso(_utc_now())
        with self._db.transaction() as conn:
            changed = conn.execute(
                "UPDATE jobs SET status = 'succeeded', result = ?, last_error = NULL, "
                "completed_at = ?, lease_expires_at = NULL, updated_at = ? "
                "WHERE id = ? AND status = 'running' AND lease_owner = ?",
                (
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    now,
                    now,
                    job.id,
                    job.lease_owner,
                ),
            )
            if changed == 1:
                self._append_event(conn, job.id, "succeeded", self.worker_id)
        return changed == 1

    def fail(self, job: ClaimedJob, error: str, *, retry: bool | None = None) -> str:
        """Record a failure; requeue with backoff unless attempts are exhausted.

        Returns the resulting state so the caller can log it.
        """
        now = _utc_now()
        exhausted = job.attempts >= job.max_attempts
        should_retry = (not exhausted) if retry is None else (retry and not exhausted)
        backoff = min(BACKOFF_BASE_SECONDS * (2 ** max(0, job.attempts - 1)), MAX_BACKOFF_SECONDS)
        with self._db.transaction() as conn:
            if should_retry:
                conn.execute(
                    "UPDATE jobs SET status = 'queued', last_error = ?, "
                    "run_after = ?, lease_owner = NULL, lease_expires_at = NULL, "
                    "updated_at = ? WHERE id = ? AND lease_owner = ?",
                    (
                        error[:2000],
                        _iso(now + timedelta(seconds=backoff)),
                        _iso(now),
                        job.id,
                        job.lease_owner,
                    ),
                )
                self._append_event(conn, job.id, "retry_scheduled", f"in {backoff}s")
                return "queued"
            conn.execute(
                "UPDATE jobs SET status = 'failed', last_error = ?, completed_at = ?, "
                "lease_expires_at = NULL, updated_at = ? WHERE id = ?",
                (error[:2000], _iso(now), _iso(now), job.id),
            )
            self._append_event(conn, job.id, "failed", error[:200])
            return "failed"

    def cancel(self, job_id: str) -> bool:
        now = _iso(_utc_now())
        with self._db.transaction() as conn:
            changed = conn.execute(
                "UPDATE jobs SET status = 'cancelled', completed_at = ?, updated_at = ? "
                "WHERE id = ? AND status IN ('queued', 'running')",
                (now, now, job_id),
            )
            if changed:
                self._append_event(conn, job_id, "cancelled", self.worker_id)
        return changed == 1

    # -- introspection ------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._db.read() as conn:
            row = conn.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return _row_to_job(row) if row else None

    def list_jobs(
        self,
        *,
        status: JobState | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        params.append(limit)
        with self._db.read() as conn:
            rows = conn.query(
                f"SELECT * FROM jobs {where}ORDER BY created_at DESC LIMIT ?", tuple(params)
            )
        return [_row_to_job(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._db.read() as conn:
            rows = conn.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {str(row["status"]): int(row["n"]) for row in rows}

    def events(self, job_id: str) -> list[dict[str, Any]]:
        with self._db.read() as conn:
            return conn.query(
                "SELECT event, worker, detail, created_at FROM job_events "
                "WHERE job_id = ? ORDER BY created_at ASC",
                (job_id,),
            ).rows

    @staticmethod
    def _append_event(
        conn: Any, job_id: str, event: str, worker: str | None, detail: str | None = None
    ) -> None:
        conn.execute(
            "INSERT INTO job_events (id, job_id, event, worker, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"evt_{uuid.uuid4().hex}", job_id, event, worker, detail, _iso(_utc_now())),
        )

    # -- worker loop --------------------------------------------------------

    def run_once(
        self,
        handlers: dict[str, Callable[[ClaimedJob], Any]],
        *,
        limit: int = 10,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> int:
        """Claim and process up to *limit* jobs. Returns the count processed.

        Unknown ``kind`` values are failed rather than silently skipped: a job
        nobody can run would otherwise sit in the queue forever and look like
        health.
        """
        processed = 0
        # Deliberately claim *any* kind, not just the ones we have handlers for.
        # Filtering by handler would leave an unhandled job sitting in the queue
        # forever, and a queue that quietly never drains its poison messages
        # looks exactly like a healthy one from the outside. Claiming it means
        # we can fail it explicitly and it shows up in the failed count.
        for job in self.claim(limit=limit, lease_seconds=lease_seconds):
            handler = handlers.get(job.kind)
            if handler is None:
                self.fail(job, f"no handler registered for kind {job.kind!r}", retry=False)
                processed += 1
                continue
            try:
                result = handler(job)
            except Exception as exc:  # noqa: BLE001 - job failures are data, not crashes
                logger.exception("job %s (%s) failed", job.id, job.kind)
                self.fail(job, f"{type(exc).__name__}: {exc}")
            else:
                self.succeed(job, result)
            processed += 1
        return processed


def acquire_queue(db: Database | None = None) -> JobQueue:
    """Build a queue, or raise :class:`JobQueueUnavailable`.

    Callers that can degrade gracefully (an admin page showing queue depth)
    should catch the exception; callers that need a job to run should let it
    propagate so the request fails loudly rather than silently dropping work.
    """
    database = db
    if database is None:
        from deeptutor.db.connection import open_database

        database = open_database(get_database_settings())
    if database is None:
        raise JobQueueUnavailable(
            "no database configured; set DEEPTUTOR_DATABASE_URL to enable the job queue"
        )
    return JobQueue(database)


def health(db: Database | None = None) -> dict[str, Any]:
    """Queue depth for readiness payloads. Never raises."""
    try:
        queue = acquire_queue(db)
        return {"ok": True, "depth": queue.stats()}
    except (JobQueueUnavailable, DatabaseUnavailable) as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": type(exc).__name__}
