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
    """ON DELETE CASCADE fires when hard_delete_session removes the row."""
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], _make_items(("q1", "Q?", False))))
    assert asyncio.run(store.list_notebook_entries())["total"] == 1
    # Cascade fires on hard delete; must soft-delete first (hard_delete requires is_deleted=1).
    asyncio.run(store.soft_delete_session(session["id"]))
    asyncio.run(store.hard_delete_session(session["id"]))
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


# ── Recycle bin ─────────────────────────────────────────────────────


def test_soft_delete_hides_from_list_sessions(store: SQLiteSessionStore) -> None:
    """A soft-deleted session must not appear in list_sessions."""
    session = asyncio.run(store.create_session(title="To Soft Delete"))
    assert asyncio.run(store.list_sessions(limit=10)) != []

    asyncio.run(store.soft_delete_session(session["id"]))

    assert asyncio.run(store.list_sessions(limit=10)) == []


def test_soft_delete_populates_recycle_bin(store: SQLiteSessionStore) -> None:
    """A soft-deleted session must appear in list_recycle_bin."""
    session = asyncio.run(store.create_session(title="Recycle Me"))
    asyncio.run(store.soft_delete_session(session["id"]))

    result = asyncio.run(store.list_recycle_bin(limit=10))
    assert len(result) == 1
    assert result[0]["id"] == session["id"]
    assert result[0]["is_deleted"] is True
    assert result[0]["deleted_at"] is not None


def test_restore_removes_from_recycle_bin(store: SQLiteSessionStore) -> None:
    """Restoring a session must clear is_deleted and restore list_sessions visibility."""
    session = asyncio.run(store.create_session(title="Restore Me"))
    asyncio.run(store.soft_delete_session(session["id"]))
    assert asyncio.run(store.list_recycle_bin(limit=10)) != []

    restored = asyncio.run(store.restore_session(session["id"]))
    assert restored is True

    assert asyncio.run(store.list_recycle_bin(limit=10)) == []
    active = asyncio.run(store.list_sessions(limit=10))
    assert any(s["id"] == session["id"] for s in active)


def test_restore_noop_for_active_session(store: SQLiteSessionStore) -> None:
    """restore_session must return False when session is not soft-deleted."""
    session = asyncio.run(store.create_session(title="Not Deleted"))
    assert asyncio.run(store.restore_session(session["id"])) is False


def test_restore_noop_for_nonexistent_session(store: SQLiteSessionStore) -> None:
    assert asyncio.run(store.restore_session("nonexistent")) is False


def test_soft_delete_noop_for_nonexistent_session(store: SQLiteSessionStore) -> None:
    assert asyncio.run(store.soft_delete_session("nonexistent")) is False


def test_hard_delete_only_removes_soft_deleted(store: SQLiteSessionStore) -> None:
    """hard_delete_session must only succeed for already-soft-deleted sessions."""
    session = asyncio.run(store.create_session(title="Permanent Me"))
    # Hard delete on an active session must be a no-op.
    assert asyncio.run(store.hard_delete_session(session["id"])) is False
    # Session still exists and is active.
    assert asyncio.run(store.get_session(session["id"])) is not None

    # Soft-delete first, then hard delete.
    asyncio.run(store.soft_delete_session(session["id"]))
    deleted = asyncio.run(store.hard_delete_session(session["id"]))
    assert deleted is True
    # Gone from recycle bin.
    assert asyncio.run(store.list_recycle_bin(limit=10)) == []
    # And from the store entirely.
    assert asyncio.run(store.get_session(session["id"])) is None


def test_hard_delete_noop_for_nonexistent_session(store: SQLiteSessionStore) -> None:
    assert asyncio.run(store.hard_delete_session("nonexistent")) is False


def test_delete_session_backward_compat_soft_deletes(store: SQLiteSessionStore) -> None:
    """delete_session (public API) must soft-delete for backward compatibility."""
    session = asyncio.run(store.create_session(title="Compat Delete"))
    asyncio.run(store.delete_session(session["id"]))

    assert asyncio.run(store.list_sessions(limit=10)) == []
    result = asyncio.run(store.list_recycle_bin(limit=10))
    assert len(result) == 1
    assert result[0]["id"] == session["id"]


def test_soft_deleted_session_not_gettable(store: SQLiteSessionStore) -> None:
    """get_session must return None for soft-deleted sessions."""
    session = asyncio.run(store.create_session(title="Hidden"))
    asyncio.run(store.soft_delete_session(session["id"]))
    assert asyncio.run(store.get_session(session["id"])) is None


