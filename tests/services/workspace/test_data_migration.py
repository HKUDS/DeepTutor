from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from deeptutor.services.path_service import get_path_service
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.data_migration import discover, export_data, migrate_data, preview
from deeptutor.services.workspace.models import WorkspaceError
from tests.services.workspace.test_data_scope import account as account


@pytest.mark.asyncio
async def test_migration_keeps_messages_branches_questions_and_source_backup(account):
    target = account.create_workspace("Destination")["workspace_id"]
    with workspace_context():
        store = get_sqlite_session_store()
        session = await store.create_session("A learning conversation")
        user_id = await store.add_message(session["id"], "user", "question")
        reply_id = await store.add_message(
            session["id"], "assistant", "answer", parent_message_id=user_id
        )
        await store.upsert_notebook_entries(
            session["id"],
            [{"question_id": "question-one", "question": "Keep this question"}],
        )
        notebook_id = (await store.find_notebook_entry(session["id"], "question-one"))["id"]
        await store.append_assessment_attempt(
            session["id"],
            notebook_id,
            {
                "attempt_id": "attempt-one",
                "question_id": "question-one",
                "result": "correct",
            },
        )
        paths = get_path_service()
        book = paths.get_book_dir() / "book_one"
        book.mkdir(parents=True)
        (book / "inputs.json").write_text(
            json.dumps(
                {
                    "chat_selections": [
                        {"session_id": session["id"], "message_ids": [user_id, reply_id]}
                    ]
                }
            )
        )
    plan = preview("", target, ["book"])
    assert session["id"] in plan["session_ids"]
    assert not plan["blockers"]
    result = migrate_data("", target, ["book"])
    assert result["status"] == "completed"
    backup = Path(result["recovery_path"]) / "snapshot" / "sessions" / "chat_history.db"
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    with workspace_context(target):
        migrated = get_sqlite_session_store()
        saved = await migrated.get_session(session["id"])
        assert saved["preferences"]["workspace_id"] == target
        messages = await migrated.get_messages(session["id"])
        assert [row["id"] for row in messages] == [user_id, reply_id]
        assert messages[1]["parent_message_id"] == user_id
        questions = await migrated.list_notebook_entries(session_id=session["id"])
        assert questions["items"][0]["question"] == "Keep this question"
        attempts = await migrated.list_assessment_attempts(
            session["id"], question_id="question-one"
        )
        assert attempts[0]["attempt_id"] == "attempt-one"
        assert (get_path_service().get_book_dir() / "book_one" / "inputs.json").exists()
    with workspace_context():
        assert await store.get_session(session["id"]) is None
        assert not (await store.list_notebook_entries(session_id=session["id"]))["items"]
        assert not await store.list_assessment_attempts(session["id"], question_id="question-one")
        assert not book.exists()


@pytest.mark.asyncio
async def test_active_turn_and_conflicting_target_refuse_without_changes(account):
    target = account.create_workspace("Destination")["workspace_id"]
    with workspace_context():
        store = get_sqlite_session_store()
        session = await store.create_session()
        turn = await store.create_turn(session["id"])
    with pytest.raises(WorkspaceError, match="active"):
        migrate_data("", target, ["chat"])
    assert await store.get_session(session["id"]) is not None
    await store.update_turn_status(turn["id"], "completed")
    with workspace_context(target):
        book = get_path_service().get_book_dir()
        book.mkdir(parents=True)
        (book / "existing.txt").write_text("keep")
    with workspace_context():
        original = get_path_service().get_book_dir()
        original.mkdir(parents=True, exist_ok=True)
        (original / "source.txt").write_text("keep")
    with pytest.raises(WorkspaceError, match="already contains"):
        migrate_data("", target, ["book"])
    assert (book / "existing.txt").read_text() == "keep"
    assert (original / "source.txt").read_text() == "keep"


def test_export_checksums_and_symlink_exclusion(account, tmp_path):
    root = get_path_service().get_book_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.txt").write_text("notes")
    export = export_data("", ["book"])
    from deeptutor.services.workspace.data_migration import export_path

    with zipfile.ZipFile(export_path(export["id"])) as archive:
        assert archive.read("book/notes.txt") == b"notes"
        manifest = json.loads(archive.read("manifest.json"))
        assert "notes.txt" in manifest["sha256"]["book"]
    secret = tmp_path / "outside.txt"
    secret.write_text("outside")
    (root / "link").symlink_to(secret)
    assert next(row for row in discover()["features"] if row["feature"] == "book")["error"]
    with pytest.raises(WorkspaceError, match="Symbolic"):
        export_data("", ["book"])


