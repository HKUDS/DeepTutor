from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.session.legacy_migration import (
    LegacyChatSessionMigrator,
    LegacyMigrationError,
)
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _write_legacy(path: Path, sessions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "sessions": sessions}), encoding="utf-8")


def _session(session_id: str = "chat_original") -> dict:
    return {
        "session_id": session_id,
        "title": "Original title",
        "created_at": 100.5,
        "updated_at": 103.5,
        "settings": {
            "kb_name": "physics",
            "enable_rag": True,
            "enable_web_search": True,
        },
        "messages": [
            {"role": "user", "content": "hello", "timestamp": 101.5},
            {
                "role": "assistant",
                "content": "answer",
                "timestamp": 102.5,
                "sources": {"rag": [{"title": "source"}], "web": []},
            },
        ],
    }


@pytest.mark.asyncio
async def test_migrates_timestamps_settings_sources_and_archives(tmp_path) -> None:
    source = tmp_path / "workspace" / "chat" / "chat" / "sessions.json"
    archive = tmp_path / "archive" / "legacy-chat"
    _write_legacy(source, [_session()])
    store = SQLiteSessionStore(tmp_path / "chat_history.db")

    report = await LegacyChatSessionMigrator(store, source, archive).migrate()

    assert report.imported == 1
    assert report.messages == 2
    assert report.failed == 0
    assert not source.exists()
    assert Path(report.archived_to).exists()
    detail = await store.get_session_with_messages("chat_original")
    assert detail is not None
    assert detail["title"] == "Original title"
    assert detail["created_at"] == 100.5
    assert detail["updated_at"] == 103.5
    assert detail["preferences"]["knowledge_bases"] == ["physics"]
    assert detail["preferences"]["tools"] == ["web_search"]
    assert [row["created_at"] for row in detail["messages"]] == [101.5, 102.5]
    assert detail["messages"][1]["metadata"]["sources"]["rag"][0]["title"] == "source"


@pytest.mark.asyncio
async def test_existing_session_is_not_overwritten_and_repeat_is_idempotent(
    tmp_path,
) -> None:
    source = tmp_path / "sessions.json"
    archive = tmp_path / "archive"
    payload = _session("chat_collision")
    _write_legacy(source, [payload])
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    await store.create_session("Keep me", "chat_collision")
    migrator = LegacyChatSessionMigrator(store, source, archive)

    first = await migrator.migrate()
    assert first.imported == 0 and first.skipped == 1
    assert (await store.get_session("chat_collision"))["title"] == "Keep me"

    archived = Path(first.archived_to)
    source.write_bytes(archived.read_bytes())
    second = await migrator.migrate()
    assert second.imported == 0 and second.skipped == 1
    assert not source.exists()
    assert len((archive / "migration-ledger.json").read_text().splitlines()) > 1


@pytest.mark.asyncio
async def test_corrupt_or_partial_migration_keeps_source(tmp_path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{bad", encoding="utf-8")
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    migrator = LegacyChatSessionMigrator(store, corrupt, tmp_path / "archive")
    with pytest.raises(LegacyMigrationError):
        await migrator.migrate()
    assert corrupt.exists()
    assert list((tmp_path / "archive").glob("pre-migration-*.json"))

    class _PartiallyFailingRepository:
        def __init__(self) -> None:
            self.imported: set[str] = set()
            self.fail_once = True

        async def import_legacy_session(self, **session):
            session_id = session["session_id"]
            if session_id == "chat_b" and self.fail_once:
                self.fail_once = False
                raise RuntimeError("simulated backend error")
            if session_id in self.imported:
                return {"imported": False, "message_count": 0}
            self.imported.add(session_id)
            return {"imported": True, "message_count": len(session["messages"])}

    source = tmp_path / "partial.json"
    _write_legacy(source, [_session("chat_a"), _session("chat_b")])
    repository = _PartiallyFailingRepository()
    partial = LegacyChatSessionMigrator(repository, source, tmp_path / "archive-partial")
    with pytest.raises(LegacyMigrationError):
        await partial.migrate()
    assert source.exists()

    recovered = await partial.migrate()
    assert recovered.imported == 1
    assert recovered.skipped == 1
    assert not source.exists()


@pytest.mark.asyncio
async def test_empty_and_dry_run_are_safe(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    source = tmp_path / "sessions.json"
    _write_legacy(source, [])
    migrator = LegacyChatSessionMigrator(store, source, tmp_path / "archive")

    dry_run = await migrator.migrate(dry_run=True)
    assert dry_run.imported == 0
    assert source.exists()

    applied = await migrator.migrate()
    assert applied.imported == 0
    assert not source.exists()
