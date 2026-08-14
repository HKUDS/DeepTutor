"""Manager handling of connected MarginNote 4 KBs (``type: marginnote4`` pointers).

A connected MN4 library is a pointer with no on-disk KB folder and no index,
so the manager must (1) not prune it as an orphan, (2) not run provider/embedding
normalization on it, and (3) surface its ``type`` through ``get_metadata`` so the
capability layer can bind to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _seed_mn4(manager: KnowledgeBaseManager, name: str, db_path: str = "") -> None:
    entry: dict = {"type": "marginnote4", "description": "Connected MN4 library"}
    if db_path:
        entry["db_path"] = db_path
    manager.config.setdefault("knowledge_bases", {})[name] = entry
    manager._save_config()


def test_mn4_entry_survives_orphan_prune(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_mn4(manager, "MyLibrary")
    assert "MyLibrary" in manager.list_knowledge_bases()
    persisted = json.loads(manager.config_file.read_text(encoding="utf-8"))
    assert "MyLibrary" in persisted.get("knowledge_bases", {})


def test_get_metadata_surfaces_type(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_mn4(manager, "MyLibrary", db_path="/data/mn4/test.db")
    meta = manager.get_metadata("MyLibrary")
    assert meta["type"] == "marginnote4"
    assert meta["db_path"] == "/data/mn4/test.db"


def test_reconcile_does_not_clobber_mn4_entry(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_mn4(manager, "MyLibrary", db_path="/data/mn4/test.db")
    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = reloaded.config["knowledge_bases"]["MyLibrary"]
    assert entry["type"] == "marginnote4"
    assert entry["db_path"] == "/data/mn4/test.db"
    assert entry.get("needs_reindex") is not True
    assert "index_versions" not in entry


def test_ordinary_kb_metadata_has_no_mn4_fields(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = manager.base_dir / "plain"
    (kb_dir / "version-1").mkdir(parents=True)
    (kb_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    manager.config.setdefault("knowledge_bases", {})["plain"] = {"path": "plain", "status": "ready"}
    manager._save_config()
    meta = manager.get_metadata("plain")
    assert "type" not in meta
    assert "db_path" not in meta


def test_register_marginnote4_kb_creates_pointer(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = manager.register_marginnote4_kb(
        "MyLibrary", db_path="/data/mn4/test.db", description="Test lib"
    )
    assert entry["type"] == "marginnote4"
    assert entry["db_path"] == "/data/mn4/test.db"
    assert entry["description"] == "Test lib"
    assert "MyLibrary" in manager.list_knowledge_bases()


def test_register_marginnote4_kb_default_path(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = manager.register_marginnote4_kb("AutoPath")
    assert entry["type"] == "marginnote4"
    assert "db_path" not in entry  # capability derives default from name


def test_register_marginnote4_kb_rejects_duplicate(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_marginnote4_kb("Lib")
    import pytest

    with pytest.raises(ValueError, match="already exists"):
        manager.register_marginnote4_kb("Lib")
