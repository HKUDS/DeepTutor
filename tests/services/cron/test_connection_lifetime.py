"""Cron persistence releases SQLite resources after successful and failed work."""

from pathlib import Path
import sqlite3
from typing import Any

import pytest

from deeptutor.services.cron.repository import SQLiteCronRepository


@pytest.mark.parametrize(
    "operation", ["initialize", "revision", "list", "upsert", "delete", "delete_owner", "failure"]
)
def test_repository_closes_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Retaining real connections must not keep handles open after repository calls."""
    connections: list[sqlite3.Connection] = []
    original_connect = sqlite3.connect

    def track_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connect)
    try:
        repo = SQLiteCronRepository(tmp_path / "jobs.sqlite3")
        if operation == "revision":
            assert repo.revision() == 0
        elif operation == "list":
            assert repo.list_payloads() == []
        elif operation == "upsert":
            repo.upsert({"id": "job"})
        elif operation == "delete":
            assert not repo.delete("missing")
        elif operation == "delete_owner":
            assert repo.delete_owner("chat:missing") == 0
        elif operation == "failure":
            with pytest.raises(ValueError, match="id is required"):
                repo.upsert({})
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        # On Windows an open SQLite handle prevents this ordinary file operation.
        repo.path.replace(tmp_path / "moved.sqlite3")
    finally:
        for connection in connections:
            connection.close()
