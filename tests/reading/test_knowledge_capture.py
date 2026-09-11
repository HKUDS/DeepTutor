from __future__ import annotations

from pathlib import Path

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.knowledge_capture import (
    mastery_source_records,
    organize_workspace_notes,
    send_workspace_to_notebook,
)
from deeptutor.reading.models import Annotation
from deeptutor.reading.store import ReadingStore
from deeptutor.services.notebook.service import NotebookManager


def test_notes_keep_quotes_locators_and_create_real_notebook_record(tmp_path: Path) -> None:
    reading, catalog, workspace_id, material_id = _workspace(tmp_path)
    notebook_manager = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    notebook = notebook_manager.create_notebook("Research notes")

    notes = organize_workspace_notes(workspace_id, catalog=catalog, reading_store=reading)
    result = send_workspace_to_notebook(
        workspace_id,
        [notebook["id"]],
        catalog=catalog,
        reading_store=reading,
        notebook_manager=notebook_manager,
    )

    assert "> Evidence belongs here." in notes.markdown
    assert "locator 1" in notes.markdown
    assert result["record"]["type"] == "reading"
    stored = notebook_manager.get_notebook(notebook["id"])
    assert stored["records"][0]["metadata"]["reading_material_ids"] == [material_id]


def test_mastery_sources_are_bounded_and_material_labelled(tmp_path: Path) -> None:
    reading, catalog, workspace_id, material_id = _workspace(tmp_path)

    records = mastery_source_records(
        workspace_id,
        catalog=catalog,
        reading_store=reading,
        max_chars_per_material=500,
    )

    assert records[0]["id"] == material_id
    assert records[0]["title"] == "Grounded Paper"
    assert records[0]["output"].startswith("[section 1]")
    assert len(records[0]["output"]) <= 500


def _workspace(tmp_path: Path):
    root = tmp_path / "reading"
    reading = ReadingStore(root)
    catalog = ReadingCatalogStore(root)
    manifest = reading.ingest_units(
        "e" * 16,
        filename="grounded.md",
        title="Grounded Paper",
        units=["Evidence belongs here. " * 80],
    )
    catalog.register_manifest(manifest)
    workspace = catalog.create_workspace("Grounded Research", [manifest.material_id])
    reading.save_annotation(
        manifest.material_id,
        Annotation(
            annotation_id="",
            locator=1,
            kind="highlight",
            quote="Evidence belongs here.",
            note="Use this in the synthesis.",
        ),
    )
    return reading, catalog, workspace.workspace_id, manifest.material_id
