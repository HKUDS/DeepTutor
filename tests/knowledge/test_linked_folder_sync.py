"""Persistence of linked-folder sync state (``metadata.json``).

``update_folder_sync_state()`` used to mutate the loaded metadata dict and
return without writing it back, so ``last_sync``/``synced_files`` silently
vanished while the API layer logged success. These tests pin the write-back.
The atomicity contract of the shared writer lives in
``tests/services/test_file_io.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _manager_with_linked_folder(tmp_path: Path) -> tuple[KnowledgeBaseManager, Path, str, Path]:
    """A registered KB with one linked folder containing one markdown file."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    source.mkdir()
    doc = source / "note.md"
    doc.write_text("hello", encoding="utf-8")

    folder_info = manager.link_folder("kb", str(source))
    assert folder_info["last_sync"] is None
    return manager, kb_dir / "metadata.json", folder_info["id"], doc


def test_update_folder_sync_state_persists_to_disk(tmp_path: Path) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    folder = on_disk["linked_folders"][0]
    assert "last_sync" in folder
    assert str(doc) in folder["synced_files"]
    assert folder["file_count"] == 1

    # A fresh manager (new process in real life) must see the sync state too.
    reloaded = KnowledgeBaseManager(base_dir=str(manager.base_dir))
    folder = reloaded.get_linked_folders("kb")[0]
    assert "last_sync" in folder
    assert str(doc) in folder["synced_files"]


def test_update_folder_sync_state_unknown_folder_writes_nothing(tmp_path: Path) -> None:
    manager, metadata_file, _folder_id, doc = _manager_with_linked_folder(tmp_path)
    before = metadata_file.read_bytes()

    manager.update_folder_sync_state("kb", "no-such-id", [str(doc)])

    assert metadata_file.read_bytes() == before


def test_empty_successful_sync_records_last_sync_without_changing_file_state(
    tmp_path: Path,
) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    manager.update_folder_sync_state("kb", folder_id, [str(doc)])
    before = json.loads(metadata_file.read_text(encoding="utf-8"))["linked_folders"][0]

    manager.update_folder_sync_state("kb", folder_id, [])

    after = json.loads(metadata_file.read_text(encoding="utf-8"))["linked_folders"][0]
    assert after["last_sync"]
    assert after["last_sync"] >= before["last_sync"]
    assert after["synced_files"] == before["synced_files"]


def test_unlink_removes_only_the_source_registration(tmp_path: Path) -> None:
    manager, _metadata_file, folder_id, _doc = _manager_with_linked_folder(tmp_path)
    kb_dir = manager.base_dir / "kb"
    raw_file = kb_dir / "raw" / "note.md"
    index_marker = kb_dir / "version-1" / "index.marker"
    raw_file.parent.mkdir(parents=True)
    index_marker.parent.mkdir(parents=True)
    raw_file.write_text("imported", encoding="utf-8")
    index_marker.write_text("index", encoding="utf-8")

    assert manager.unlink_folder("kb", folder_id) is True

    assert manager.get_linked_folders("kb") == []
    assert raw_file.read_text(encoding="utf-8") == "imported"
    assert index_marker.read_text(encoding="utf-8") == "index"
