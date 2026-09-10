from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.ingestion import url_material_id
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import (
    TurnRuntimeManager,
    _request_snapshot_metadata,
    _timed_media_id,
    _workspace_mode,
)
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning.reading_migration import WatchingToReadingMigration
from deeptutor.video_learning.service import TimedMediaStore, material_id_for


def test_legacy_replay_fields_are_normalized() -> None:
    assert _timed_media_id(" ABCDEF0123456789 ") == "abcdef0123456789"
    assert _timed_media_id("../../etc/passwd") == ""
    assert _workspace_mode("immersive_watching") == ""


def test_timed_media_id_is_saved_for_legacy_regenerate() -> None:
    metadata = _request_snapshot_metadata(
        payload={"timed_media_id": "0123456789abcdef"},
        content="explain",
        capability="immersive_watching",
        config={},
        attachments=[],
        notebook_references=[],
        history_references=[],
        partner_group_references=[],
        question_notebook_references=[],
        book_references=[],
        persona="",
        memory_references=[],
        llm_selection=None,
    )
    snapshot = metadata["request_snapshot"]
    assert snapshot["timedMediaId"] == "0123456789abcdef"
    assert "timedMediaViewport" not in snapshot


def _legacy_media(timed_store: TimedMediaStore, timed_id: str) -> None:
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {
                "provider": "youtube",
                "video_id": "abc123xyz00",
                "url": "https://youtu.be/abc123xyz00",
            },
            "metadata": {
                "title": "Legacy lecture",
                "duration_seconds": 120,
            },
            "transcript": {
                "status": "ready",
                "cues": [
                    {"start": 0, "end": 12, "text": "Opening idea."},
                    {"start": 30, "end": 42, "text": "Later idea."},
                ],
            },
            "learning": {"last_position": 35},
        }
    )


@pytest.mark.asyncio
async def test_legacy_watching_turn_migrates_to_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    try:
        timed_store = TimedMediaStore(tmp_path / "timed-media")
        reading = ReadingStore(tmp_path / "reading")
        catalog = ReadingCatalogStore(reading.root)
        notebook = NotebookManager(base_dir=str(tmp_path / "notebooks"))
        timed_id = material_id_for("abc123xyz00")
        _legacy_media(timed_store, timed_id)
        monkeypatch.setattr(video_notes, "get_timed_media_store", lambda: timed_store)
        migration = WatchingToReadingMigration(
            timed_media_store=timed_store,
            reading_store=reading,
            catalog=catalog,
            notebook_manager=notebook,
        )
        monkeypatch.setattr(
            "deeptutor.video_learning.reading_migration.WatchingToReadingMigration",
            lambda: migration,
        )
        monkeypatch.setattr(
            "deeptutor.reading.ReadingCatalogStore",
            lambda _root=None: catalog,
        )

        runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "sessions.db"))

        async def no_execution(execution):
            return None

        monkeypatch.setattr(runtime, "_run_turn", no_execution)
        session, turn = await runtime.start_turn(
            {
                "content": "Explain the second idea",
                "capability": "immersive_watching",
                "workspace_mode": "immersive_watching",
                "timed_media_id": timed_id,
                "timed_media_viewport": {"time_seconds": 35},
                "language": "en",
                "tools": [],
            }
        )
        await runtime._executions[turn["id"]].task

        payload = runtime._executions[turn["id"]].payload
        material_id = url_material_id("https://youtu.be/abc123xyz00")
        assert payload["capability"] == "chat"
        assert payload["workspace_mode"] == "immersive_reading"
        assert payload["reading_material_id"] == material_id
        assert payload["reading_workspace_id"].startswith("rw_")
        assert "timed_media_id" not in payload
        assert "timed_media_viewport" not in payload

        loaded = await runtime.store.get_session(session["id"])
        assert loaded is not None
        preferences = loaded["preferences"]
        assert preferences["capability"] == "chat"
        assert preferences["workspace_mode"] == "immersive_reading"
        assert preferences["session_kind"] == "immersive_reading"
        assert preferences["reading_material_id"] == material_id
        assert preferences["timed_media_id"] == timed_id
        assert "timed_media_viewport" not in preferences
    finally:
        PathService.reset_instance()


@pytest.mark.asyncio
async def test_legacy_watching_turn_fails_closed_when_media_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    try:
        runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "sessions.db"))
        with pytest.raises(RuntimeError, match="legacy Watching video"):
            await runtime.start_turn(
                {
                    "content": "Explain here",
                    "capability": "immersive_watching",
                    "workspace_mode": "immersive_watching",
                    "timed_media_id": "0123456789abcdef",
                    "language": "en",
                    "tools": [],
                }
            )
    finally:
        PathService.reset_instance()


@pytest.mark.asyncio
async def test_legacy_regenerate_snapshot_keeps_watching_migration_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    store = SQLiteSessionStore(tmp_path / "regenerate.db")
    session = await store.create_session()
    timed_id = material_id_for("abc123xyz00")
    await store.update_session_preferences(
        session["id"],
        {
            "capability": "immersive_watching",
            "workspace_mode": "immersive_watching",
            "timed_media_id": timed_id,
        },
    )
    await store.add_message(
        session["id"],
        role="user",
        content="Explain this part",
        capability="immersive_watching",
        metadata={
            "request_snapshot": {
                "capability": "immersive_watching",
                "workspaceMode": "immersive_watching",
                "timedMediaId": timed_id,
            }
        },
    )
    runtime = TurnRuntimeManager(store)
    replayed: dict[str, object] = {}

    async def capture_start_turn(payload: dict[str, object]):
        replayed.update(payload)
        return session, {"id": "replayed-turn", "session_id": session["id"]}

    monkeypatch.setattr(runtime, "start_turn", capture_start_turn)
    await runtime.regenerate_last_turn(session["id"])

    assert replayed["capability"] == "immersive_watching"
    assert replayed["workspace_mode"] == ""
    assert replayed["timed_media_id"] == timed_id


def test_watching_loop_capability_is_not_registered() -> None:
    from deeptutor.capabilities.registry import LOOP_CAPABILITIES
    from deeptutor.runtime.registry.capability_registry import get_capability_registry

    assert get_capability_registry().get("immersive_watching") is None
    assert all(capability.name != "immersive_watching" for capability in LOOP_CAPABILITIES)