@pytest.mark.asyncio
async def test_reverse_dependencies_include_books_but_not_unrelated_chats(account):
    with workspace_context():
        store = get_sqlite_session_store()
        a = await store.create_session("Cited")
        b = await store.create_session("Unrelated")
        root = get_path_service().get_book_dir() / "book_reverse"
        root.mkdir(parents=True)
        (root / "inputs.json").write_text(
            json.dumps({"chat_selections": [{"session_id": a["id"]}]})
        )
        from deeptutor.services.workspace.data_migration import _sessions
        from deeptutor.services.workspace.dependencies import dependency_closure

        features, ids = dependency_closure(
            get_path_service(), _sessions(get_path_service()), ["chat"], session_ids={a["id"]}
        )
        assert "book" in features
        assert ids == {a["id"]}
        assert b["id"] not in ids


@pytest.mark.asyncio
async def test_move_chat_preserves_presented_file_and_denies_source(account):
    from deeptutor.services.workspace.session_move import move_chat

    target = account.create_workspace("Destination")["workspace_id"]
    with workspace_context():
        store = get_sqlite_session_store()
        session = await store.create_session("Chat with file")
        output = account.create_runtime_context(
            capability="chat", session_id=session["id"], turn_id="turn_one", workspace_id=""
        )
        (Path(output.output_dir) / "hello.txt").write_text("hello")
        item = account.publish(
            account.general_binding(), [{"path": output.logical_output_dir + "/hello.txt"}]
        )[0]
        await store.add_message(session["id"], "assistant", item.url)
        moved = move_chat(session["id"], target)
        assert moved["preferences"]["workspace_id"] == target
        with pytest.raises(WorkspaceError):
            account.resolve_published_item(item.workspace_id, item.workspace_item_id)
        assert not (Path(output.output_dir) / "hello.txt").exists()
    with workspace_context(target):
        path, updated = account.resolve_published_item(item.workspace_id, item.workspace_item_id)
        assert path.read_text() == "hello"
        assert updated.data_workspace_id == target
        messages = await get_sqlite_session_store().get_messages(session["id"])
        assert "dt_workspace=" + target in messages[0]["content"]


@pytest.mark.asyncio
async def test_crash_after_session_commit_can_restore_both_stores(account, monkeypatch):
    from deeptutor.services.workspace import session_transfer
    from deeptutor.services.workspace.data_migration import (
        assert_no_pending_recovery,
        operations,
        recover_operation,
    )

    target = account.create_workspace("Destination")["workspace_id"]
    store = get_sqlite_session_store()
    session = await store.create_session("Recover me")
    await store.add_message(session["id"], "user", "retained")
    transfer = session_transfer.transfer_sessions

    def crash(*args, **kwargs):
        transfer(*args, **kwargs)
        raise KeyboardInterrupt("simulated process termination")

    monkeypatch.setattr(session_transfer, "transfer_sessions", crash)
    with pytest.raises(KeyboardInterrupt):
        migrate_data("", target, ["chat"])
    op = operations()[0]
    assert op["status"] == "transferring"
    with pytest.raises(WorkspaceError, match="recovery"):
        assert_no_pending_recovery()
    assert recover_operation(op["id"])["status"] == "recovered"
    assert (await store.get_messages(session["id"]))[0]["content"] == "retained"
    with workspace_context(target):
        assert await get_sqlite_session_store().get_session(session["id"]) is None
    assert_no_pending_recovery()


def test_crash_during_copy_tracks_partial_destination(account, monkeypatch):
    import shutil

    from deeptutor.services.workspace.data_migration import operations, recover_operation

    target = account.create_workspace("Destination")["workspace_id"]
    source = get_path_service().get_book_dir()
    source.mkdir(parents=True, exist_ok=True)
    (source / "draft.md").write_text("keep source")

    def interrupted(src, dst, **kwargs):
        Path(dst).mkdir(parents=True, exist_ok=True)
        (Path(dst) / "partial.txt").write_text("partial")
        raise KeyboardInterrupt("simulated process termination")

    monkeypatch.setattr(shutil, "copytree", interrupted)
    with pytest.raises(KeyboardInterrupt):
        migrate_data("", target, ["book"])
    op = operations()[0]
    assert recover_operation(op["id"])["status"] == "recovered"
    assert (source / "draft.md").read_text() == "keep source"
    with workspace_context(target):
        assert not get_path_service().get_book_dir().exists()


@pytest.mark.asyncio
async def test_legacy_bindings_adopt_default_once_without_copying_materials(account):
    from deeptutor.services.workspace.session_move import migrate_legacy_bindings

    target = account.create_workspace("Legacy")["workspace_id"]
    store = get_sqlite_session_store()
    session = await store.create_session()
    await store.update_session_preferences(session["id"], {"workspace_id": target})
    assert migrate_legacy_bindings() == 1
    prefs = (await store.get_session(session["id"]))["preferences"]
    assert prefs["workspace_id"] == ""
    assert prefs["legacy_workspace_id"] == target
    assert migrate_legacy_bindings() == 0
    with workspace_context(target):
        assert await get_sqlite_session_store().get_session(session["id"]) is None


