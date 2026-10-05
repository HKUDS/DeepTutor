"""Tests for KnowledgeBaseManager.list_knowledge_bases() orphan pruning.

When a KB entry remains in ``kb_config.json`` but its on-disk directory has
been removed (failed init, manual ``rm -rf``, etc.), the entry must be
pruned from the list — and from the persisted config — so the UI does not
keep surfacing zombie KBs the user cannot act on.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _seed_kb(manager: KnowledgeBaseManager, name: str) -> Path:
    kb_dir = manager.base_dir / name
    (kb_dir / "raw").mkdir(parents=True, exist_ok=True)
    (kb_dir / "version-1").mkdir(parents=True, exist_ok=True)
    (kb_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "description": "",
        "status": "ready",
    }
    manager._save_config()
    return kb_dir


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_list_prunes_orphan_config_entries(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _seed_kb(manager, "alive")
    _seed_kb(manager, "ghost")
    shutil.rmtree(manager.base_dir / "ghost")

    listed = manager.list_knowledge_bases()

    assert listed == ["alive"]
    persisted = _read_config(manager.config_file).get("knowledge_bases", {})
    assert "ghost" not in persisted
    assert "alive" in persisted


def test_list_keeps_entries_when_directory_present(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _seed_kb(manager, "kept")

    assert manager.list_knowledge_bases() == ["kept"]
    assert "kept" in _read_config(manager.config_file).get("knowledge_bases", {})


def test_get_default_reuses_available_names(monkeypatch, tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))

    def _unexpected_rescan() -> list[str]:
        raise AssertionError("available names should avoid another KB scan")

    monkeypatch.setattr(manager, "list_knowledge_bases", _unexpected_rescan)

    assert manager.get_default(available_names=["first", "second"]) == "first"


def test_list_keeps_recent_entry_with_missing_dir(tmp_path: Path) -> None:
    """During KB creation the config entry is written before the directory
    exists. A concurrent ``list`` must not delete that in-flight entry —
    a recent ``updated_at`` keeps it in the list.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.config.setdefault("knowledge_bases", {})["in-flight"] = {
        "path": "in-flight",
        "status": "initializing",
        "updated_at": datetime.now().isoformat(),
    }
    manager._save_config()

    assert manager.list_knowledge_bases() == ["in-flight"]
    assert "in-flight" in _read_config(manager.config_file).get("knowledge_bases", {})


def test_auto_register_legacy_storage_marks_needs_reindex(tmp_path: Path) -> None:
    kb_dir = tmp_path / "legacy"
    (kb_dir / "raw").mkdir(parents=True)
    legacy_storage = kb_dir / "rag_storage"
    legacy_storage.mkdir()
    (legacy_storage / "old.json").write_text("{}", encoding="utf-8")

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))

    assert manager.list_knowledge_bases() == ["legacy"]
    entry = _read_config(manager.config_file)["knowledge_bases"]["legacy"]
    assert entry["status"] == "needs_reindex"
    assert entry["needs_reindex"] is True


def test_repeated_catalog_reads_reuse_probes_and_return_independent_results(tmp_path, monkeypatch):
    """A slow index is probed once per snapshot, not per list request (#1711)."""
    from deeptutor.knowledge import manager as module

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _seed_kb(manager, "book")
    original = module.inspect_kb_versions
    probes = []

    def inspect(*args, **kwargs):
        probes.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "inspect_kb_versions", inspect)
    names = manager.list_knowledge_bases()
    info = manager.get_info("book", refresh_config=False, default_name=names[0])
    initial = len(probes)
    assert initial > 0
    info["statistics"]["index_versions"].clear()
    for _ in range(6):
        names = manager.list_knowledge_bases()
        fresh = manager.get_info("book", refresh_config=False, default_name=names[0])
        assert fresh["statistics"]["index_versions"]
    assert len(probes) == initial

    # A background process publishes status in the atomic registry.
    config = _read_config(manager.config_file)
    config["knowledge_bases"]["book"]["description"] = "updated elsewhere"
    manager.config_file.write_text(json.dumps(config), encoding="utf-8")
    manager.list_knowledge_bases()
    fresh = manager.get_info("book", refresh_config=False, default_name="book")
    assert fresh["metadata"]["description"] == "updated elsewhere"
    assert len(probes) > initial


def test_catalog_rechecks_manual_index_changes_after_snapshot_expires(tmp_path, monkeypatch):
    from deeptutor.knowledge import manager as module

    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = _seed_kb(manager, "book")
    manager.list_knowledge_bases()
    manager.get_info("book", refresh_config=False, default_name="book")
    shutil.rmtree(kb_dir / "version-1")
    now[0] += module._CATALOG_CACHE_SECONDS + 1
    manager.list_knowledge_bases()
    fresh = manager.get_info("book", refresh_config=False, default_name="book")
    assert fresh["statistics"]["index_versions"] == []