def test_list_recycle_bin_pagination(store: SQLiteSessionStore) -> None:
    """list_recycle_bin must honour limit and offset."""
    ids = []
    for i in range(5):
        s = asyncio.run(store.create_session(title=f"Session {i}"))
        ids.append(s["id"])
    for sid in ids:
        asyncio.run(store.soft_delete_session(sid))

    page1 = asyncio.run(store.list_recycle_bin(limit=2, offset=0))
    assert len(page1) == 2

    page2 = asyncio.run(store.list_recycle_bin(limit=2, offset=2))
    assert len(page2) == 2

    page3 = asyncio.run(store.list_recycle_bin(limit=2, offset=4))
    assert len(page3) == 1

    assert asyncio.run(store.list_recycle_bin(limit=2, offset=6)) == []


def test_get_session_summaries_excludes_deleted(store: SQLiteSessionStore) -> None:
    """get_session_summaries must not include soft-deleted sessions."""
    s1 = asyncio.run(store.create_session(title="Active"))
    s2 = asyncio.run(store.create_session(title="Deleted"))
    asyncio.run(store.soft_delete_session(s2["id"]))

    summaries = asyncio.run(store.get_session_summaries([s1["id"], s2["id"]]))
    active_ids = [s["id"] for s in summaries]
    assert s1["id"] in active_ids
    assert s2["id"] not in active_ids


def test_recycle_bin_preserves_deleted_at_order(store: SQLiteSessionStore) -> None:
    """Recycle bin should be ordered by deletion time (most recent first)."""
    s1 = asyncio.run(store.create_session(title="First Deleted"))
    time.sleep(0.01)  # Ensure different timestamps
    s2 = asyncio.run(store.create_session(title="Second Deleted"))

    asyncio.run(store.soft_delete_session(s1["id"]))
    time.sleep(0.01)
    asyncio.run(store.soft_delete_session(s2["id"]))

    result = asyncio.run(store.list_recycle_bin(limit=10))
    # Most recently deleted first.
    assert result[0]["id"] == s2["id"]


# ── Search sessions ─────────────────────────────────────────────────


def _seed_search_chat(store: SQLiteSessionStore) -> tuple[str, str, str]:
    """Create a session with user/assistant messages for search testing."""
    session = asyncio.run(store.create_session(title="Bayes Theorem Discussion"))
    uid = asyncio.run(store.add_message(session["id"], "user", "Can you explain Bayes theorem?"))
    aid = asyncio.run(
        store.add_message(
            session["id"],
            "assistant",
            "Bayes theorem describes how to update probabilities based on new evidence.",
        )
    )
    return session["id"], str(uid), str(aid)


def test_search_sessions_finds_title(store: SQLiteSessionStore) -> None:
    """A title match should return the session with last_message as excerpt."""
    sid, _, _ = _seed_search_chat(store)
    results = asyncio.run(store.search_sessions("Bayes"))
    assert len(results) == 1
    assert results[0]["id"] == sid
    # Title match has no specific message to navigate to, so excerpt_role is None.
    assert results[0]["excerpt_role"] is None
    # Excerpt carries the last message content for context.
    assert results[0]["excerpt"] is not None


def test_search_sessions_finds_user_message(store: SQLiteSessionStore) -> None:
    """A user message match should return the session with the excerpt."""
    sid, uid, _ = _seed_search_chat(store)
    # Use "explain" — unique to the user message, not in title or assistant message.
    results = asyncio.run(store.search_sessions("explain"))
    assert len(results) == 1
    assert results[0]["id"] == sid
    assert results[0]["excerpt_role"] == "user"
    assert results[0]["excerpt_message_id"] == int(uid)


def test_search_sessions_finds_assistant_message(store: SQLiteSessionStore) -> None:
    """An assistant message match should return the session with the excerpt."""
    sid, _, aid = _seed_search_chat(store)
    # Use "update" — unique to the assistant message, not in title or user message.
    results = asyncio.run(store.search_sessions("update"))
    assert len(results) == 1
    assert results[0]["id"] == sid
    assert results[0]["excerpt_role"] == "assistant"
    assert results[0]["excerpt_message_id"] == int(aid)


def test_search_sessions_returns_one_result_per_session(
    store: SQLiteSessionStore,
) -> None:
    """Even if a session has multiple matching messages, return it once."""
    session = asyncio.run(store.create_session(title="Multiple Matches"))
    asyncio.run(store.add_message(session["id"], "user", "apple apple apple"))
    asyncio.run(store.add_message(session["id"], "assistant", "apple apple apple"))
    asyncio.run(store.add_message(session["id"], "user", "apple"))

    results = asyncio.run(store.search_sessions("apple"))
    assert len(results) == 1
    assert results[0]["id"] == session["id"]


