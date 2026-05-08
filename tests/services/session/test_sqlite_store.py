from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_sqlite_store_defaults_to_data_user_chat_history_db(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"

        store = SQLiteSessionStore()

        assert store.db_path == tmp_path / "data" / "user" / "chat_history.db"
        assert store.db_path.exists()
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


def test_sqlite_store_migrates_legacy_chat_history_db(tmp_path: Path) -> None:
    service = PathService.get_instance()
    original_root = service._project_root
    original_user_dir = service._user_data_dir

    try:
        service._project_root = tmp_path
        service._user_data_dir = tmp_path / "data" / "user"
        legacy_db = tmp_path / "data" / "chat_history.db"
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(legacy_db) as conn:
            conn.execute("CREATE TABLE legacy (id INTEGER PRIMARY KEY)")
            conn.commit()

        store = SQLiteSessionStore()

        assert store.db_path.exists()
        assert not legacy_db.exists()
    finally:
        service._project_root = original_root
        service._user_data_dir = original_user_dir


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "test.db")


def _make_items(*specs):
    """Build notebook entry dicts from (qid, question, is_correct) tuples."""
    items = []
    for qid, question, is_correct in specs:
        items.append(
            {
                "question_id": qid,
                "question": question,
                "question_type": "choice",
                "options": {"A": "opt_a", "B": "opt_b"},
                "user_answer": "A",
                "correct_answer": "B",
                "explanation": "expl",
                "difficulty": "medium",
                "is_correct": is_correct,
            }
        )
    return items


# ── Notebook entries ──────────────────────────────────────────────


def test_upsert_notebook_entries_persists_all(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Test"))
    items = _make_items(("q1", "2+2?", False), ("q2", "3+3?", True), ("q3", "5+5?", False))
    upserted = asyncio.run(store.upsert_notebook_entries(session["id"], items))
    assert upserted == 3
    result = asyncio.run(store.list_notebook_entries())
    assert result["total"] == 3
    assert all(e["session_title"] == "Test" for e in result["items"])


def test_upsert_notebook_entries_updates_on_conflict(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    sid = session["id"]
    asyncio.run(store.upsert_notebook_entries(sid, _make_items(("q1", "Q?", False))))
    result = asyncio.run(store.list_notebook_entries())
    assert result["items"][0]["is_correct"] is False

    asyncio.run(
        store.upsert_notebook_entries(
            sid,
            [
                {
                    "question_id": "q1",
                    "question": "Q?",
                    "user_answer": "B",
                    "correct_answer": "B",
                    "is_correct": True,
                }
            ],
        )
    )
    result = asyncio.run(store.list_notebook_entries())
    assert result["total"] == 1
    assert result["items"][0]["is_correct"] is True
    assert result["items"][0]["user_answer"] == "B"


def test_upsert_skips_blank_questions(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    items = [
        {"question_id": "q1", "question": "", "is_correct": False},
        {"question_id": "", "question": "Valid?", "is_correct": False},
        {"question_id": "q3", "question": "OK?", "is_correct": False},
    ]
    upserted = asyncio.run(store.upsert_notebook_entries(session["id"], items))
    assert upserted == 1


def test_upsert_unknown_session_raises(store: SQLiteSessionStore) -> None:
    with pytest.raises(ValueError, match="Session not found"):
        asyncio.run(store.upsert_notebook_entries("nope", _make_items(("q1", "Q?", False))))


def test_list_entries_filters_bookmarked(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            _make_items(
                ("q1", "Q1?", False),
                ("q2", "Q2?", True),
            ),
        )
    )
    entries = asyncio.run(store.list_notebook_entries())["items"]
    asyncio.run(store.update_notebook_entry(entries[0]["id"], {"bookmarked": True}))
    bm = asyncio.run(store.list_notebook_entries(bookmarked=True))
    assert bm["total"] == 1
    assert bm["items"][0]["bookmarked"] is True


def test_list_entries_filters_is_correct(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            _make_items(
                ("q1", "Q1?", False),
                ("q2", "Q2?", True),
            ),
        )
    )
    wrong = asyncio.run(store.list_notebook_entries(is_correct=False))
    assert wrong["total"] == 1
    assert wrong["items"][0]["question_id"] == "q1"


def test_update_notebook_entry_bookmark_roundtrip(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    assert asyncio.run(store.update_notebook_entry(eid, {"bookmarked": True})) is True
    assert asyncio.run(store.get_notebook_entry(eid))["bookmarked"] is True
    assert asyncio.run(store.update_notebook_entry(eid, {"bookmarked": False})) is True
    assert asyncio.run(store.get_notebook_entry(eid))["bookmarked"] is False
    assert asyncio.run(store.update_notebook_entry(99999, {"bookmarked": True})) is False


def test_update_followup_session_id(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    asyncio.run(store.update_notebook_entry(eid, {"followup_session_id": "sess_fu"}))
    entry = asyncio.run(store.get_notebook_entry(eid))
    assert entry["followup_session_id"] == "sess_fu"


def test_find_notebook_entry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    found = asyncio.run(store.find_notebook_entry(session["id"], "q1"))
    assert found is not None
    assert found["question_id"] == "q1"
    assert asyncio.run(store.find_notebook_entry(session["id"], "nope")) is None


def test_delete_notebook_entry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            _make_items(
                ("q1", "Q1?", False),
                ("q2", "Q2?", False),
            ),
        )
    )
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    assert asyncio.run(store.delete_notebook_entry(eid)) is True
    assert asyncio.run(store.list_notebook_entries())["total"] == 1
    assert asyncio.run(store.delete_notebook_entry(99999)) is False


def test_entries_cascade_on_session_delete(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    assert asyncio.run(store.list_notebook_entries())["total"] == 1
    asyncio.run(store.delete_session(session["id"]))
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


# ── Categories ────────────────────────────────────────────────────


def test_category_crud(store: SQLiteSessionStore) -> None:
    cat = asyncio.run(store.create_category("Math"))
    assert cat["name"] == "Math"
    cats = asyncio.run(store.list_categories())
    assert len(cats) == 1
    assert cats[0]["entry_count"] == 0

    asyncio.run(store.rename_category(cat["id"], "Algebra"))
    cats = asyncio.run(store.list_categories())
    assert cats[0]["name"] == "Algebra"

    asyncio.run(store.delete_category(cat["id"]))
    assert asyncio.run(store.list_categories()) == []


def test_entry_category_association(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    cat = asyncio.run(store.create_category("Physics"))

    assert asyncio.run(store.add_entry_to_category(eid, cat["id"])) is True
    entry = asyncio.run(store.get_notebook_entry(eid))
    assert len(entry["categories"]) == 1
    assert entry["categories"][0]["name"] == "Physics"

    by_cat = asyncio.run(store.list_notebook_entries(category_id=cat["id"]))
    assert by_cat["total"] == 1

    asyncio.run(store.remove_entry_from_category(eid, cat["id"]))
    assert asyncio.run(store.get_entry_categories(eid)) == []


def test_category_cascade_on_entry_delete(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]
    cat = asyncio.run(store.create_category("History"))
    asyncio.run(store.add_entry_to_category(eid, cat["id"]))
    asyncio.run(store.delete_notebook_entry(eid))
    cats = asyncio.run(store.list_categories())
    assert cats[0]["entry_count"] == 0
