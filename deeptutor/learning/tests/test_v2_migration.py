from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing
from pathlib import Path
import sqlite3

import pytest

import deeptutor.learning.migration as migration_module
from deeptutor.learning.migration import prepare_mastery_v2_root
from deeptutor.learning.models import LearningProgress, MasteryInteraction, PendingQuestion
from deeptutor.learning.storage import LearningStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_in_process(path: str) -> str:
    return str(prepare_mastery_v2_root(Path(path)))


def test_workspace_v1_is_archived_then_copied_into_v2_store(tmp_path: Path) -> None:
    learning_root = tmp_path / "learning"
    old_store = LearningStore(root=learning_root)
    old_store.save(LearningProgress(book_id="topic-one", name="Calculus"))
    old_store.bind_session("topic-one", "session-one")

    question = PendingQuestion(
        question_id="q-one",
        knowledge_point_id="kp-one",
        prompt="What is a limit?",
        expected_answer="A value approached by a function.",
    )
    old_store.mutate(
        "topic-one",
        lambda tx: tx.put_interaction(
            MasteryInteraction(
                interaction_id="q-one",
                path_id="topic-one",
                question=question,
            )
        ),
    )
    legacy_json = learning_root / ".legacy" / "older-topic.json"
    legacy_json.parent.mkdir(parents=True)
    legacy_json.write_text('{"legacy": true}', encoding="utf-8")

    old_db_hash = _sha256(learning_root / "mastery.sqlite3")
    v2_root = prepare_mastery_v2_root(learning_root)

    assert v2_root == learning_root / "mastery"
    assert not (learning_root / "mastery.sqlite3").exists()
    assert not (learning_root / ".legacy").exists()

    archives = sorted((learning_root / "archive").glob("v1-*"))
    assert len(archives) == 1
    archive = archives[0]
    archived_db = archive / "mastery.sqlite3"
    assert archived_db.exists()
    assert _sha256(archived_db) == old_db_hash
    assert (archive / "legacy-json" / "older-topic.json").exists()

    manifest = json.loads((archive / "migration.json").read_text(encoding="utf-8"))
    assert manifest["format_version"] == 2
    assert manifest["database_sha256"] == old_db_hash
    assert manifest["row_counts"]["mastery_paths"] == 1
    assert manifest["row_counts"]["mastery_path_sessions"] == 1
    assert manifest["row_counts"]["mastery_interactions"] == 1
    assert manifest["legacy_json_count"] == 1

    migrated = LearningStore(root=v2_root)
    assert migrated.load("topic-one").name == "Calculus"
    assert migrated.list_session_ids("topic-one") == ["session-one"]
    assert migrated.get_interaction("topic-one", "q-one") is not None
    migrated_topic = migrated.get_topic("topic-one")
    assert migrated_topic is not None
    assert migrated_topic.metadata.status == "active"
    assert migrated_topic.metadata.map_seed > 0
    with sqlite3.connect(migrated.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mastery_topic_meta").fetchone()[0] == 1


def test_v2_initialization_is_idempotent_and_never_reads_archive(tmp_path: Path) -> None:
    learning_root = tmp_path / "learning"
    old_store = LearningStore(root=learning_root)
    old_store.save(LearningProgress(book_id="topic-one"))

    v2_root = prepare_mastery_v2_root(learning_root)
    archive = next((learning_root / "archive").glob("v1-*"))
    archived_db = archive / "mastery.sqlite3"
    archived_db.write_bytes(b"backup-only")

    assert prepare_mastery_v2_root(learning_root) == v2_root
    assert LearningStore(root=v2_root).exists("topic-one") is True
    assert archived_db.read_bytes() == b"backup-only"


def test_empty_workspace_uses_v2_directory_without_creating_archive(tmp_path: Path) -> None:
    learning_root = tmp_path / "learning"

    v2_root = prepare_mastery_v2_root(learning_root)
    store = LearningStore(root=v2_root)
    store.save(LearningProgress(book_id="fresh-topic"))

    assert store.db_path == learning_root / "mastery" / "mastery.sqlite3"
    assert not (learning_root / "archive").exists()


def test_live_root_json_is_imported_and_archived(tmp_path: Path) -> None:
    learning_root = tmp_path / "learning"
    learning_root.mkdir(parents=True)
    legacy_json = learning_root / "json-only.json"
    legacy_json.write_text(
        LearningProgress(book_id="json-only", name="JSON only").model_dump_json(),
        encoding="utf-8",
    )

    v2_root = prepare_mastery_v2_root(learning_root)

    assert LearningStore(root=v2_root).load("json-only").name == "JSON only"
    assert not legacy_json.exists()
    archive = next((learning_root / "archive").glob("v1-*"))
    assert (archive / "legacy-json" / "json-only.json").exists()
    manifest = json.loads((archive / "migration.json").read_text(encoding="utf-8"))
    assert manifest["legacy_json_count"] == 1
    assert manifest["row_counts"]["mastery_paths"] == 1


def test_corrupt_live_json_is_quarantined_without_blocking_good_migration(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    learning_root = tmp_path / "learning"
    learning_root.mkdir(parents=True)
    good_json = learning_root / "good-topic.json"
    good_json.write_text(
        LearningProgress(book_id="good-topic", name="Recovered topic").model_dump_json(),
        encoding="utf-8",
    )
    corrupt_json = learning_root / "corrupt-topic.json"
    corrupt_json.write_text('{"book_id": "corrupt-topic",', encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="deeptutor.learning.storage"):
        v2_root = prepare_mastery_v2_root(learning_root)

    migrated = LearningStore(root=v2_root)
    assert migrated.load("good-topic").name == "Recovered topic"
    assert migrated.exists("corrupt-topic") is False
    assert not corrupt_json.exists()
    assert (learning_root / "archive" / "failed" / "corrupt-topic.json").exists()
    assert "Quarantined corrupt legacy mastery file" in caplog.text

    archive = next((learning_root / "archive").glob("v1-*"))
    manifest = json.loads((archive / "migration.json").read_text(encoding="utf-8"))
    assert manifest["row_counts"]["mastery_paths"] == 1


def test_late_root_json_is_reconciled_into_existing_v2_store(tmp_path: Path) -> None:
    learning_root = tmp_path / "learning"
    v2_root = prepare_mastery_v2_root(learning_root)
    LearningStore(root=v2_root).save(LearningProgress(book_id="existing"))
    late_json = learning_root / "late-topic.json"
    late_json.write_text(
        LearningProgress(book_id="late-topic", name="Recovered").model_dump_json(),
        encoding="utf-8",
    )

    assert prepare_mastery_v2_root(learning_root) == v2_root
    migrated = LearningStore(root=v2_root)
    assert migrated.exists("existing") is True
    assert migrated.load("late-topic").name == "Recovered"
    assert not late_json.exists()


def test_process_concurrent_initialization_creates_one_archive(tmp_path: Path) -> None:
    learning_root = tmp_path / "learning"
    old_store = LearningStore(root=learning_root)
    old_store.save(LearningProgress(book_id="topic-one"))

    context = multiprocessing.get_context("spawn")
    with context.Pool(processes=3) as pool:
        roots = pool.map(_prepare_in_process, [str(learning_root)] * 3)

    assert roots == [str(learning_root / "mastery")] * 3
    assert len(list((learning_root / "archive").glob("v1-*"))) == 1
    assert LearningStore(root=learning_root / "mastery").exists("topic-one") is True


def test_interrupted_finalization_resumes_from_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    learning_root = tmp_path / "learning"
    old_store = LearningStore(root=learning_root)
    old_store.save(LearningProgress(book_id="topic-one"))

    def interrupt(_archive_root: Path, _staging: Path) -> None:
        raise RuntimeError("simulated shutdown")

    monkeypatch.setattr(migration_module, "_finish_staging_archive", interrupt)
    with pytest.raises(RuntimeError, match="simulated shutdown"):
        prepare_mastery_v2_root(learning_root)

    assert (learning_root / "archive" / ".v1-migration-in-progress").exists()
    assert not (learning_root / "mastery.sqlite3").exists()
    monkeypatch.undo()

    v2_root = prepare_mastery_v2_root(learning_root)
    assert not (learning_root / "archive" / ".v1-migration-in-progress").exists()
    assert len(list((learning_root / "archive").glob("v1-*"))) == 1
    assert LearningStore(root=v2_root).exists("topic-one") is True
