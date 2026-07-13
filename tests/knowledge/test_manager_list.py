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
