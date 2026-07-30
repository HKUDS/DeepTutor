"""Persistent, per-user resource quotas with atomic reservations.

The ledger tracks user-facing LLM/Embedding tokens and MinerU pages rather than
provider dollars. Provider cost attribution and hard spend ceilings belong in
LiteLLM Proxy; this small SQLite ledger enforces exact per-user limits before
the relevant upstream work starts.
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
from .quota_config import (
    DEFAULT_QUOTA,
    DEFAULT_TOKEN_QUOTA,
    normalize_quota_limit,
    normalize_quotas,
)

DEFAULT_DAILY_TOKENS = DEFAULT_TOKEN_QUOTA["daily_tokens"]
DEFAULT_MONTHLY_TOKENS = DEFAULT_TOKEN_QUOTA["monthly_tokens"]
USAGE_DB_ENV = "DEEPTUTOR_USAGE_DB_PATH"

_schema_lock = threading.Lock()


class QuotaExceeded(RuntimeError):
    """Raised before a provider call would exceed a user's resource quota."""

    def __init__(
        self,
        *,
        resource: str,
        unit: str,
        period: str,
        limit: int,
        used: int,
        requested: int,
    ) -> None:
        self.resource = resource
        self.unit = unit
        self.period = period
        self.limit = limit
        self.used = used
        self.requested = requested
        super().__init__(
            f"{resource.title()} quota exceeded for {period}: limit={limit:,} {unit}, "
            f"used={used:,}, requested={requested:,}"
        )


