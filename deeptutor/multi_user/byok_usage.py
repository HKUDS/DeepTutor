"""Persistent safety limits and redacted usage telemetry for BYOK calls.

This ledger is deliberately separate from platform quota accounting. BYOK
requests do not consume administrator-funded credits, but they still need a
per-user rate gate and an auditable request lifecycle when the deployment is
open to untrusted users.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from . import paths
from .byok_policy import load_policy

_schema_lock = threading.Lock()
logger = logging.getLogger(__name__)


class ByokUsageError(RuntimeError):
    """Base class for fail-closed BYOK safety/telemetry errors."""


class ByokUsageLimitExceeded(ByokUsageError):
    """The user reached a BYOK request or per-request safety limit."""


class ByokUsageUnavailable(ByokUsageError):
    """The BYOK usage ledger could not enforce the safety policy."""


def _db_path() -> Path:
    configured = os.getenv("DEEPTUTOR_BYOK_USAGE_DB_PATH", "").strip()
    return Path(configured).expanduser() if configured else paths.SYSTEM_ROOT / "byok_usage.sqlite3"


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


class ByokUsageLease:
    """A request row finalized at most once."""

    def __init__(self, db_path: Path, request_id: str, estimated_units: int) -> None:
        self.db_path = db_path
        self.request_id = request_id
        self.estimated_units = max(0, int(estimated_units))
        self._finalized = False

    def finalize(self, reported_units: int = 0, *, status: str = "success") -> None:
        if self._finalized:
            return
        self._finalized = True
        try:
            _finish_usage(
                self.db_path,
                self.request_id,
                status=status,
                reported_units=max(0, int(reported_units)),
            )
        except ByokUsageUnavailable:
            # The reservation already passed the fail-closed preflight. A
            # successful provider response must not be turned into a user
            # error solely because post-call telemetry could not be updated.
            # The started row remains visible for operators and still counts
            # against the short rate window until it ages out.
            logger.warning("BYOK usage finalization failed for request %s", self.request_id)

    def release(self, *, status: str = "failed") -> None:
        self.finalize(0, status=status)


def _connect(db_path: Path) -> sqlite3.Connection:
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        with _schema_lock:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS byok_usage (
                    request_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    service TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    estimated_units INTEGER NOT NULL DEFAULT 0,
                    reported_units INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    finalized_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_byok_usage_rate
                    ON byok_usage (user_id, service, created_at);
                """
            )
        return connection
    except (OSError, sqlite3.Error) as exc:
        raise ByokUsageUnavailable("BYOK usage ledger is unavailable") from exc


def start_byok_usage(
    *,
    service: str,
    user_id: str,
    profile_id: str,
    provider: str,
    model: str,
    estimated_units: int,
) -> ByokUsageLease:
    """Reserve one BYOK request slot and return a redacted usage lease."""
    policy = load_policy()
    limits = policy.get("limits") if isinstance(policy.get("limits"), dict) else {}
    estimated = max(0, int(estimated_units))
    if service == "llm":
        max_tokens = max(1, int(limits.get("max_single_request_tokens", 64_000)))
        if estimated > max_tokens:
            raise ByokUsageLimitExceeded(
                f"BYOK LLM request exceeds the safety limit of {max_tokens:,} tokens"
            )
    rpm = max(1, int(limits.get("byok_requests_per_minute", 60)))
    db_path = _db_path()
    request_id = uuid.uuid4().hex
    now = _now()
    connection = _connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Keep the telemetry table bounded enough for the rate query while
        # retaining a useful operational history window.
        connection.execute("DELETE FROM byok_usage WHERE created_at < ?", (now - 90 * 86400,))
        count = connection.execute(
            """
            SELECT COUNT(*) FROM byok_usage
            WHERE user_id = ? AND service = ? AND created_at >= ?
            """,
            (user_id, service, now - 60),
        ).fetchone()[0]
        if int(count) >= rpm:
            raise ByokUsageLimitExceeded("BYOK request rate limit exceeded; try again later")
        connection.execute(
            """
            INSERT INTO byok_usage
                (request_id, user_id, service, profile_id, provider, model,
                 estimated_units, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)
            """,
            (
                request_id,
                user_id,
                service,
                profile_id,
                provider,
                model,
                estimated,
                now,
            ),
        )
        connection.execute("COMMIT")
    except ByokUsageLimitExceeded:
        connection.execute("ROLLBACK")
        raise
    except (OSError, sqlite3.Error) as exc:
        connection.execute("ROLLBACK")
        raise ByokUsageUnavailable("BYOK usage ledger reservation failed") from exc
    finally:
        connection.close()
    return ByokUsageLease(db_path, request_id, estimated)


def _finish_usage(
    db_path: Path,
    request_id: str,
    *,
    status: str,
    reported_units: int,
) -> None:
    normalized_status = status if status in {"success", "failed", "cancelled"} else "failed"
    connection = _connect(db_path)
    try:
        connection.execute(
            """
            UPDATE byok_usage
            SET status = ?, reported_units = ?, finalized_at = ?
            WHERE request_id = ? AND status = 'started'
            """,
            (normalized_status, max(0, int(reported_units)), _now(), request_id),
        )
    except (OSError, sqlite3.Error) as exc:
        raise ByokUsageUnavailable("BYOK usage finalization failed") from exc
    finally:
        connection.close()


__all__ = [
    "ByokUsageError",
    "ByokUsageLease",
    "ByokUsageLimitExceeded",
    "ByokUsageUnavailable",
    "start_byok_usage",
]
