"""Product database layer: connection, migrations, repositories and jobs.

Design constraints (see ``docs/darsyar/ADR-003-POSTGRES-DATA-LAYER.md``):

* The production target is **PostgreSQL** (Supabase). The data layer must not
  assume Postgres-only SQL where a portable spelling exists, because the test
  suite runs against SQLite as a harness — CI has no Postgres.
* PostgreSQL is **optional at import time**. ``psycopg`` is imported lazily so a
  deployment without the driver still boots and fails only where a database is
  actually required.
* Nothing in this package silently replaces an existing file/JSON store. The
  file-backed stores stay authoritative until a repository is explicitly wired
  and its backfill has run (ROADMAP Phase 3: "existing file/JSON models must not
  be silently deleted").
"""

from __future__ import annotations

from deeptutor.db.config import DatabaseSettings, get_database_settings, reset_database_settings
from deeptutor.db.connection import (
    Connection,
    Database,
    DatabaseUnavailable,
    open_database,
)
from deeptutor.db.migrate import (
    MigrationError,
    applied_migrations,
    apply_pending,
    discover_migrations,
    rollback_to,
)

__all__ = [
    "Connection",
    "Database",
    "DatabaseSettings",
    "DatabaseUnavailable",
    "MigrationError",
    "applied_migrations",
    "apply_pending",
    "discover_migrations",
    "get_database_settings",
    "open_database",
    "reset_database_settings",
    "rollback_to",
]