class TokenQuotaExceeded(QuotaExceeded):
    """Backward-compatible LLM token quota exception."""

    def __init__(self, *, period: str, limit: int, used: int, requested: int) -> None:
        super().__init__(
            resource="token",
            unit="tokens",
            period=period,
            limit=limit,
            used=used,
            requested=requested,
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


@dataclass(frozen=True)
class ResourceQuotaPolicy:
    """Daily/monthly limits for Embedding tokens or MinerU pages."""

    resource: str
    unit: str
    daily_limit: int
    monthly_limit: int
    per_request_limit: int = 0

    def normalized(self) -> "ResourceQuotaPolicy":
        return ResourceQuotaPolicy(
            resource=self.resource,
            unit=self.unit,
            daily_limit=normalize_quota_limit(self.daily_limit, 0),
            monthly_limit=normalize_quota_limit(self.monthly_limit, 0),
            per_request_limit=normalize_quota_limit(self.per_request_limit, 0),
        )

    @property
    def bounded(self) -> bool:
        return (
            self.daily_limit > 0
            or self.monthly_limit > 0
            or self.per_request_limit > 0
        )


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
    """Resolve the backward-compatible LLM policy from a user grant."""
    quotas = normalize_quotas(
        grant.get("quota"),
        legacy_token_quota=grant.get("token_quota"),
    )
    raw = quotas["llm"]
    return TokenQuotaPolicy(
        daily_tokens=_normalize_limit(raw.get("daily_tokens")),
        monthly_tokens=_normalize_limit(raw.get("monthly_tokens")),
    )


def resource_quota_policy_from_grant(
    grant: dict[str, object], resource: str
) -> ResourceQuotaPolicy:
    """Resolve an Embedding or MinerU policy from a user grant."""
    quotas = normalize_quotas(
        grant.get("quota"),
        legacy_token_quota=grant.get("token_quota"),
    )
    raw = quotas[resource]
    if resource == "mineru":
        return ResourceQuotaPolicy(
            resource=resource,
            unit="pages",
            daily_limit=_normalize_limit(raw.get("daily_pages")),
            monthly_limit=_normalize_limit(raw.get("monthly_pages")),
            per_request_limit=_normalize_limit(raw.get("max_pages_per_file")),
        )
    if resource == "embedding":
        return ResourceQuotaPolicy(
            resource=resource,
            unit="tokens",
            daily_limit=_normalize_limit(raw.get("daily_tokens")),
            monthly_limit=_normalize_limit(raw.get("monthly_tokens")),
        )
    raise ValueError(f"Unsupported resource quota: {resource}")


def default_quota() -> dict[str, dict[str, int]]:
    """Return the current persisted resource defaults, safely."""
    try:
        # Keep this import lazy: runtime_settings imports the shared quota
        # normalizer, and importing the settings service at module import time
        # would create an avoidable cycle.
        from deeptutor.services.config import load_auth_settings

        auth_settings = load_auth_settings()
        return normalize_quotas(
            auth_settings.get("default_quota"),
            fallback=DEFAULT_QUOTA,
            legacy_token_quota=auth_settings.get("default_token_quota"),
        )
    except Exception:
        return {resource: dict(values) for resource, values in DEFAULT_QUOTA.items()}


def default_token_quota() -> dict[str, int]:
    """Return the persisted LLM default for legacy callers."""
    return dict(default_quota()["llm"])


def quota_db_path() -> Path:
    configured = os.environ.get(USAGE_DB_ENV, "").strip()
    return Path(configured).expanduser() if configured else paths.SYSTEM_ROOT / "usage.sqlite3"


def _normalize_limit(value: object) -> int:
    return normalize_quota_limit(value, 0)


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


@dataclass
class ResourceQuotaLease:
    """A reservation for a non-LLM resource such as Embedding or MinerU."""

    _ledger: "ResourceQuotaLedger"
    reservation_id: str
    requested_units: int
    _finalized: bool = False

    def finalize(self, actual_units: int) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._ledger.finalize(self.reservation_id, max(0, int(actual_units)))

    def release(self) -> None:
        self.finalize(0)


class ResourceQuotaLedger:
    """SQLite-backed daily/monthly ledger for Embedding and MinerU usage.

    The original ``token_usage`` tables remain the LLM compatibility store.
    Resource usage has a separate table with a resource dimension, so existing
    deployments keep their LLM history while the new categories are introduced.
    """

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
                    CREATE TABLE IF NOT EXISTS resource_usage (
                        user_id TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        unit TEXT NOT NULL,
                        period TEXT NOT NULL,
                        period_key TEXT NOT NULL,
                        consumed_units INTEGER NOT NULL DEFAULT 0,
                        reserved_units INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, resource, period, period_key)
                    );
                    CREATE TABLE IF NOT EXISTS resource_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        resource TEXT NOT NULL,
                        unit TEXT NOT NULL,
                        daily_key TEXT NOT NULL,
                        monthly_key TEXT NOT NULL,
                        requested_units INTEGER NOT NULL,
                        state TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        finalized_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_resource_reservations_active
                        ON resource_reservations (user_id, resource, state);
                    """
                )
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise TokenQuotaUnavailable(f"resource quota ledger unavailable: {exc}") from exc

    @staticmethod
    def _ensure_period_row(
        connection: sqlite3.Connection,
        *,
        user_id: str,
        resource: str,
        unit: str,
        period: str,
        period_key: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO resource_usage
                (user_id, resource, unit, period, period_key, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, resource, unit, period, period_key, now),
        )

    def reserve(
        self,
        user_id: str,
        requested_units: int,
        policy: ResourceQuotaPolicy,
    ) -> ResourceQuotaLease | None:
        requested = max(0, int(requested_units))
        policy = policy.normalized()
        if requested == 0 or not policy.bounded:
            return None
        if policy.per_request_limit > 0 and requested > policy.per_request_limit:
            raise QuotaExceeded(
                resource=policy.resource,
                unit=policy.unit,
                period="per_request",
                limit=policy.per_request_limit,
                used=0,
                requested=requested,
            )

        daily_key, monthly_key = _period_keys()
        now = datetime.now(timezone.utc).isoformat()
        reservation_id = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for period, period_key in (("daily", daily_key), ("monthly", monthly_key)):
                self._ensure_period_row(
                    connection,
                    user_id=user_id,
                    resource=policy.resource,
                    unit=policy.unit,
                    period=period,
                    period_key=period_key,
                    now=now,
                )
            rows = {
                row["period"]: row
                for row in connection.execute(
                    """
                    SELECT period, consumed_units, reserved_units
                    FROM resource_usage
                    WHERE user_id = ? AND resource = ? AND period_key IN (?, ?)
                    """,
                    (user_id, policy.resource, daily_key, monthly_key),
                )
            }
            for period, limit in (
                ("daily", policy.daily_limit),
                ("monthly", policy.monthly_limit),
            ):
                if limit <= 0:
                    continue
                row = rows[period]
                used = int(row["consumed_units"]) + int(row["reserved_units"])
                if used + requested > limit:
                    raise QuotaExceeded(
                        resource=policy.resource,
                        unit=policy.unit,
                        period=period,
                        limit=limit,
                        used=used,
                        requested=requested,
                    )

            for period, period_key in (("daily", daily_key), ("monthly", monthly_key)):
                connection.execute(
                    """
                    UPDATE resource_usage
                    SET reserved_units = reserved_units + ?, updated_at = ?
                    WHERE user_id = ? AND resource = ? AND period = ? AND period_key = ?
                    """,
                    (
                        requested,
                        now,
                        user_id,
                        policy.resource,
                        period,
                        period_key,
                    ),
                )
            connection.execute(
                """
                INSERT INTO resource_reservations
                    (reservation_id, user_id, resource, unit, daily_key, monthly_key,
                     requested_units, state, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    reservation_id,
                    user_id,
                    policy.resource,
                    policy.unit,
                    daily_key,
                    monthly_key,
                    requested,
                    now,
                ),
            )
            connection.execute("COMMIT")
        except QuotaExceeded:
            connection.execute("ROLLBACK")
            raise
        except (OSError, sqlite3.Error) as exc:
            connection.execute("ROLLBACK")
            raise TokenQuotaUnavailable(f"resource quota reservation failed: {exc}") from exc
        finally:
            connection.close()
        return ResourceQuotaLease(self, reservation_id, requested)

    def finalize(self, reservation_id: str, actual_units: int) -> None:
        connection = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        try:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                """
                SELECT user_id, resource, daily_key, monthly_key, requested_units, state
                FROM resource_reservations WHERE reservation_id = ?
                """,
                (reservation_id,),
            ).fetchone()
            if reservation is None or reservation["state"] != "active":
                connection.execute("COMMIT")
                return
            requested = int(reservation["requested_units"])
            actual = max(0, int(actual_units))
            booked = max(requested, actual) if actual > requested else actual
            for period, period_key in (
                ("daily", reservation["daily_key"]),
                ("monthly", reservation["monthly_key"]),
            ):
                connection.execute(
                    """
                    UPDATE resource_usage
                    SET reserved_units = max(0, reserved_units - ?),
                        consumed_units = consumed_units + ?, updated_at = ?
                    WHERE user_id = ? AND resource = ? AND period = ? AND period_key = ?
                    """,
                    (
                        requested,
                        booked,
                        now,
                        reservation["user_id"],
                        reservation["resource"],
                        period,
                        period_key,
                    ),
                )
            connection.execute(
                """
                UPDATE resource_reservations
                SET state = 'finalized', finalized_at = ?
                WHERE reservation_id = ?
                """,
                (now, reservation_id),
            )
            connection.execute("COMMIT")
        except (OSError, sqlite3.Error) as exc:
            connection.execute("ROLLBACK")
            raise TokenQuotaUnavailable(f"resource quota finalization failed: {exc}") from exc
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


