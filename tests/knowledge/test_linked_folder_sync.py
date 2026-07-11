"""Persistence of linked-folder sync state (``metadata.json``).

``update_folder_sync_state()`` used to mutate the loaded metadata dict and
return without writing it back, so ``last_sync``/``synced_files`` silently
vanished while the API layer logged success. These tests pin the write-back
and the atomicity contract of the metadata writer.
"""

from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from deeptutor.knowledge.config_store import KBConfigStore, write_json_atomic
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.metadata_store import get_metadata_store


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


def test_concurrent_folder_links_keep_both_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, metadata_file, _folder_id, _doc = _manager_with_linked_folder(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "first.md").write_text("one", encoding="utf-8")
    (second / "second.md").write_text("two", encoding="utf-8")

    entered = threading.Event()
    release = threading.Event()
    original = KBConfigStore.transaction

    def stall_first_metadata_transaction(self, mutate):
        if self.config_path == metadata_file and not entered.is_set():

            def stalled(metadata):
                entered.set()
                assert release.wait(10)
                return mutate(metadata)

            return original(self, stalled)
        return original(self, mutate)

    monkeypatch.setattr(KBConfigStore, "transaction", stall_first_metadata_transaction)
    failures: list[BaseException] = []

    def link(path: Path) -> None:
        try:
            manager.link_folder("kb", str(path))
        except BaseException as exc:  # pragma: no cover - assertion diagnostic
            failures.append(exc)

    one = threading.Thread(target=link, args=(first,))
    two = threading.Thread(target=link, args=(second,))
    one.start()
    assert entered.wait(10)
    two.start()
    release.set()
    one.join(10)
    two.join(10)

    assert not failures
    assert not one.is_alive() and not two.is_alive()
    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert {item["path"] for item in on_disk["linked_folders"]} == {
        str((tmp_path / "notes").resolve()),
        str(first.resolve()),
        str(second.resolve()),
    }


def test_metadata_store_preserves_unrelated_metadata_updates(tmp_path: Path) -> None:
    """Metadata writers share one serialized read-modify-write primitive."""
    metadata_file = tmp_path / "metadata.json"
    first = get_metadata_store(metadata_file)
    second = get_metadata_store(metadata_file)
    entered = threading.Event()
    release = threading.Event()

    def slow_mutate(metadata: dict) -> None:
        metadata["linked_folders"] = [{"id": "folder"}]
        entered.set()
        assert release.wait(10)

    thread = threading.Thread(target=first.transaction, args=(slow_mutate,))
    thread.start()
    assert entered.wait(10)

    second_thread = threading.Thread(
        target=second.transaction,
        args=(lambda metadata: metadata.setdefault("file_hashes", {}).update({"note.md": "hash"}),),
    )
    second_thread.start()
    release.set()
    thread.join(10)
    second_thread.join(10)

    assert not thread.is_alive() and not second_thread.is_alive()
    assert json.loads(metadata_file.read_text(encoding="utf-8")) == {
        "linked_folders": [{"id": "folder"}],
        "file_hashes": {"note.md": "hash"},
    }


def test_metadata_store_never_recreates_a_deleted_kb_directory(tmp_path: Path) -> None:
    metadata_file = tmp_path / "deleted-kb" / "metadata.json"

    with pytest.raises(FileNotFoundError):
        get_metadata_store(metadata_file).transaction(lambda metadata: metadata.update(ok=True))

    assert not metadata_file.parent.exists()


def test_write_json_atomic_preserves_original_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "metadata.json"
    target.write_text('{"ok": true}', encoding="utf-8")

    with pytest.raises(TypeError):
        write_json_atomic(target, {"bad": object()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    # The failed write must not litter temp files next to the target.
    assert [p.name for p in tmp_path.iterdir()] == ["metadata.json"]
