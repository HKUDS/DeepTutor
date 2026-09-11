from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.ingestion import url_material_id
from deeptutor.reading.models import ReadingPosition
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning.reading_migration import WatchingToReadingMigration
from deeptutor.video_learning.service import TimedMediaStore, material_id_for


@pytest.mark.asyncio
async def test_legacy_timed_media_projects_into_reading_without_notebook_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_store = TimedMediaStore(tmp_path / "timed-media")
    reading = ReadingStore(tmp_path / "reading")
    catalog = ReadingCatalogStore(reading.root)
    notebook = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    timed_id = material_id_for("abc123xyz00")
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
                "thumbnail_url": "https://img.example/cover.jpg",
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
    monkeypatch.setattr(video_notes, "get_timed_media_store", lambda: timed_store)
    first_note = video_notes.create_note(notebook, timed_id, "First note", 2)
    second_note = video_notes.create_note(notebook, timed_id, "Second note", 33)

    migration = WatchingToReadingMigration(
        timed_media_store=timed_store,
        reading_store=reading,
        catalog=catalog,
        notebook_manager=notebook,
    )
    result = await migration.migrate(
        timed_id,
        session_id="session-1",
        session_title="Legacy Watching conversation",
    )
    material_id = url_material_id("https://youtu.be/abc123xyz00")

    assert result.timed_media_id == timed_id
    assert result.reading_material_id == material_id
    assert result.reading_workspace_id != timed_id
    workspace = catalog.get_workspace(result.reading_workspace_id)
    assert workspace is not None
    assert workspace.active_material_id == material_id
    assert catalog.list_sessions(result.reading_workspace_id)[0].session_id == "session-1"

    manifest = reading.manifest(material_id)
    assert manifest.render_mode == "video"
    assert manifest.unit == "segment"
    assert [row.source_href for row in reading.unit_references(material_id)] == ["#t=0", "#t=30"]
    assert reading.position(material_id).source_anchor == "#t=35"
    assert reading.position(material_id).locator == 2

    annotations = reading.annotations(material_id)
    assert [(row.locator, row.note, row.source_anchor) for row in annotations] == [
        (1, first_note["body"], "#t=2"),
        (2, second_note["body"], "#t=33"),
    ]
    assert all(row.kind == "note" for row in annotations)
    assert all(row.annotation_id.startswith("legacy-video-") for row in annotations)
    records = notebook.get_notebook(first_note["notebook_id"])["records"]
    assert [row["id"] for row in records] == [first_note["note_id"], second_note["note_id"]]

    second = await migration.migrate(
        timed_id,
        session_id="session-1",
        session_title="Legacy Watching conversation",
    )
    assert second.reading_material_id == material_id
    assert len(reading.annotations(material_id)) == 2
    assert reading.position(material_id).source_anchor == "#t=35"
    assert timed_store.get(timed_id)["learning"]["last_position"] == 35


@pytest.mark.asyncio
async def test_repeated_migration_preserves_newer_reading_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_store = TimedMediaStore(tmp_path / "timed-media")
    reading = ReadingStore(tmp_path / "reading")
    catalog = ReadingCatalogStore(reading.root)
    notebook = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    timed_id = material_id_for("abc123xyz00")
    timed_store.save(
        {
            "version": 1,
            "type": "timed_media",
            "material_id": timed_id,
            "source": {"video_id": "abc123xyz00"},
            "metadata": {"title": "Legacy lecture"},
            "transcript": {
                "cues": [
                    {"start": 0, "text": "Opening."},
                    {"start": 30, "text": "Later."},
                ]
            },
            "learning": {"last_position": 35},
        }
    )
    monkeypatch.setattr(video_notes, "get_timed_media_store", lambda: timed_store)
    migration = WatchingToReadingMigration(
        timed_media_store=timed_store,
        reading_store=reading,
        catalog=catalog,
        notebook_manager=notebook,
    )
    first = await migration.migrate(timed_id)
    reading.save_position(
        first.reading_material_id,
        ReadingPosition(
            locator=1,
            source_anchor="#t=1",
            percentage=0,
        ),
    )

    await migration.migrate(timed_id)

    assert reading.position(first.reading_material_id).source_anchor == "#t=1"
