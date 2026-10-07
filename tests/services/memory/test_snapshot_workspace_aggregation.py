"""Account-level Memory aggregation across workspaces (#1799).

Memory L1 is documented as account-level shared, but the chat/quiz adapters
used to read only the currently scoped workspace's chat-history DB, so
conversations started inside a custom workspace were invisible to Memory.
These tests pin the aggregation contract:

- the default workspace keeps **bare** session ids — renumbering them would
  churn every existing snapshot;
- additional registered workspaces contribute their sessions under a
  ``ws:<workspace_id>:`` qualifier with workspace provenance in metadata;
- a probe and its full read must agree on identity across workspaces;
- a broken binding is skipped (fail-open) and never blanks the scan.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.services.memory.snapshot import adapters
from deeptutor.services.path_service import PathService


class _FakePathService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def get_chat_history_db(self) -> Path:
        return self._db_path


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            capability TEXT,
            created_at REAL
        );
        CREATE TABLE notebook_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            turn_id TEXT,
            question_id TEXT,
            question TEXT,
            question_type TEXT,
            options_json TEXT,
            correct_answer TEXT,
            explanation TEXT,
            difficulty TEXT,
            user_answer TEXT,
            is_correct INTEGER,
            bookmarked INTEGER,
            created_at REAL
        );
        """
    )
    return conn


def _add_session(
    conn: sqlite3.Connection, sid: str, title: str, *, question: str | None = None
) -> None:
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, 1000.0, 1200.0)",
        (sid, title),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, capability, created_at) "
        "VALUES (?, 'user', ?, 'chat', 1100.0)",
        (sid, f"about {title}"),
    )
    if question is not None:
        conn.execute(
            "INSERT INTO notebook_entries (session_id, turn_id, question_id, question, "
            "question_type, correct_answer, user_answer, is_correct, bookmarked, created_at) "
            "VALUES (?, 't1', 'q1', ?, 'choice', 'A', 'B', 0, 0, 1150.0)",
            (sid, question),
        )
    # The adapters read through a *separate* read-only connection; uncommitted
    # rows would be invisible to it.
    conn.commit()


def _binding(workspace_id: str, ws_root: Path) -> SimpleNamespace:
    return SimpleNamespace(workspace_id=workspace_id, root=ws_root, display_name=workspace_id)


def _workspace_data_root(ws_root: Path) -> Path:
    # Mirror WorkspacePathService: data lives under <content_root>/.deeptutor/data.
    return ws_root / ".deeptutor" / "data"


def _with_bindings(
    monkeypatch: pytest.MonkeyPatch,
    default_db: Path,
    bindings: list[SimpleNamespace],
) -> None:
    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(default_db))
    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service",
        lambda: SimpleNamespace(registered_bindings=lambda: bindings),
    )


@pytest.fixture
def default_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    db_path = tmp_path / "default" / "chat_history.db"
    db_path.parent.mkdir(parents=True)
    conn = _make_db(db_path)
    _with_bindings(monkeypatch, db_path, [])
    yield conn
    conn.close()


def test_default_workspace_ids_stay_bare(default_db: sqlite3.Connection) -> None:
    _add_session(default_db, "s1", "Chain rule")

    entities = adapters.read_chat_entities()

    assert [e.id for e in entities] == ["s1"]  # bare id — no snapshot churn


def test_custom_workspace_sessions_are_aggregated_with_provenance(
    tmp_path: Path, default_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws_root = tmp_path / "ws-thesis"
    db_path = PathService(workspace_root=_workspace_data_root(ws_root)).get_chat_history_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ws_conn = _make_db(db_path)
    try:
        _add_session(default_db, "s-default", "Default chat")
        _add_session(ws_conn, "s1", "Thesis chapter")
        _with_bindings(
            monkeypatch,
            tmp_path / "default" / "chat_history.db",
            [_binding("ws_abc123", ws_root)],
        )

        entities = adapters.read_chat_entities()
    finally:
        ws_conn.close()

    by_id = {e.id: e for e in entities}
    # Both workspaces visible; the same session id in two workspaces never
    # collides because the custom one is qualified.
    assert set(by_id) == {"s-default", "ws:ws_abc123:s1"}
    qualified = by_id["ws:ws_abc123:s1"]
    assert qualified.label == "Thesis chapter"
    assert qualified.metadata["workspace_id"] == "ws_abc123"
    # The default workspace entry stays bare.
    assert by_id["s-default"].metadata.get("workspace_id") is None


def test_quiz_entities_carry_the_same_qualifier(
    tmp_path: Path, default_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws_root = tmp_path / "ws-quiz"
    db_path = PathService(workspace_root=_workspace_data_root(ws_root)).get_chat_history_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ws_conn = _make_db(db_path)
    try:
        _add_session(ws_conn, "s9", "Quiz chapter", question="What is entropy?")
        _with_bindings(
            monkeypatch,
            tmp_path / "default" / "chat_history.db",
            [_binding("ws_quiz1", ws_root)],
        )

        entities = adapters.read_quiz_entities()
    finally:
        ws_conn.close()

    assert [e.id for e in entities] == ["ws:ws_quiz1:s9:q1"]
    assert entities[0].metadata["workspace_id"] == "ws_quiz1"


def test_probe_agrees_with_full_read_across_workspaces(
    tmp_path: Path, default_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws_root = tmp_path / "ws-probe"
    db_path = PathService(workspace_root=_workspace_data_root(ws_root)).get_chat_history_db()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ws_conn = _make_db(db_path)
    try:
        _add_session(default_db, "s-default", "Default chat")
        _add_session(ws_conn, "s1", "Shared id across workspaces")
        _with_bindings(
            monkeypatch,
            tmp_path / "default" / "chat_history.db",
            [_binding("ws_p1", ws_root)],
        )

        full = adapters.read_chat_entities()
        probe = adapters.probe_chat_entities()
    finally:
        ws_conn.close()

    assert sorted(e.id for e in full) == ["s-default", "ws:ws_p1:s1"]
    assert sorted(e.id for e in probe) == ["s-default", "ws:ws_p1:s1"]


def test_broken_binding_is_skipped_fail_open(
    tmp_path: Path, default_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_session(default_db, "s1", "Still visible")
    # A binding whose data store does not exist (moved / never provisioned)
    # contributes nothing but must not blank the account-wide scan. (The
    # symlink-refusal branch mirrors WorkspacePathService and cannot be
    # exercised here — creating symlinks on Windows needs privileges.)
    _with_bindings(
        monkeypatch,
        tmp_path / "default" / "chat_history.db",
        [_binding("ws_broken", tmp_path / "ws-broken")],
    )

    entities = adapters.read_chat_entities()

    ids = [e.id for e in entities]
    assert "s1" in ids
    assert not any(i.startswith("ws:") for i in ids)
    missing = PathService(
        workspace_root=_workspace_data_root(tmp_path / "ws-broken")
    ).get_chat_history_db()
    assert not missing.exists()


def test_enumeration_failure_falls_back_to_default_only(
    tmp_path: Path, default_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_session(default_db, "s1", "Chain rule")
    monkeypatch.setattr(
        "deeptutor.services.workspace.get_content_workspace_service",
        lambda: (_ for _ in ()).throw(RuntimeError("registry unreadable")),
    )

    entities = adapters.read_chat_entities()

    assert [e.id for e in entities] == ["s1"]