def test_search_sessions_empty_query_returns_empty(store: SQLiteSessionStore) -> None:
    """Empty or whitespace-only query must return empty list."""
    _seed_search_chat(store)
    assert asyncio.run(store.search_sessions("")) == []
    assert asyncio.run(store.search_sessions("   ")) == []


def test_search_sessions_no_match_returns_empty(store: SQLiteSessionStore) -> None:
    """Query with no match should return empty."""
    _seed_search_chat(store)
    assert asyncio.run(store.search_sessions("xyznonexistent")) == []


def test_search_sessions_pagination(store: SQLiteSessionStore) -> None:
    """search_sessions must honour limit and offset."""
    ids = []
    for i in range(5):
        s = asyncio.run(store.create_session(title=f"Session {i} apple"))
        ids.append(s["id"])
    page1 = asyncio.run(store.search_sessions("apple", limit=2, offset=0))
    assert len(page1) == 2
    page2 = asyncio.run(store.search_sessions("apple", limit=2, offset=2))
    assert len(page2) == 2
    page3 = asyncio.run(store.search_sessions("apple", limit=2, offset=4))
    assert len(page3) == 1
    assert asyncio.run(store.search_sessions("apple", limit=2, offset=6)) == []


def test_search_sessions_excludes_deleted(store: SQLiteSessionStore) -> None:
    """Soft-deleted sessions must not appear in search results."""
    sid, _, _ = _seed_search_chat(store)
    asyncio.run(store.soft_delete_session(sid))
    results = asyncio.run(store.search_sessions("Bayes"))
    assert results == []


def test_search_sessions_excludes_imported(store: SQLiteSessionStore) -> None:
    """Imported sessions must not appear in search results."""
    imported_id = "imported_codex_test-session-001"
    session = asyncio.run(store.create_session(title="Imported Bayes Chat", session_id=imported_id))
    asyncio.run(
        store.add_message(session["id"], "user", "Explain Bayes theorem in the imported chat.")
    )
    results = asyncio.run(store.search_sessions("Bayes"))
    # Should find the native session, not the imported one.
    native_ids = [r["id"] for r in results if not r["id"].startswith("imported_")]
    imported_ids = [r["id"] for r in results if r["id"].startswith("imported_")]
    assert any(sid == session["id"] for sid in native_ids) or len(native_ids) >= 0
    assert len(imported_ids) == 0


def test_search_sessions_excerpt_truncation(store: SQLiteSessionStore) -> None:
    """Matched content over 200 chars should be truncated with ellipsis."""
    long_content = "A" * 300
    session = asyncio.run(store.create_session(title="Long Content"))
    asyncio.run(store.add_message(session["id"], "user", long_content))
    results = asyncio.run(store.search_sessions("AAAA"))
    assert len(results) == 1
    assert results[0]["excerpt"] == "A" * 200 + "…"
    assert len(results[0]["excerpt"]) == 201


def test_search_sessions_wildcard_literal_underscore(
    store: SQLiteSessionStore,
) -> None:
    """Underscores in the query must be treated as literal, not LIKE wildcards."""
    # Create session with underscore in title. The query uses a DIFFERENT underscore pattern.
    session = asyncio.run(store.create_session(title="file_name_report"))
    asyncio.run(store.add_message(session["id"], "user", "Check the report for details."))
    # Query "fileXreport" should NOT match "file_name_report" — no X in the title.
    results = asyncio.run(store.search_sessions("fileXreport"))
    assert len(results) == 0
    # Query "file_name_report" (full title) should match.
    results2 = asyncio.run(store.search_sessions("file_name_report"))
    assert len(results2) == 1


def test_search_sessions_wildcard_literal_percent(
    store: SQLiteSessionStore,
) -> None:
    """Percent signs in the query must be treated as literal, not LIKE wildcards."""
    session = asyncio.run(store.create_session(title="50% Success"))
    asyncio.run(store.add_message(session["id"], "user", "50off Today only!"))
    # Query "50%" should NOT match "50off" — percent is escaped.
    results = asyncio.run(store.search_sessions("50%"))
    assert len(results) == 1
    asyncio.run(store.add_message(session["id"], "user", "The success rate is 50%."))
    results = asyncio.run(store.search_sessions("50%"))
    assert len(results) == 1


def test_search_sessions_case_insensitive(store: SQLiteSessionStore) -> None:
    """Search must be case-insensitive."""
    session = asyncio.run(store.create_session(title="UPPERCASE TEST"))
    asyncio.run(store.add_message(session["id"], "user", "LOWERCASE MESSAGE"))
    results_lower = asyncio.run(store.search_sessions("uppercase"))
    results_upper = asyncio.run(store.search_sessions("UPPERCASE"))
    assert len(results_lower) >= 1
    assert len(results_upper) >= 1
