"""Tests for importing external chat histories into the session store.

Imported conversations share the session tables with native chats (so the chat
loop can re-open and continue them) but carry an ``imported_`` id prefix that
keeps them in their own category and out of the regular history list.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.session.sqlite_store import (
    SQLiteSessionStore,
    make_imported_session_id,
)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "test.db")


_MSGS = [
    {"role": "user", "content": "hi", "created_at": 1000.0},
    {"role": "assistant", "content": "hello", "created_at": 1001.0},
]


def _import(store: SQLiteSessionStore, ext: str = "abc", title: str = "Imported"):
    sid = make_imported_session_id("claude_code", ext)
    res = asyncio.run(
        store.import_session(
            sid, title, 1000.0, 1001.0, {"import": {"source": "claude_code"}}, _MSGS
        )
    )
    return sid, res


def test_make_imported_session_id_prefix_and_sanitize() -> None:
    assert make_imported_session_id("claude_code", "uuid-1").startswith("imported_claude_code_")
    unsafe = make_imported_session_id("x/y", "a/b.c")
    assert unsafe.startswith("imported_")
    assert "/" not in unsafe and "." not in unsafe


def test_import_then_list_filters_native_and_imported(store: SQLiteSessionStore) -> None:
    asyncio.run(store.create_session(title="Native", session_id="unified_1"))
    asyncio.run(store.add_message("unified_1", "user", "native msg"))

    sid, res = _import(store)
    assert res["imported"] is True
    assert res["message_count"] == 2

    native = asyncio.run(store.list_sessions(200, 0))
    imported = asyncio.run(store.list_imported_sessions(200, 0))
    assert [s["id"] for s in native] == ["unified_1"]
    assert [s["id"] for s in imported] == [sid]


def test_import_is_idempotent(store: SQLiteSessionStore) -> None:
    _, first = _import(store)
    _, second = _import(store)
    assert first["imported"] is True
    assert second["imported"] is False
    assert second["message_count"] == 0

    imported = asyncio.run(store.list_imported_sessions(200, 0))
    assert len(imported) == 1
    assert imported[0]["message_count"] == 2  # not doubled by the re-import


def test_imported_session_reopens_with_messages_and_prefs(
    store: SQLiteSessionStore,
) -> None:
    sid, _ = _import(store, title="My import")
    full = asyncio.run(store.get_session_with_messages(sid))
    assert full is not None
    assert full["title"] == "My import"
    assert [(m["role"], m["content"]) for m in full["messages"]] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]
    assert full["preferences"]["import"]["source"] == "claude_code"
    # Linear parent chain so the chat loop can resume the thread.
    assert full["messages"][0]["parent_message_id"] is None
    assert full["messages"][1]["parent_message_id"] == full["messages"][0]["id"]


def test_imported_timestamps_are_preserved(store: SQLiteSessionStore) -> None:
    sid, _ = _import(store)
    listed = asyncio.run(store.list_imported_sessions(200, 0))
    assert listed[0]["created_at"] == 1000.0
    assert listed[0]["updated_at"] == 1001.0
