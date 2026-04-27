from __future__ import annotations

from pathlib import Path

from deeptutor.services.session import (
    SessionStore,
    clear_session_store_cache,
    get_session_store,
    get_sqlite_session_store,
)
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_get_session_store_returns_sqlite_backend_for_explicit_backend(tmp_path: Path) -> None:
    store = get_session_store("sqlite", db_path=tmp_path / "session.db")

    assert isinstance(store, SQLiteSessionStore)
    assert isinstance(store, SessionStore)
    assert store.db_path == tmp_path / "session.db"


def test_get_sqlite_session_store_accepts_custom_path(tmp_path: Path) -> None:
    store = get_sqlite_session_store(db_path=tmp_path / "custom.db")

    assert isinstance(store, SQLiteSessionStore)
    assert store.db_path == tmp_path / "custom.db"


def test_get_session_store_rejects_unknown_backend() -> None:
    clear_session_store_cache()

    try:
        get_session_store("postgresql")
    except ValueError as exc:
        assert "Unsupported session backend" in str(exc)
    else:
        raise AssertionError("Expected get_session_store('postgresql') to fail")
