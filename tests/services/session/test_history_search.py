from __future__ import annotations

import asyncio
import sqlite3

from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def run(coro):
    return asyncio.run(coro)


def test_searches_full_visible_transcript_and_returns_latest_match(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "history.db")
    session = run(store.create_session(title="Probability notes", session_id="native"))
    first_id = run(store.add_message(session["id"], "user", "Explain Bayes theorem slowly"))
    latest_id = run(store.add_message(session["id"], "assistant", "A later BAYES theorem recap"))
    run(store.add_message(session["id"], "system", "Bayes provider metadata"))

    result = run(store.search_sessions("bayes", limit=10, offset=0))

    assert result["total"] == 1
    [match] = result["sessions"]
    assert match["session_id"] == "native"
    assert match["match_message_id"] == latest_id
    assert match["match_message_id"] != first_id
    assert match["match_role"] == "assistant"
    assert "BAYES theorem" in match["match_excerpt"]
    assert len(match["match_excerpt"]) <= 320


def test_search_is_literal_paginated_and_preserves_history_visibility(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "history.db")
    first = run(store.create_session(title="100%_literal", session_id="first"))
    second = run(store.create_session(title="Second", session_id="second"))
    archived = run(store.create_session(title="Archived", session_id="archived"))
    imported = run(store.create_session(title="Imported", session_id="imported_codex_hidden"))
    run(store.add_message(second["id"], "user", "also 100%_literal here"))
    run(store.add_message(archived["id"], "assistant", "100%_literal archived match"))
    run(store.update_session_preferences(archived["id"], {"archived": True}))
    run(store.add_message(imported["id"], "user", "100%_literal imported match"))

    with sqlite3.connect(store.db_path) as conn:
        conn.executemany(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            [(40, first["id"]), (30, second["id"]), (20, archived["id"])],
        )

    first_page = run(store.search_sessions("%_", limit=2, offset=0))
    second_page = run(store.search_sessions("%_", limit=2, offset=2))

    assert first_page["total"] == 3
    assert [row["session_id"] for row in first_page["sessions"]] == ["first", "second"]
    assert first_page["sessions"][0]["match_message_id"] is None
    assert first_page["sessions"][0]["match_excerpt"] == "100%_literal"
    assert [row["session_id"] for row in second_page["sessions"]] == ["archived"]
    assert second_page["sessions"][0]["preferences"]["archived"] is True


def test_search_ignores_system_only_matches_and_empty_queries(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "history.db")
    session = run(store.create_session(title="Unrelated", session_id="system-only"))
    run(store.add_message(session["id"], "system", "private needle"))

    assert run(store.search_sessions("needle")) == {"sessions": [], "total": 0}
    assert run(store.search_sessions("   ")) == {"sessions": [], "total": 0}
