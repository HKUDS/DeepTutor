from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.ingestion import url_material_id
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning.reading_migration import WatchingToReadingMigration
from deeptutor.video_learning.service import TimedMediaStore, material_id_for


class SessionStore:
    def __init__(self, session: dict[str, Any]) -> None:
        self.session = session
        self.preference_updates: list[tuple[str, dict[str, Any]]] = []

    async def list_sessions(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return [self.session][offset : offset + limit]

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        return self.session if self.session["id"] == session_id else None

    async def update_session_preferences(
        self,
        session_id: str,
        updates: dict[str, Any],
    ) -> bool:
        self.preference_updates.append((session_id, updates))
        self.session.setdefault("preferences", {}).update(updates)
        return True


def _legacy_session(timed_id: str) -> dict[str, Any]:
    return {
        "id": "legacy-session",
        "session_id": "legacy-session",
        "title": "Legacy lecture question",
        "preferences": {
            "capability": "immersive_watching",
            "workspace_mode": "immersive_watching",
            "session_kind": "immersive_watching",
            "timed_media_id": timed_id,
            "timed_media_viewport": {"time_seconds": 35},
        },
        "messages": [],
    }


def _timed_store(tmp_path: Path, timed_id: str) -> TimedMediaStore:
    store = TimedMediaStore(tmp_path / "timed-media")
    store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {
                "provider": "youtube",
                "video_id": "abc123xyz00",
                "url": "https://youtu.be/abc123xyz00",
            },
            "metadata": {"title": "Legacy lecture", "duration_seconds": 120},
            "transcript": {
                "status": "ready",
                "cues": [{"start": 0, "end": 12, "text": "Opening idea."}],
            },
            "learning": {"last_position": 35},
        }
    )
    return store


def _install_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timed_store: TimedMediaStore,
) -> None:
    reading = ReadingStore(tmp_path / "reading")
    catalog = ReadingCatalogStore(reading.root)
    notebook = NotebookManager(base_dir=str(tmp_path / "notebooks"))
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


@pytest.mark.asyncio
async def test_session_list_migrates_legacy_watching_preferences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_id = material_id_for("abc123xyz00")
    store = SessionStore(_legacy_session(timed_id))
    _install_migration(tmp_path, monkeypatch, _timed_store(tmp_path, timed_id))
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    response = await sessions_router.list_sessions(1, 0)

    preferences = response["sessions"][0]["preferences"]
    assert preferences["capability"] == "chat"
    assert preferences["workspace_mode"] == "immersive_reading"
    assert preferences["session_kind"] == "immersive_reading"
    assert preferences["reading_material_id"] == url_material_id("https://youtu.be/abc123xyz00")
    assert preferences["reading_workspace_id"].startswith("rw_")
    assert preferences["timed_media_id"] == timed_id
    assert "timed_media_viewport" not in preferences
    assert store.preference_updates[0][0] == "legacy-session"


@pytest.mark.asyncio
async def test_failed_legacy_migration_leaves_session_response_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _legacy_session("0123456789abcdef")
    store = SessionStore(session)
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    class FailedMigration:
        async def migrate(self, *_args, **_kwargs):
            raise RuntimeError("legacy media unavailable")

    monkeypatch.setattr(
        "deeptutor.video_learning.reading_migration.WatchingToReadingMigration",
        FailedMigration,
    )

    response = await sessions_router.get_session("legacy-session")

    assert response["preferences"] == session["preferences"]
    assert store.preference_updates == []
