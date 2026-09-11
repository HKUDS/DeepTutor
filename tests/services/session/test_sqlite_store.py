from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
import time

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


def test_store_migrates_legacy_notebook_review_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-notebook.db"
    now = time.time()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                compressed_summary TEXT DEFAULT '',
                summary_up_to_msg_id INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE notebook_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL DEFAULT '',
                question_id TEXT NOT NULL,
                question TEXT NOT NULL,
                question_type TEXT DEFAULT '',
                options_json TEXT DEFAULT '{}',
                correct_answer TEXT DEFAULT '',
                explanation TEXT DEFAULT '',
                difficulty TEXT DEFAULT '',
                user_answer TEXT DEFAULT '',
                user_answer_images_json TEXT DEFAULT '[]',
                is_correct INTEGER DEFAULT 0,
                bookmarked INTEGER DEFAULT 0,
                followup_session_id TEXT DEFAULT '',
                ai_judgment TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(session_id, turn_id, question_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notebook_entries (
                session_id,
                turn_id,
                question_id,
                question,
                is_correct,
                created_at,
                updated_at
            ) VALUES ('session-1', '', 'q1', 'Legacy?', 0, ?, ?)
            """,
            (now, now),
        )
        conn.commit()

    store = SQLiteSessionStore(db_path=db_path)
    listing = asyncio.run(store.list_notebook_entries())

    assert listing["total"] == 1
    entry = listing["items"][0]
    assert entry["source"] == "deep_question"
    assert entry["score_trend"] == "new"
    assert entry["resolved"] is False
    assert all(not entry[key] for key in ("material_id", "section_id"))
    with sqlite3.connect(db_path) as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(notebook_entries)")}
    assert "idx_notebook_entries_review" in indexes


def test_store_migrates_legacy_workspace_ownership_without_reordering(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-workspaces.db"
    rows = [
        (
            "mastery",
            50.0,
            {"capability": "mastery_path", "mastery_path_id": "topic-1"},
        ),
        (
            "reading",
            40.0,
            {
                "capability": "immersive_reading",
                "session_kind": "immersive_reading",
                "reading_workspace_id": "reading-1",
            },
        ),
        (
            "stale-chat",
            30.0,
            {"capability": "chat", "mastery_path_id": "topic-stale"},
        ),
        (
            "left-workspace",
            20.0,
            {
                "capability": "mastery_path",
                "mastery_path_id": "topic-old",
                "workspace_mode": "",
            },
        ),
    ]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'New conversation',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                compressed_summary TEXT DEFAULT '',
                summary_up_to_msg_id INTEGER DEFAULT 0,
                preferences_json TEXT DEFAULT '{}'
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, preferences_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (session_id, session_id, updated_at, updated_at, json.dumps(preferences))
                for session_id, updated_at, preferences in rows
            ],
        )

    store = SQLiteSessionStore(db_path=db_path)
    listed = asyncio.run(store.list_sessions())
    by_id = {row["id"]: row for row in listed}

    assert [row["id"] for row in listed] == [row[0] for row in rows]
    assert by_id["mastery"]["preferences"]["workspace_mode"] == "mastery_path"
    assert by_id["reading"]["preferences"]["workspace_mode"] == "immersive_reading"
    assert "workspace_mode" not in by_id["stale-chat"]["preferences"]
    assert by_id["left-workspace"]["preferences"]["workspace_mode"] == ""
    with sqlite3.connect(db_path) as conn:
        timestamps = dict(conn.execute("SELECT id, updated_at FROM sessions").fetchall())
    assert timestamps == {session_id: updated_at for session_id, updated_at, _ in rows}


@pytest.mark.asyncio
async def test_explicit_workspace_migration_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "startup-migration.db")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, preferences_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "late-legacy",
                "late-legacy",
                10.0,
                20.0,
                json.dumps({"capability": "mastery_path", "mastery_path_id": "topic-late"}),
            ),
        )

    assert await store.migrate_workspace_preferences() == 1
    assert await store.migrate_workspace_preferences() == 0
    session = await store.get_session("late-legacy")

    assert session is not None
    assert session["preferences"]["workspace_mode"] == "mastery_path"
    assert session["updated_at"] == 20.0


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


def test_get_session_summaries_batches_counts_and_latest_visible_message(
    store: SQLiteSessionStore,
) -> None:
    first = asyncio.run(store.create_session(title="First", session_id="session-1"))
    second = asyncio.run(store.create_session(title="Second", session_id="session-2"))
    asyncio.run(store.add_message(first["id"], "system", "private setup"))
    asyncio.run(store.add_message(first["id"], "user", "First question"))
    asyncio.run(store.add_message(first["id"], "assistant", "Latest answer"))
    asyncio.run(store.add_message(second["id"], "system", "system only"))

    summaries = asyncio.run(store.get_session_summaries([first["id"], second["id"], first["id"]]))
    by_id = {summary["session_id"]: summary for summary in summaries}

    assert by_id[first["id"]]["message_count"] == 2
    assert by_id[first["id"]]["last_message"] == "Latest answer"
    assert by_id[second["id"]]["message_count"] == 0
    assert by_id[second["id"]]["last_message"] == ""


def test_generic_history_lists_immersive_reading_sessions_with_their_collection(
    store: SQLiteSessionStore,
) -> None:
    """Reading conversations are listed, carrying where they belong.

    They used to be filtered out of history entirely, which left a learner no
    route back to one except by reopening its collection. They are listed now,
    and the sidebar files them under their collection — which only works if
    both routing signals survive the summary, so assert on those rather than
    merely on the row being present.
    """
    chat = asyncio.run(store.create_session(title="Regular chat"))
    reading = asyncio.run(store.create_session(title="Reading conversation"))
    asyncio.run(
        store.update_session_preferences(
            reading["id"],
            {
                "session_kind": "immersive_reading",
                "reading_workspace_id": "rw_private",
            },
        )
    )

    listed = asyncio.run(store.list_sessions())

    assert {row["id"] for row in listed} == {chat["id"], reading["id"]}
    row = next(row for row in listed if row["id"] == reading["id"])
    assert row["preferences"]["session_kind"] == "immersive_reading"
    assert row["preferences"]["reading_workspace_id"] == "rw_private"
    assert row["preferences"]["workspace_mode"] == "immersive_reading"


# ── Notebook entries ──────────────────────────────────────────────


def test_upsert_notebook_entries_persists_all(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Test"))
    items = _make_items(("q1", "2+2?", False), ("q2", "3+3?", True), ("q3", "5+5?", False))
    upserted = asyncio.run(store.upsert_notebook_entries(session["id"], items))
    assert upserted == 3
    result = asyncio.run(store.list_notebook_entries())
    assert result["total"] == 3
    assert all(e["session_title"] == "Test" for e in result["items"])


def test_list_notebook_entries_intersects_session_filters(
    store: SQLiteSessionStore,
) -> None:
    session_a = asyncio.run(store.create_session(session_id="session-a"))
    session_b = asyncio.run(store.create_session(session_id="session-b"))
    asyncio.run(
        store.upsert_notebook_entries(
            session_a["id"],
            _make_items(("a1", "A question?", False)),
        )
    )
    asyncio.run(
        store.upsert_notebook_entries(
            session_b["id"],
            _make_items(("b1", "B question?", True)),
        )
    )

    overlap = asyncio.run(
        store.list_notebook_entries(
            session_id=session_a["id"],
            session_ids=[session_a["id"], session_b["id"]],
        )
    )
    disjoint = asyncio.run(
        store.list_notebook_entries(
            session_id=session_a["id"],
            session_ids=[session_b["id"]],
        )
    )
    empty = asyncio.run(store.list_notebook_entries(session_ids=[]))

    assert overlap["total"] == 1
    assert [item["question_id"] for item in overlap["items"]] == ["a1"]
    assert disjoint == {"items": [], "total": 0}
    assert empty == {"items": [], "total": 0}


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


def test_upsert_notebook_entries_with_answer_images(store: SQLiteSessionStore) -> None:
    """#1245 — INSERT with user_answer_images must include every schema column.

    The ``notebook_entries`` schema has more columns than the INSERT listed
    historically (notably ``ai_judgment``, added by migration on legacy
    databases). Skipping one produced ``OperationalError: 22 values for 23
    columns`` at the call site. Cover both INSERT branches: a fresh entry
    carrying images, and a re-upsert that only changes ``is_correct`` while
    keeping the stored images.
    """
    session = asyncio.run(store.create_session())
    sid = session["id"]
    images = [
        {
            "id": "img-1",
            "url": "/files/attachments/img-1/answer.png",
            "filename": "answer.png",
            "mime_type": "image/png",
        }
    ]

    asyncio.run(
        store.upsert_notebook_entries(
            sid,
            [
                {
                    "question_id": "q1",
                    "question": "Identify the diagram.",
                    "user_answer": "B",
                    "is_correct": False,
                    "user_answer_images": images,
                }
            ],
        )
    )
    stored = asyncio.run(store.list_notebook_entries())
    assert stored["total"] == 1
    assert stored["items"][0]["user_answer_images"] == images

    # Re-upsert the same key without sending images — stored images must
    # survive (no-images branch must not clobber user_answer_images_json).
    asyncio.run(
        store.upsert_notebook_entries(
            sid,
            [
                {
                    "question_id": "q1",
                    "question": "Identify the diagram.",
                    "user_answer": "A",
                    "is_correct": True,
                }
            ],
        )
    )
    after = asyncio.run(store.list_notebook_entries())["items"][0]
    assert after["is_correct"] is True
    assert after["user_answer"] == "A"
    assert after["user_answer_images"] == images
    # The new column defaults are exposed by _serialize_notebook_entry.
    assert after["bookmarked"] is False
    assert after["followup_session_id"] == ""


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


def test_notebook_review_metadata_filters_and_transitions(
    store: SQLiteSessionStore,
) -> None:
    session = asyncio.run(store.create_session(title="Sources"))
    asyncio.run(
        store.upsert_notebook_entries(
            session["id"],
            [
                {
                    "question_id": "q1",
                    "question": "Mastery?",
                    "is_correct": False,
                    "source": "mastery_path",
                    "material_id": "path-1",
                    "material_title": "Algebra",
                    "section_id": "kp-1",
                    "section_title": "Equations",
                },
                {
                    "question_id": "q2",
                    "question": "Reading?",
                    "is_correct": True,
                    "source": "immersive_reading",
                    "material_id": "book-1",
                    "material_title": "EPUB",
                    "section_id": "page-1",
                    "section_title": "Page 1",
                },
            ],
        )
    )

    mastery = asyncio.run(
        store.list_notebook_entries(source="mastery_path", material_id="path-1", section_id="kp-1")
    )
    assert mastery["total"] == 1
    entry = mastery["items"][0]
    assert entry["score_trend"] == "new"
    assert entry["resolved"] is False
    assert asyncio.run(store.question_bank_stats())["unresolved"] == 1
    assert asyncio.run(store.list_question_bank_materials()) == [
        {
            "source": "mastery_path",
            "material_id": "path-1",
            "material_title": "Algebra",
            "entry_count": 1,
            "unresolved_count": 1,
        },
        {
            "source": "immersive_reading",
            "material_id": "book-1",
            "material_title": "EPUB",
            "entry_count": 1,
            "unresolved_count": 0,
        },
    ]

    eid = entry["id"]
    assert asyncio.run(store.update_notebook_entry(eid, {"resolved": True}))
    resolved = asyncio.run(store.list_notebook_entries(resolved=True))
    assert {item["id"] for item in resolved["items"]} == {eid, entry["id"] + 1}

    retry = {
        "question_id": "q1",
        "question": "Mastery?",
        "is_correct": True,
        "source": "mastery_path",
        "material_id": "path-1",
        "section_id": "kp-1",
    }
    asyncio.run(store.upsert_notebook_entries(session["id"], [retry]))
    improved = asyncio.run(store.list_notebook_entries(score_trend="improved"))["items"][0]
    assert improved["resolved"] is True

    retry["is_correct"] = False
    asyncio.run(store.upsert_notebook_entries(session["id"], [retry]))
    declined = asyncio.run(store.list_notebook_entries(score_trend="declined"))["items"][0]
    assert declined["resolved"] is False

    asyncio.run(store.upsert_notebook_entries(session["id"], [retry]))
    unchanged = asyncio.run(store.list_notebook_entries(score_trend="unchanged"))["items"][0]
    assert unchanged["resolved"] is False


def test_question_bank_materials_respect_session_scope(store: SQLiteSessionStore) -> None:
    first = asyncio.run(store.create_session(title="Course A"))
    second = asyncio.run(store.create_session(title="Course B"))
    asyncio.run(
        store.upsert_notebook_entries(
            first["id"],
            [
                {
                    "question_id": "q-a",
                    "question": "A?",
                    "is_correct": False,
                    "source": "book",
                    "material_id": "book-a",
                    "material_title": "Book A",
                }
            ],
        )
    )
    asyncio.run(
        store.upsert_notebook_entries(
            second["id"],
            [
                {
                    "question_id": "q-b",
                    "question": "B?",
                    "is_correct": True,
                    "source": "book",
                    "material_id": "book-b",
                    "material_title": "Book B",
                }
            ],
        )
    )

    assert asyncio.run(store.list_question_bank_materials([first["id"]])) == [
        {
            "source": "book",
            "material_id": "book-a",
            "material_title": "Book A",
            "entry_count": 1,
            "unresolved_count": 1,
        }
    ]


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


# ── Turn deletion / parent-pointer splicing ───────────────────────


def _seed_chat(store: SQLiteSessionStore, turns: int) -> tuple[str, list[int]]:
    """Seed a linear multi-turn chat; returns (session_id, message_ids) where
    message_ids alternate user/assistant per turn."""
    session = asyncio.run(store.create_session())
    sid = session["id"]
    ids: list[int] = []
    parent: int | None = None
    for i in range(turns):
        uid = asyncio.run(store.add_message(sid, "user", f"q{i + 1}", parent_message_id=parent))
        ids.append(uid)
        aid = asyncio.run(store.add_message(sid, "assistant", f"a{i + 1}", parent_message_id=uid))
        ids.append(aid)
        parent = aid
    return sid, ids


def test_delete_first_turn_reparents_descendants(store: SQLiteSessionStore) -> None:
    sid, ids = _seed_chat(store, turns=2)
    u1, _a1, u2, a2 = ids

    result = asyncio.run(store.delete_turn_by_message(sid, u1))
    assert result["deleted"] is True

    remaining = asyncio.run(store.get_messages(sid))
    assert [m["content"] for m in remaining] == ["q2", "a2"]
    assert remaining[0]["parent_message_id"] is None
    assert remaining[1]["parent_message_id"] == u2
    # The surviving chain is fully connected root → leaf.
    path = asyncio.run(store.get_message_path(sid, a2))
    assert [m["content"] for m in path] == ["q2", "a2"]


def test_delete_middle_turn_keeps_chain_connected(store: SQLiteSessionStore) -> None:
    sid, ids = _seed_chat(store, turns=3)
    u1, a1, u2, _a2, u3, a3 = ids

    result = asyncio.run(store.delete_turn_by_message(sid, u2))
    assert result["deleted"] is True

    remaining = asyncio.run(store.get_messages(sid))
    assert [m["content"] for m in remaining] == ["q1", "a1", "q3", "a3"]
    by_content = {m["content"]: m for m in remaining}
    assert by_content["q3"]["parent_message_id"] == a1

    path = asyncio.run(store.get_message_path(sid, a3))
    assert [m["content"] for m in path] == ["q1", "a1", "q3", "a3"]
    # u1 stays the session root.
    assert by_content["q1"]["parent_message_id"] is None
    assert by_content["q1"]["id"] == u1


def test_delete_last_turn_leaves_prefix_intact(store: SQLiteSessionStore) -> None:
    sid, ids = _seed_chat(store, turns=2)
    _u1, a1, u2, _a2 = ids

    result = asyncio.run(store.delete_turn_by_message(sid, u2))
    assert result["deleted"] is True

    remaining = asyncio.run(store.get_messages(sid))
    assert [m["content"] for m in remaining] == ["q1", "a1"]
    assert remaining[0]["parent_message_id"] is None
    assert remaining[1]["parent_message_id"] == remaining[0]["id"]
    assert remaining[1]["id"] == a1


# ── Context messages ──────────────────────────────────────────────


_ASK_USER_EVENTS = [
    {"type": "content", "content": "streamed delta", "metadata": {}},
    {
        "type": "tool_result",
        "metadata": {
            "tool_metadata": {"ask_user": {"questions": [{"id": "level", "prompt": "Your level?"}]}}
        },
    },
    {
        "type": "progress",
        "metadata": {
            "ask_user_resolved": True,
            "answers": [{"questionId": "level", "text": "Beginner"}],
        },
    },
]


def _add_ask_user_turn(store: SQLiteSessionStore, session_id: str) -> None:
    asyncio.run(store.add_message(session_id, "user", "Plan my study"))
    asyncio.run(
        store.add_message(session_id, "assistant", "Here is a plan", events=_ASK_USER_EVENTS)
    )


def test_context_messages_carry_ask_user_events(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    _add_ask_user_turn(store, session["id"])

    messages = asyncio.run(store.get_messages_for_context(session["id"]))

    assert [m["role"] for m in messages] == ["user", "assistant"]
    # Streamed deltas are dropped; only the ask_user exchange survives, so a
    # later turn can see which questions the learner already answered.
    assert [e["type"] for e in messages[1]["events"]] == ["tool_result", "progress"]


def test_context_messages_carry_private_metadata(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    state = {"reasoning_content": "private reasoning"}
    asyncio.run(
        store.add_message(
            session["id"],
            "assistant",
            "A direct answer",
            metadata={"provider_response_state": state},
        )
    )

    messages = asyncio.run(store.get_messages_for_context(session["id"]))

    assert messages[0]["metadata"]["provider_response_state"] == state

    public_detail = asyncio.run(store.get_session_with_messages(session["id"]))
    assert public_detail is not None
    assert "provider_response_state" not in public_detail["messages"][0]["metadata"]


def test_branch_context_messages_carry_ask_user_events(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    _add_ask_user_turn(store, session["id"])
    leaf = asyncio.run(store.add_message(session["id"], "user", "Still not right"))

    messages = asyncio.run(store.get_messages_for_context(session["id"], leaf_message_id=leaf))

    assert [e["type"] for e in messages[1]["events"]] == ["tool_result", "progress"]


def test_branch_context_messages_carry_private_metadata(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.add_message(session["id"], "user", "Question"))
    state = {"reasoning_content": "branch reasoning"}
    leaf = asyncio.run(
        store.add_message(
            session["id"],
            "assistant",
            "A branched answer",
            metadata={"provider_response_state": state},
        )
    )

    messages = asyncio.run(store.get_messages_for_context(session["id"], leaf_message_id=leaf))

    assert messages[-1]["metadata"]["provider_response_state"] == state
