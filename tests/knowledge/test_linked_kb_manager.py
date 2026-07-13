"""Manager handling of linked KBs (``type: linked`` engine-index pointers).

A linked KB mounts a pre-built index in place: no on-disk folder under
``base_dir``, read-only, and — critically — deleting it must never touch the
user's external files. Mirrors the Obsidian pointer guarantees but for an
engine-backed index queried via its bound ``rag_provider``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _external_index(tmp_path: Path) -> Path:
    """A self-contained external folder holding a ready LlamaIndex version."""
    ext = tmp_path / "external_kb"
    version = ext / "version-1"
    version.mkdir(parents=True)
    (version / "docstore.json").write_text("{}", encoding="utf-8")
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps({"version": "version-1", "signature": "abc", "layout": "flat"}),
        encoding="utf-8",
    )
    return ext


def test_register_linked_kb_writes_pointer(tmp_path: Path) -> None:
    ext = _external_index(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    entry = manager.register_linked_kb("Linked", str(ext), "llamaindex", stats={"doc_count": 5})

    assert entry["type"] == "linked"
    assert entry["rag_provider"] == "llamaindex"
    assert Path(entry["external_path"]) == ext.resolve()
    assert entry["status"] == "ready"
    assert entry["last_indexed_count"] == 5
    # No KB folder is created under base_dir.
    assert not (manager.base_dir / "Linked").exists()


def test_register_linked_kb_rejects_missing_folder(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    with pytest.raises(ValueError):
        manager.register_linked_kb("X", str(tmp_path / "nope"), "llamaindex")


def test_register_linked_kb_rejects_name_clash(tmp_path: Path) -> None:
    ext = _external_index(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_linked_kb("Dup", str(ext), "llamaindex")
    with pytest.raises(ValueError):
        manager.register_linked_kb("Dup", str(ext), "graphrag")


def test_delete_linked_kb_preserves_external_folder(tmp_path: Path) -> None:
    ext = _external_index(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_linked_kb("Linked", str(ext), "llamaindex")

    assert manager.delete_knowledge_base("Linked", confirm=True) is True

    # The pointer entry is gone, but the user's external index is untouched.
    assert "Linked" not in manager.list_knowledge_bases()
    assert (ext / "version-1" / "docstore.json").exists()


def test_linked_entry_survives_orphan_prune(tmp_path: Path) -> None:
    ext = _external_index(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_linked_kb("Linked", str(ext), "graphrag")

    # No ``kbs/Linked`` directory exists, yet the pointer must not be pruned.
    assert "Linked" in manager.list_knowledge_bases()


def test_get_metadata_surfaces_external_path_and_provider(tmp_path: Path) -> None:
    ext = _external_index(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_linked_kb("Linked", str(ext), "graphrag")

    meta = manager.get_metadata("Linked")
    assert meta["type"] == "linked"
    assert Path(meta["external_path"]) == ext.resolve()
    assert meta["rag_provider"] == "graphrag"


def test_reconcile_skips_linked_entry(tmp_path: Path) -> None:
    ext = _external_index(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_linked_kb("Linked", str(ext), "llamaindex")

    # A fresh load runs the reconcile path; the linked pointer stays intact and
    # is never flagged for reindex.
    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = reloaded.config["knowledge_bases"]["Linked"]
    assert entry["type"] == "linked"
    assert entry.get("needs_reindex") is not True
    assert "index_versions" not in entry
