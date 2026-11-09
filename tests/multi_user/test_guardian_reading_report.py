from __future__ import annotations

import asyncio
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from deeptutor.multi_user import guardian_reading


def paths_at(root: Path):
    return SimpleNamespace(
        get_workspace_dir=lambda: root / "workspace", get_chat_history_db=lambda: root / "chat.db"
    )


def seed(root: Path, label: str):
    root.mkdir(parents=True)
    with sqlite3.connect(root / "chat.db") as db:
        db.executescript("""
        CREATE TABLE sessions(id TEXT, deleted_at REAL);
        INSERT INTO sessions VALUES ('live', NULL), ('trash', 1);
        CREATE TABLE notebook_entries(id INTEGER PRIMARY KEY, question_id TEXT, material_id TEXT,
          material_title TEXT, section_id TEXT, section_title TEXT, question TEXT, is_correct INTEGER,
          hints_used INTEGER, attempt_count INTEGER, updated_at REAL, source TEXT, session_id TEXT,
          created_at REAL, correct_answer TEXT, explanation TEXT);
        """)
        for i in range(60):
            db.execute(
                "INSERT INTO notebook_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i,
                    f"q{i}",
                    "material",
                    label,
                    "section",
                    "Lesson",
                    f"{label} {i}",
                    0,
                    2,
                    3,
                    i,
                    "immersive_reading" if i != 59 else "other",
                    "trash" if i == 58 else "live",
                    i,
                    "secret answer",
                    "secret explanation",
                ),
            )
    directory = root / "workspace" / "learning" / "mastery"
    directory.mkdir(parents=True)
    with sqlite3.connect(directory / "mastery.sqlite3") as db:
        db.executescript("""
        CREATE TABLE reading_progress(material_id TEXT, latest_locator INTEGER, latest_percentage REAL,
          furthest_locator INTEGER, furthest_percentage REAL, updated_at REAL);
        INSERT INTO reading_progress VALUES ('material', 2, 0.2, 4, 0.4, 10);
        CREATE TABLE reading_activities(activity_id TEXT, material_id TEXT, extension_id TEXT,
          action TEXT, locator INTEGER, result_type TEXT, created_at REAL);
        INSERT INTO reading_activities VALUES ('a1', 'material', 'vocabulary', 'explain', 2, 'card', 9);
        """)


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_readonly_projection_filters_source_and_recycled_entries_limits_and_counts(tmp_path):
    seed(tmp_path / "learner", "Learner question")
    before = snapshot(tmp_path)
    result = guardian_reading._read_report(paths_at(tmp_path / "learner"))
    assert result["reading_status"] == result["quiz_status"] == "available"
    assert result["progress"][0]["furthest_percentage"] == 0.4
    assert result["activities"][0]["action"] == "explain"
    assert result["quiz_total"] == 58
    assert len(result["quizzes"]) == 50
    assert result["quizzes"][0]["question_id"] == "q57"
    assert result["quizzes"][0]["is_correct"] is False
    assert result["quizzes"][0]["hints_used"] == 2
    assert "secret" not in str(result)
    assert "session_id" not in result["quizzes"][0]
    assert snapshot(tmp_path) == before


def test_uses_verified_learner_scope_not_another_accounts_store(tmp_path, monkeypatch):
    for name in ("learner", "guardian", "other"):
        seed(tmp_path / name, name)
    calls = []
    monkeypatch.setattr(
        guardian_reading, "scope_for_user", lambda uid, **kw: calls.append((uid, kw)) or uid
    )
    monkeypatch.setattr(
        guardian_reading, "get_path_service_for_scope", lambda uid: paths_at(tmp_path / uid)
    )
    result = asyncio.run(guardian_reading.reading_report_for("learner"))
    assert calls == [("learner", {"is_admin": False})]
    assert all(q["material_title"] == "learner" for q in result["quizzes"])


def test_uninitialized_report_creates_no_files_or_directories(tmp_path):
    root = tmp_path / "absent"
    result = guardian_reading._read_report(paths_at(root))
    assert result["reading_status"] == result["quiz_status"] == "not_initialized"
    assert not root.exists()


def test_legacy_learning_store_is_reported_without_migration(tmp_path):
    learning = tmp_path / "workspace" / "learning"
    learning.mkdir(parents=True)
    (learning / "mastery.sqlite3").write_bytes(b"historical fixture")
    before = snapshot(tmp_path)
    result = guardian_reading._read_report(paths_at(tmp_path))
    assert result["reading_status"] == "migration_required"
    assert snapshot(tmp_path) == before
    assert not (learning / "mastery").exists()


def test_old_chat_schema_is_not_silently_reported_as_empty_current_data(tmp_path):
    with sqlite3.connect(tmp_path / "chat.db") as db:
        db.execute("CREATE TABLE sessions(id TEXT)")
    before = snapshot(tmp_path)
    assert guardian_reading._read_report(paths_at(tmp_path))["quiz_status"] == "migration_required"
    assert snapshot(tmp_path) == before


def test_corrupt_database_failure_propagates(tmp_path):
    (tmp_path / "chat.db").write_bytes(b"corrupt database")
    with pytest.raises(sqlite3.DatabaseError):
        guardian_reading._read_report(paths_at(tmp_path))


def test_wal_report_reads_committed_records_without_changing_application_data(tmp_path):
    seed(tmp_path / "learner", "Initial")
    path = tmp_path / "learner" / "chat.db"
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE notebook_entries SET hints_used=7 WHERE id=57")
        writer.commit()
        result = guardian_reading._read_report(paths_at(tmp_path / "learner"))
        assert result["quizzes"][0]["hints_used"] == 7
        assert writer.execute("SELECT COUNT(*) FROM notebook_entries").fetchone()[0] == 60
        assert (
            writer.execute("SELECT hints_used FROM notebook_entries WHERE id=57").fetchone()[0] == 7
        )
    # SQLite may create WAL/SHM coordination files during a read; those are not
    # an application database migration or a write to learner records.
    again = guardian_reading._read_report(paths_at(tmp_path / "learner"))
    assert again["quizzes"][0]["hints_used"] == 7


def test_material_title_comes_from_catalog_without_any_quiz(tmp_path):
    seed(tmp_path / "learner", "Old quiz title")
    root = tmp_path / "learner" / "workspace" / "reading"
    root.mkdir()
    with sqlite3.connect(root / "_catalog.sqlite3") as db:
        db.execute("CREATE TABLE reading_materials(material_id TEXT, title TEXT, filename TEXT)")
        db.execute(
            "INSERT INTO reading_materials VALUES ('material', 'Current lesson title', 'lesson.txt')"
        )
    with sqlite3.connect(tmp_path / "learner" / "chat.db") as db:
        db.execute("DELETE FROM notebook_entries")
    result = guardian_reading._read_report(paths_at(tmp_path / "learner"))
    assert result["quizzes"] == []
    assert result["progress"][0]["material_title"] == "Current lesson title"
