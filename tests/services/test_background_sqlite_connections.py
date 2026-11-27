"""Background SQLite repositories release connections without waiting for GC."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.cron.repository import SQLiteCronRepository
from deeptutor.services.web_source.repository import SQLiteWebSourceSyncRepository


@pytest.fixture(params=[SQLiteCronRepository, SQLiteWebSourceSyncRepository])
def repository_type(
    request: pytest.FixtureRequest,
) -> type[SQLiteCronRepository] | type[SQLiteWebSourceSyncRepository]:
    """Exercise both repositories used by periodic background tasks."""
    return request.param


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[sqlite3.Connection]]:
    """Retain real connections so garbage collection cannot hide a missing close."""
    opened: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def track_connection(*args, **kwargs) -> sqlite3.Connection:
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connection)
    try:
        yield opened
    finally:
        # Also clean up when this regression test runs against the unfixed code.
        for connection in opened:
            connection.close()


def assert_closed(connections: list[sqlite3.Connection]) -> None:
    """Every returned connection must already reject database operations."""
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_polling_closes_every_connection(repository_type, connections, tmp_path: Path) -> None:
    """Initialization and repeated empty polling must not retain DB/WAL handles."""
    repository = repository_type(tmp_path / "jobs.sqlite")
    for _ in range(10):
        if isinstance(repository, SQLiteCronRepository):
            assert repository.revision() == 0
            assert repository.list_payloads() == []
        else:
            repository.reconcile_sources(set(), scanned_owner_ids={"local-admin"})
            assert repository.due_jobs() == []
    assert_closed(connections)


def test_failed_operation_closes_connection(repository_type, connections, tmp_path: Path) -> None:
    """An exception during a repository operation must release its connection."""
    repository = repository_type(tmp_path / "jobs.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        with repository._connect() as connection:
            connection.execute("SELECT * FROM nonexistent_table")
    assert_closed(connections)


@pytest.mark.parametrize("pragma", ["journal_mode", "busy_timeout", "synchronous"])
def test_failed_setup_closes_connection(
    repository_type, connections, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pragma: str
) -> None:
    """Close even when connection setup fails before the context yields."""
    repository = repository_type(tmp_path / "jobs.sqlite")
    connect = sqlite3.connect

    class SetupFailureConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith(f"PRAGMA {pragma}"):
                raise sqlite3.OperationalError("injected setup failure")
            return super().execute(sql, *args, **kwargs)

    def fail_setup(*args, **kwargs) -> sqlite3.Connection:
        return connect(*args, **kwargs, factory=SetupFailureConnection)

    monkeypatch.setattr(sqlite3, "connect", fail_setup)
    with pytest.raises(sqlite3.OperationalError, match="injected setup failure"):
        with repository._connect():
            pytest.fail("failed setup must not yield a connection")
    assert_closed(connections)


def test_connection_context_preserves_commit_and_rollback(
    repository_type, connections, tmp_path: Path
) -> None:
    """Closing must preserve the existing SQLite transaction context semantics."""
    repository = repository_type(tmp_path / "jobs.sqlite")
    with repository._connect() as connection:
        connection.execute("CREATE TABLE lifecycle_test (value INTEGER)")
        connection.execute("BEGIN")
        connection.execute("INSERT INTO lifecycle_test VALUES (1)")
    with pytest.raises(RuntimeError, match="abort transaction"):
        with repository._connect() as connection:
            connection.execute("BEGIN")
            connection.execute("INSERT INTO lifecycle_test VALUES (2)")
            raise RuntimeError("abort transaction")
    with repository._connect() as connection:
        rows = connection.execute("SELECT value FROM lifecycle_test").fetchall()
    assert [row[0] for row in rows] == [1]
    assert_closed(connections)
