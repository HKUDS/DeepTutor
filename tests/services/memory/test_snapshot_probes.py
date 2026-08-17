"""Probe/full-read equivalence for the snapshot adapters.

A probe exists to skip reading content. That is only safe while it agrees with
its full adapter about *identity* — id, label and fingerprint — because the two
feed the same diff: a refresh driven by one and a refresh driven by the other
must not disagree about what changed. These tests pin that agreement, including
the case that motivates the probe's odd-looking SQL.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.memory.snapshot import adapters


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
        """
    )
    return conn


@pytest.fixture
def chat_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    db_path = tmp_path / "chat_history.db"
    conn = _make_db(db_path)
    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(db_path))
    yield conn
    conn.close()


def _stamps_of(entities) -> list[tuple[str, str, str]]:
    return [(e.id, e.label, e.fingerprint) for e in entities]


def test_probe_matches_full_read(chat_db: sqlite3.Connection) -> None:
    chat_db.executemany(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        [
            ("s1", "Chain rule", 1000.0, 1200.0),
            ("s2", "Agentic RAG", 900.0, 1100.0),
        ],
    )
    chat_db.executemany(
        "INSERT INTO messages (session_id, role, content, capability, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("s1", "user", "what is the chain rule", "chat", 1000.0),
            ("s1", "assistant", "it is...", "chat", 1010.0),
            ("s2", "user", "explain retrieval", "chat", 900.0),
        ],
    )
    chat_db.commit()

    assert _stamps_of(adapters.probe_chat_entities()) == _stamps_of(adapters.read_chat_entities())


def test_probe_matches_full_read_when_ids_and_timestamps_disagree(
    chat_db: sqlite3.Connection,
) -> None:
    """The case ``MAX(id)`` would get wrong.

    The full read orders by ``created_at ASC, id ASC`` and fingerprints the
    *last* row of that ordering. A backfilled message (higher id, earlier
    timestamp) is therefore not the one it picks — so a probe reaching for
    ``MAX(id)`` would fingerprint a different message and report a phantom
    change on every refresh.
    """
    chat_db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("s1", "Chain rule", 1000.0, 1200.0),
    )
    chat_db.executemany(
        "INSERT INTO messages (id, session_id, role, content, capability, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (10, "s1", "user", "asked first", "chat", 1000.0),
            (20, "s1", "assistant", "answered last", "chat", 1010.0),
            # Imported/backfilled after the fact: highest id, earliest stamp.
            (30, "s1", "user", "backfilled", "chat", 500.0),
        ],
    )
    chat_db.commit()

    probed = adapters.probe_chat_entities()
    full = adapters.read_chat_entities()
    assert _stamps_of(probed) == _stamps_of(full)
    # And specifically: not the highest id.
    assert probed[0].fingerprint == adapters._sha1(20, 1200.0)


def test_probe_stamps_empty_session_as_zero(chat_db: sqlite3.Connection) -> None:
    chat_db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("s1", "", 1000.0, 1000.0),
    )
    chat_db.commit()

    probed = adapters.probe_chat_entities()
    assert _stamps_of(probed) == _stamps_of(adapters.read_chat_entities())
    # Untitled sessions fall back to the id, in both readers.
    assert probed[0].label == "s1"
    assert probed[0].fingerprint == adapters._sha1(0, 1000.0)


def test_probe_returns_empty_without_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "nope.db"
    monkeypatch.setattr(adapters, "get_path_service", lambda: _FakePathService(missing))
    assert adapters.probe_chat_entities() == []


def test_read_stamps_falls_back_for_surfaces_without_a_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A surface with no probe is slower, never unsupported."""
    from deeptutor.services.memory.snapshot.entity import Entity

    monkeypatch.setitem(
        adapters._READERS,
        "book",
        lambda: [Entity(id="b1", label="Calculus", ts="2026-08-01T00:00:00+00:00", content="...")],
    )

    stamps = adapters.read_stamps("book")

    assert [(s.id, s.label) for s in stamps] == [("b1", "Calculus")]
    assert stamps[0].ts == "2026-08-01T00:00:00+00:00"


def test_read_stamps_falls_back_when_a_probe_raises(
    monkeypatch: pytest.MonkeyPatch, chat_db: sqlite3.Connection
) -> None:
    """A broken probe must not read as "the surface is empty" — the diff would
    take that for a mass deletion."""
    chat_db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("s1", "Chain rule", 1000.0, 1200.0),
    )
    chat_db.commit()

    def _boom() -> list:
        raise RuntimeError("probe exploded")

    monkeypatch.setitem(adapters._PROBES, "chat", _boom)

    stamps = adapters.read_stamps("chat")

    assert [s.label for s in stamps] == ["Chain rule"]