def current_user_resource_quota_policy(resource: str) -> ResourceQuotaPolicy | None:
    """Resolve a non-LLM resource policy; administrators are unlimited."""
    from .context import get_current_user
    from .grants import load_grant

    user = get_current_user()
    if user.is_admin:
        return None
    return resource_quota_policy_from_grant(load_grant(user.id), resource)


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


def reserve_current_user_units(
    *,
    resource: str,
    requested_units: int,
) -> ResourceQuotaLease | None:
    """Reserve Embedding tokens or MinerU pages for the current user."""
    from .context import get_current_user

    policy = current_user_resource_quota_policy(resource)
    if policy is None:
        return None
    return ResourceQuotaLedger().reserve(
        get_current_user().id,
        requested_units,
        policy,
    )


__all__ = [
    "DEFAULT_DAILY_TOKENS",
    "DEFAULT_MONTHLY_TOKENS",
    "QuotaExceeded",
    "ResourceQuotaLedger",
    "ResourceQuotaLease",
    "ResourceQuotaPolicy",
    "TokenQuotaExceeded",
    "TokenQuotaLedger",
    "TokenQuotaLease",
    "TokenQuotaPolicy",
    "TokenQuotaUnavailable",
    "current_user_quota_policy",
    "current_user_resource_quota_policy",
    "default_quota",
    "default_token_quota",
    "quota_db_path",
    "quota_policy_from_grant",
    "resource_quota_policy_from_grant",
    "reserve_current_user_units",
    "reserve_current_user_tokens",
]
