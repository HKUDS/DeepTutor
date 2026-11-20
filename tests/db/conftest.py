"""Fixtures for the Phase 3 data-layer tests.

Two engines, one suite. Every behavioural test is parametrised over:

* ``sqlite`` — always available, runs everywhere including CI
* ``postgres`` — only when ``DEEPTUTOR_TEST_DATABASE_URL`` points at a real
  Postgres (see ``tests/db/README.md`` for how to run it against Supabase)

The SQLite run is not a lesser substitute: it is the regression net that runs on
every commit. The Postgres run is the evidence that the same SQL is portable,
and it is skipped-not-failed when unavailable so a contributor without a
database can still run the suite.
"""

from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest

from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.connection import Database, DatabaseUnavailable, open_database
from deeptutor.db.migrate import apply_pending

TEST_DSN_ENV = "DEEPTUTOR_TEST_DATABASE_URL"


def _postgres_available() -> bool:
    return bool(os.environ.get(TEST_DSN_ENV))


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, tmp_path) -> Database:
    """A migrated, empty database on the requested engine."""
    if request.param == "postgres":
        if not _postgres_available():
            pytest.skip(f"{TEST_DSN_ENV} not configured")
        dsn = os.environ[TEST_DSN_ENV]
        # Every test gets its own schema so a run cannot collide with another
        # run, or with the tables the application actually uses.
        schema = f"test_{uuid.uuid4().hex[:12]}"
        settings = DatabaseSettings(app_url=dsn, migration_url=dsn, backend="postgres")
        admin = Database(settings)
        with admin.transaction() as conn:
            conn.execute(f"CREATE SCHEMA {schema}")
        scoped = _with_search_path(dsn, schema)
        database = Database(
            DatabaseSettings(app_url=scoped, migration_url=scoped, backend="postgres")
        )
        try:
            apply_pending(database)
            yield database
        finally:
            database.close()
            with admin.transaction() as conn:
                conn.execute(f"DROP SCHEMA {schema} CASCADE")
            admin.close()
        return

    path = tmp_path / "test.db"
    settings = DatabaseSettings(app_url=f"sqlite:///{path}", backend="sqlite")
    database = Database(settings)
    apply_pending(database)
    try:
        yield database
    finally:
        database.close()


def _with_search_path(dsn: str, schema: str) -> str:
    separator = "&" if "?" in dsn else "?"
    return f"{dsn}{separator}options=-csearch_path%3D{schema},public"


@pytest.fixture
def sqlite_db(tmp_path) -> Database:
    """SQLite only — for tests that assert engine-specific behaviour."""
    path = tmp_path / "plain.db"
    database = Database(DatabaseSettings(app_url=f"sqlite:///{path}", backend="sqlite"))
    apply_pending(database)
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def temp_home(tmp_path, monkeypatch) -> Path:
    """Isolated runtime home so storage never touches the developer's data."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("DEEPTUTOR_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _reset_caches():
    """Config caches must not leak between tests."""
    reset_database_settings(None)
    yield
    reset_database_settings(None)


__all__ = ["DatabaseUnavailable", "open_database", "TEST_DSN_ENV"]
