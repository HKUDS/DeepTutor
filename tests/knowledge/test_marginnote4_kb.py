"""Manager handling of connected MarginNote 4 KBs (``type: marginnote4`` pointers).

A connected MN4 library is a pointer with no on-disk KB folder and no index,
so the manager must (1) not prune it as an orphan, (2) not run provider/embedding
normalization on it, and (3) surface its ``type`` through ``get_metadata`` so the
capability layer can bind to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.path_service import PathService


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


def test_mn4_is_connected_but_not_rag_retrievable() -> None:
    """MN4 objects live in their own store, so ``rag_search`` cannot reach them.

    Membership in ``CONNECTED_KB_TYPES`` alone would leave
    ``supports_rag_retrieval`` true and let Book sweep the library, which
    returns nothing and reads as "your MN4 notes had no relevant content"
    instead of "this source needs its own tools".
    """
    from deeptutor.knowledge.kb_types import is_connected_kb, supports_rag_retrieval

    entry = {"type": "marginnote4", "db_path": "/data/mn4/test.db"}
    assert is_connected_kb(entry) is True
    assert supports_rag_retrieval(entry) is False


def test_connected_kbs_backed_by_an_index_stay_retrievable() -> None:
    """Guard the distinction: "connected" is not the same as "unsearchable"."""
    from deeptutor.knowledge.kb_types import supports_rag_retrieval

    for kb_type in ("linked", "lightrag_server", "ima"):
        assert supports_rag_retrieval({"type": kb_type}) is True


def test_deleting_the_kb_removes_its_synced_store(tmp_path: Path, monkeypatch) -> None:
    """The store is ours, unlike an Obsidian vault, so the delete claim holds.

    Leaving it behind would also resurrect every paired device the moment a
    library of the same name is connected again.
    """
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    try:
        from deeptutor.capabilities.marginnote4.store import MarginNoteStore, resolve_db_path

        manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
        manager.register_marginnote4_kb("Lib")
        db_path = resolve_db_path("Lib", metadata={})
        MarginNoteStore(db_path).pair_device(device_name="iPad")
        assert db_path.is_file()

        assert manager.delete_knowledge_base("Lib", confirm=True) is True
        assert not db_path.exists()
        assert "Lib" not in manager.config.get("knowledge_bases", {})
    finally:
        PathService.reset_instance()


def test_deleting_an_obsidian_kb_leaves_its_vault_alone(tmp_path: Path) -> None:
    """The counter-case: an external resource the user manages is never touched."""
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    (vault / "notes" / "a.md").write_text("hi", encoding="utf-8")

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.config.setdefault("knowledge_bases", {})["Vault"] = {
        "type": "obsidian",
        "vault_path": str(vault),
    }
    manager._save_config()

    assert manager.delete_knowledge_base("Vault", confirm=True) is True
    assert (vault / "notes" / "a.md").is_file()


def test_register_rejects_a_name_that_derives_an_existing_store(
    tmp_path: Path, monkeypatch
) -> None:
    """Distinct names can still derive one SQLite file.

    ``default_db_path`` keeps only alphanumerics, ``-`` and ``_``, so "My Lib"
    and "My/Lib" both land on ``My_Lib.db``. Sharing it would merge two
    libraries' objects and let either one's paired devices sync into the other.
    """
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    try:
        manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
        manager.register_marginnote4_kb("My Lib")

        with pytest.raises(ValueError, match="already uses that MarginNote store"):
            manager.register_marginnote4_kb("My/Lib")

        # A name that differs by more than punctuation is fine.
        manager.register_marginnote4_kb("Other Lib")
        assert set(manager.config["knowledge_bases"]) == {"My Lib", "Other Lib"}
    finally:
        PathService.reset_instance()


def test_register_rejects_a_pinned_path_another_library_owns(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    PathService.reset_instance()
    try:
        shared = tmp_path / "stores" / "shared.db"
        manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
        manager.register_marginnote4_kb("First", db_path=str(shared))

        with pytest.raises(ValueError, match="already uses that MarginNote store"):
            manager.register_marginnote4_kb("Second", db_path=str(shared))
    finally:
        PathService.reset_instance()
