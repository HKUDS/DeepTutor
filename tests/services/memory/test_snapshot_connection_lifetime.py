"""Snapshot readers release their SQLite connections before returning."""

from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.mark.parametrize(
    "reader", ["read_chat_entities", "read_quiz_entities", "probe_chat_entities"]
)
def test_snapshot_reader_closes_connection(tmp_path: Path, monkeypatch, reader: str) -> None:
    """Keep native handles alive so garbage collection cannot mask a leak."""
    database = tmp_path / "history.db"
    SQLiteSessionStore(database)
    monkeypatch.setattr(
        adapters, "get_path_service", lambda: SimpleNamespace(get_chat_history_db=lambda: database)
    )
    connect = sqlite3.connect
    connections = []

    def track_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track_connection)
    try:
        assert getattr(adapters, reader)() == []
        assert len(connections) == 1
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        database.rename(tmp_path / "moved.db")
    finally:
        for connection in connections:
            connection.close()
