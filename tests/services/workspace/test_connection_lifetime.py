"""Workspace database helpers release handles before migration continues."""

from contextlib import closing
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.services.workspace import data_migration, dependencies


@pytest.mark.parametrize(
    "operation", ["snapshot", "restore", "rebind", "scaffold", "sessions", "questions"]
)
def test_workspace_helpers_close_database_connections(tmp_path, monkeypatch, operation):
    source = tmp_path / "source.sqlite"
    destination = tmp_path / "copy.sqlite"
    connect = sqlite3.connect
    with closing(connect(source)) as conn, conn:
        conn.execute("CREATE TABLE sessions (id TEXT, title TEXT, preferences_json TEXT)")
        conn.execute("CREATE TABLE notebook_entries (id TEXT, session_id TEXT)")
        conn.execute("CREATE TABLE links (url TEXT)")
        if operation != "scaffold":
            conn.execute("INSERT INTO sessions VALUES ('session-one', 'Title', '{}')")
            conn.execute("INSERT INTO notebook_entries VALUES ('question-one', 'session-one')")
            conn.execute("INSERT INTO links VALUES ('/files/outputs/result.txt')")
    connections = []

    def tracked_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    paths = SimpleNamespace(get_chat_history_db=lambda: source)
    if operation == "snapshot":
        manifest = data_migration._snapshot(source, tmp_path / "snapshot")
        assert source.name in manifest
        destination = tmp_path / "snapshot" / source.name
    elif operation == "restore":
        data_migration._restore_database(source, destination)
    elif operation == "rebind":
        data_migration._rebind_feature_urls(source, "workspace-one")
        with closing(connect(source)) as conn:
            assert (
                conn.execute("SELECT url FROM links").fetchone()[0] != "/files/outputs/result.txt"
            )
    elif operation == "scaffold":
        assert data_migration._empty_scaffold(source)
    elif operation == "sessions":
        assert data_migration._sqlite_sessions(paths)[0]["id"] == "session-one"
    else:
        assert dependencies._question_sessions(paths) == {"session-one"}
    assert connections
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")
    if operation in {"snapshot", "restore"}:
        with closing(connect(destination)) as conn:
            assert conn.execute("SELECT id FROM sessions").fetchone() == ("session-one",)
    source.rename(tmp_path / "released.sqlite")
