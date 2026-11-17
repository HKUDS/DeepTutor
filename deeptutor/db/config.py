"""Database configuration resolved from the environment.

The layer is deliberately opt-in. Without ``DEEPTUTOR_DATABASE_URL`` the app
runs exactly as it did before Phase 3: file/JSON stores only, no database
connection attempted. Setting the URL (a ``postgresql://`` DSN) switches the
product data layer on.

Two URLs are meaningful:

``DEEPTUTOR_DATABASE_URL``
    Application role. Used for every request-time query. Should be a
    least-privilege role; it must not own the schema in production.

``DEEPTUTOR_MIGRATION_DATABASE_URL``
    Migration role. Used by :func:`deeptutor.db.migrate.apply_pending` and the
    ``python -m deeptutor.db.migrations`` CLI. Falls back to the application URL
    when unset, which is fine for a single-developer Supabase project but must
    be split for production so the application cannot alter its own schema.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

APP_URL_ENV = "DEEPTUTOR_DATABASE_URL"
MIGRATION_URL_ENV = "DEEPTUTOR_MIGRATION_DATABASE_URL"
POOL_SIZE_ENV = "DEEPTUTOR_DATABASE_POOL_SIZE"
STATEMENT_TIMEOUT_ENV = "DEEPTUTOR_DATABASE_STATEMENT_TIMEOUT_MS"


class DatabaseConfigError(ValueError):
    """The configured DSN is structurally unusable."""


def redact_dsn(dsn: str) -> str:
    """Return *dsn* with the password removed.

    Every log line, error message and health payload that mentions a DSN must
    go through this. A leaked Supabase password in a log is a full database
    compromise, and the Phase 2 rule "no raw secret in DB/log/trace" applies to
    connection strings too.
    """
    if not dsn:
        return ""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return "<unparseable-dsn>"
    if not parts.password:
        return dsn
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@dataclass(frozen=True)
class DatabaseSettings:
    """Resolved database configuration.

    ``app_url`` is empty when the database layer is disabled, which is the
    default. :attr:`enabled` is the single switch every call-site checks.
    """

    app_url: str = ""
    migration_url: str = ""
    pool_size: int = 5
    statement_timeout_ms: int = 30_000
    backend: str = "sqlite"

    @property
    def enabled(self) -> bool:
        return bool(self.app_url)

    @property
    def is_postgres(self) -> bool:
        return self.backend == "postgres"

    @property
    def safe_app_dsn(self) -> str:
        """The application DSN with the password replaced by ``***``."""
        return redact_dsn(self.app_url)

    def describe(self) -> dict[str, object]:
        """Non-secret summary for health and readiness payloads."""
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "host": urlsplit(self.app_url).hostname or "",
            "pool_size": self.pool_size,
            "statement_timeout_ms": self.statement_timeout_ms,
            "migration_url_configured": bool(self.migration_url),
        }


def _detect_backend(dsn: str) -> str:
    scheme = urlsplit(dsn).scheme.lower()
    if scheme in {"postgres", "postgresql"}:
        return "postgres"
    if scheme in {"sqlite", "sqlite3"}:
        return "sqlite"
    raise DatabaseConfigError(
        f"unsupported database scheme {scheme!r}; expected postgresql:// or sqlite://"
    )


def _coerce_int(raw: str | None, default: int, *, name: str) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise DatabaseConfigError(f"{name} must be positive, got {value}")
    return value


def load_database_settings(env: Mapping[str, str] | None = None) -> DatabaseSettings:
    """Build :class:`DatabaseSettings` from *env* (defaults to ``os.environ``)."""
    source = os.environ if env is None else env
    app_url = (source.get(APP_URL_ENV) or "").strip()
    if not app_url:
        return DatabaseSettings()
    backend = _detect_backend(app_url)
    migration_url = (source.get(MIGRATION_URL_ENV) or "").strip() or app_url
    if _detect_backend(migration_url) != backend:
        raise DatabaseConfigError(
            "migration URL backend does not match the application URL backend"
        )
    return DatabaseSettings(
        app_url=app_url,
        migration_url=migration_url,
        pool_size=_coerce_int(source.get(POOL_SIZE_ENV), 5, name=POOL_SIZE_ENV),
        statement_timeout_ms=_coerce_int(
            source.get(STATEMENT_TIMEOUT_ENV), 30_000, name=STATEMENT_TIMEOUT_ENV
        ),
        backend=backend,
    )


_CACHED: DatabaseSettings | None = None


def get_database_settings() -> DatabaseSettings:
    """Process-wide settings, resolved once.

    Cached because callers use it on hot paths; tests use
    :func:`reset_database_settings` after monkeypatching the environment.
    """
    global _CACHED
    if _CACHED is None:
        _CACHED = load_database_settings()
    return _CACHED


def reset_database_settings(settings: DatabaseSettings | None = None) -> None:
    """Drop the cache, optionally pinning *settings* (used by tests)."""
    global _CACHED
    _CACHED = settings
