"""Persistent, per-user LLM token quota with atomic reservations.

The ledger intentionally tracks tokens rather than provider dollars. Provider
cost attribution and hard spend ceilings belong in LiteLLM Proxy; this small
SQLite ledger is the exact user-facing credit limit that DeepTutor can enforce
before every upstream call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import threading
import uuid

from . import paths

DEFAULT_DAILY_TOKENS = 100_000
DEFAULT_MONTHLY_TOKENS = 1_000_000
MAX_QUOTA_TOKENS = 10_000_000_000
USAGE_DB_ENV = "DEEPTUTOR_USAGE_DB_PATH"

_schema_lock = threading.Lock()


class TokenQuotaExceeded(RuntimeError):
    """Raised before an upstream call would exceed a user's token quota."""

    def __init__(self, *, period: str, limit: int, used: int, requested: int) -> None:
        self.period = period
        self.limit = limit
        self.used = used
        self.requested = requested
        super().__init__(
            f"Token quota exceeded for {period}: limit={limit:,}, "
            f"used={used:,}, requested={requested:,}"
        )


class TokenQuotaUnavailable(RuntimeError):
    """Raised when the quota ledger cannot be opened safely."""


@dataclass(frozen=True)
class TokenQuotaPolicy:
    """A zero limit means unlimited for that period; defaults are bounded."""

    daily_tokens: int = DEFAULT_DAILY_TOKENS
    monthly_tokens: int = DEFAULT_MONTHLY_TOKENS

    def normalized(self) -> "TokenQuotaPolicy":
        return TokenQuotaPolicy(
            daily_tokens=_normalize_limit(self.daily_tokens),
            monthly_tokens=_normalize_limit(self.monthly_tokens),
        )

    @property
    def bounded(self) -> bool:
        return self.daily_tokens > 0 or self.monthly_tokens > 0


@dataclass
class TokenQuotaLease:
    """A reservation that is finalized exactly once after a provider call."""

    _ledger: "TokenQuotaLedger"
    reservation_id: str
    requested_tokens: int
    prompt_tokens_estimate: int
    output_tokens_estimate: int
    _finalized: bool = False

    def finalize(self, actual_tokens: int) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._ledger.finalize(self.reservation_id, max(0, int(actual_tokens)))

    def release(self) -> None:
        self.finalize(0)


def quota_policy_from_grant(grant: dict[str, object]) -> TokenQuotaPolicy:
    raw = grant.get("token_quota")
    if not isinstance(raw, dict):
        return TokenQuotaPolicy()
    return TokenQuotaPolicy(
        daily_tokens=_normalize_limit(raw.get("daily_tokens")),
        monthly_tokens=_normalize_limit(raw.get("monthly_tokens")),
    )


def default_token_quota() -> dict[str, int]:
    return {
        "daily_tokens": DEFAULT_DAILY_TOKENS,
        "monthly_tokens": DEFAULT_MONTHLY_TOKENS,
    }


def quota_db_path() -> Path:
    configured = os.environ.get(USAGE_DB_ENV, "").strip()
    return Path(configured).expanduser() if configured else paths.SYSTEM_ROOT / "usage.sqlite3"


def _normalize_limit(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(number, MAX_QUOTA_TOKENS))


def _period_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