def test_activity_leases_are_shared_and_exclude_migration(account):
    from deeptutor.services.workspace.activity import data_activity

    with data_activity(), data_activity():
        with pytest.raises(WorkspaceError, match="busy"):
            with data_activity(exclusive=True):
                pass
    with data_activity(exclusive=True):
        with pytest.raises(WorkspaceError, match="busy"):
            with data_activity():
                pass


def test_historical_data_can_be_retained_in_workspace_and_exported(account):
    from deeptutor.multi_user.paths import get_account_path_service

    origin = get_account_path_service().workspace_root / "agent"
    origin.mkdir()
    (origin / "old-result.md").write_text("Historical result /files/outputs/original.txt")
    target = account.create_workspace("Historical")["workspace_id"]
    result = migrate_data("", target, ["historical_agent"])
    assert result["status"] == "completed"
    assert not origin.exists()
    with workspace_context(target):
        saved = (
            get_path_service().get_workspace_dir()
            / "historical"
            / "historical_agent"
            / "old-result.md"
        )
        assert saved.read_text() == "Historical result /files/outputs/original.txt"
    exported = export_data(target, ["historical_agent"])
    from deeptutor.services.workspace.data_migration import export_path

    with zipfile.ZipFile(export_path(exported["id"])) as archive:
        assert archive.read("historical_agent/old-result.md").startswith(b"Historical result")


@pytest.mark.asyncio
async def test_custom_attachment_root_moves_original_files(account, monkeypatch, tmp_path):
    from deeptutor.services.storage import attachment_store
    from deeptutor.services.workspace.session_move import move_chat

    external = tmp_path / "uploads"
    monkeypatch.setattr(
        attachment_store, "load_system_settings", lambda: {"chat_attachment_dir": str(external)}
    )
    target = account.create_workspace("With attachment")["workspace_id"]
    session = await get_sqlite_session_store().create_session()
    with workspace_context():
        url = await attachment_store.get_attachment_store().put(
            session_id=session["id"], attachment_id="doc", filename="notes.txt", data=b"original"
        )
        await get_sqlite_session_store().add_message(session["id"], "user", url)
        move_chat(session["id"], target)
    assert not (external / session["id"] / "doc_notes.txt").exists()
    with workspace_context(target):
        path = attachment_store.get_attachment_store().resolve_path(
            session_id=session["id"], attachment_id="doc", filename="notes.txt"
        )
        assert path.read_bytes() == b"original"


def test_initialized_empty_feature_can_receive_migration(account):
    target = account.create_workspace("Empty initialized")["workspace_id"]
    source = get_path_service().get_workspace_dir() / "reading"
    source.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source / "_catalog.sqlite3") as conn:
        conn.execute("CREATE TABLE materials(id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO materials VALUES ('material')")
    with workspace_context(target):
        destination = get_path_service().get_workspace_dir() / "reading"
        destination.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destination / "_catalog.sqlite3") as conn:
            conn.execute("CREATE TABLE materials(id TEXT PRIMARY KEY)")
    assert not preview("", target, ["reading"])["blockers"]
    assert migrate_data("", target, ["reading"])["status"] == "completed"
    with sqlite3.connect(destination / "_catalog.sqlite3") as conn:
        assert conn.execute("SELECT id FROM materials").fetchone() == ("material",)


def test_explicit_outputs_include_files_without_sessions(account):
    from deeptutor.services.workspace.data_migration import _feature_path, export_path

    root = _feature_path(get_path_service(), "outputs")
    root.mkdir(parents=True, exist_ok=True)
    (root / "orphan.txt").write_text("preserved")
    result = export_data("", ["outputs"])
    with zipfile.ZipFile(export_path(result["id"])) as archive:
        assert archive.read("outputs/orphan.txt") == b"preserved"


def test_legacy_adoption_waits_for_recovery(account):
    from deeptutor.services.workspace.data_migration import _journal_root
    from deeptutor.services.workspace.session_move import migrate_legacy_bindings

    root = _journal_root() / ("a" * 32)
    root.mkdir()
    (root / "operation.json").write_text(json.dumps({"status": "copying"}))
    with pytest.raises(WorkspaceError, match="recovery"):
        migrate_legacy_bindings()
    assert not (_journal_root() / "default-adoption-v1.json").exists()


@pytest.mark.asyncio
async def test_old_request_snapshot_keeps_cited_material(account):
    from deeptutor.services.workspace.data_migration import _sessions
    from deeptutor.services.workspace.dependencies import dependency_closure

    store = get_sqlite_session_store()
    row = await store.create_session("Earlier citation")
    await store.add_message(
        row["id"],
        "user",
        "Read it",
        metadata={"request_snapshot": {"readingReferences": [{"material_id": "old"}]}},
    )
    features, ids = dependency_closure(
        get_path_service(), _sessions(get_path_service()), ["chat"], session_ids={row["id"]}
    )
    assert "reading" in features
    assert row["id"] in ids