class TokenQuotaLedger:
    """SQLite-backed ledger safe for concurrent requests and worker processes."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or quota_db_path()).expanduser()

    def _connect(self) -> sqlite3.Connection:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA journal_mode = WAL")
            with _schema_lock:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS token_usage (
                        user_id TEXT NOT NULL,
                        period TEXT NOT NULL,
                        period_key TEXT NOT NULL,
                        consumed_tokens INTEGER NOT NULL DEFAULT 0,
                        reserved_tokens INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, period, period_key)
                    );
                    CREATE TABLE IF NOT EXISTS token_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        daily_key TEXT NOT NULL,
                        monthly_key TEXT NOT NULL,
                        requested_tokens INTEGER NOT NULL,
                        state TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        finalized_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_token_reservations_active
                        ON token_reservations (user_id, state);
                    """
                )
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise TokenQuotaUnavailable(f"token quota ledger unavailable: {exc}") from exc

    @staticmethod
    def _ensure_period_row(
        connection: sqlite3.Connection,
        *,
        user_id: str,
        period: str,
        period_key: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO token_usage
                (user_id, period, period_key, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, period, period_key, now),
        )

    def reserve(
        self,
        user_id: str,
        requested_tokens: int,
        policy: TokenQuotaPolicy,
        *,
        prompt_tokens_estimate: int = 0,
        output_tokens_estimate: int = 0,
    ) -> TokenQuotaLease | None:
        requested = max(0, int(requested_tokens))
        policy = policy.normalized()
        if requested == 0 or not policy.bounded:
            return None

        daily_key, monthly_key = _period_keys()
        now = datetime.now(timezone.utc).isoformat()
        reservation_id = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_period_row(
                connection,
                user_id=user_id,
                period="daily",
                period_key=daily_key,
                now=now,
            )
            self._ensure_period_row(
                connection,
                user_id=user_id,
                period="monthly",
                period_key=monthly_key,
                now=now,
            )
            rows = {
                row["period"]: row
                for row in connection.execute(
                    """
                    SELECT period, consumed_tokens, reserved_tokens
                    FROM token_usage
                    WHERE user_id = ? AND period_key IN (?, ?)
                    """,
                    (user_id, daily_key, monthly_key),
                )
            }
            for period, limit in (
                ("daily", policy.daily_tokens),
                ("monthly", policy.monthly_tokens),
            ):
                if limit <= 0:
                    continue
                row = rows[period]
                used = int(row["consumed_tokens"]) + int(row["reserved_tokens"])
                if used + requested > limit:
                    raise TokenQuotaExceeded(
                        period=period,
                        limit=limit,
                        used=used,
                        requested=requested,
                    )

            for period, period_key in (("daily", daily_key), ("monthly", monthly_key)):
                connection.execute(
                    """
                    UPDATE token_usage
                    SET reserved_tokens = reserved_tokens + ?, updated_at = ?
                    WHERE user_id = ? AND period = ? AND period_key = ?
                    """,
                    (requested, now, user_id, period, period_key),
                )
            connection.execute(
                """
                INSERT INTO token_reservations
                    (reservation_id, user_id, daily_key, monthly_key,
                     requested_tokens, state, created_at)
                VALUES (?, ?, ?, ?, ?, 'active', ?)
                """,
                (reservation_id, user_id, daily_key, monthly_key, requested, now),
            )
            connection.execute("COMMIT")
        except TokenQuotaExceeded:
            connection.execute("ROLLBACK")
            raise
        except (OSError, sqlite3.Error) as exc:
            connection.execute("ROLLBACK")
            raise TokenQuotaUnavailable(f"token quota reservation failed: {exc}") from exc
        finally:
            connection.close()
        return TokenQuotaLease(
            self,
            reservation_id,
            requested,
            max(0, int(prompt_tokens_estimate)),
            max(0, int(output_tokens_estimate)),
        )

    def finalize(self, reservation_id: str, actual_tokens: int) -> None:
        connection = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        try:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                """
                SELECT user_id, daily_key, monthly_key, requested_tokens, state
                FROM token_reservations WHERE reservation_id = ?
                """,
                (reservation_id,),
            ).fetchone()
            if reservation is None or reservation["state"] != "active":
                connection.execute("COMMIT")
                return
            requested = int(reservation["requested_tokens"])
            actual = max(0, int(actual_tokens))
            # The reservation includes an upper bound. If a provider reports a
            # larger value than that bound, book the larger value so accounting
            # never silently undercounts a call.
            booked = max(requested, actual) if actual > requested else actual
            for period, period_key in (
                ("daily", reservation["daily_key"]),
                ("monthly", reservation["monthly_key"]),
            ):
                connection.execute(
                    """
                    UPDATE token_usage
                    SET reserved_tokens = max(0, reserved_tokens - ?),
                        consumed_tokens = consumed_tokens + ?,
                        updated_at = ?
                    WHERE user_id = ? AND period = ? AND period_key = ?
                    """,
                    (requested, booked, now, reservation["user_id"], period, period_key),
                )
            connection.execute(
                """
                UPDATE token_reservations
                SET state = 'finalized', finalized_at = ?
                WHERE reservation_id = ?
                """,
                (now, reservation_id),
            )
            connection.execute("COMMIT")
        except (OSError, sqlite3.Error) as exc:
            connection.execute("ROLLBACK")
            raise TokenQuotaUnavailable(f"token quota finalization failed: {exc}") from exc
        finally:
            connection.close()


def current_user_quota_policy() -> TokenQuotaPolicy | None:
    """Resolve the policy for the request-local user; admins are unlimited."""
    from .context import get_current_user
    from .grants import load_grant

    user = get_current_user()
    if user.is_admin:
        return None
    return quota_policy_from_grant(load_grant(user.id))


def reserve_current_user_tokens(
    *,
    requested_tokens: int,
    prompt_tokens_estimate: int,
    output_tokens_estimate: int,
) -> TokenQuotaLease | None:
    from .context import get_current_user

    policy = current_user_quota_policy()
    if policy is None:
        return None
    return TokenQuotaLedger().reserve(
        get_current_user().id,
        requested_tokens,
        policy,
        prompt_tokens_estimate=prompt_tokens_estimate,
        output_tokens_estimate=output_tokens_estimate,
    )


__all__ = [
    "DEFAULT_DAILY_TOKENS",
    "DEFAULT_MONTHLY_TOKENS",
    "TokenQuotaExceeded",
    "TokenQuotaLedger",
    "TokenQuotaLease",
    "TokenQuotaPolicy",
    "TokenQuotaUnavailable",
    "current_user_quota_policy",
    "default_token_quota",
    "quota_db_path",
    "quota_policy_from_grant",
    "reserve_current_user_tokens",
]
