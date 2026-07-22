"""Manager handling of connected Obsidian KBs (``type: obsidian`` pointers).

A connected vault is a pointer with no on-disk KB folder and no index, so the
manager must (1) not prune it as an orphan, (2) not run provider/embedding
normalization on it, and (3) surface its ``type`` / ``vault_path`` through
``get_metadata`` so the capability layer can bind to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _seed_obsidian(manager: KnowledgeBaseManager, name: str, vault_path: str) -> None:
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "type": "obsidian",
        "vault_path": vault_path,
        "description": "Connected vault",
        # A hostile leftover provider that the load reconcile would normally
        # rewrite + flag for reindex — must be left alone for obsidian entries.
        "rag_provider": "pageindex",
    }
    manager._save_config()


def test_obsidian_entry_survives_orphan_prune(tmp_path: Path) -> None:
    vault = tmp_path / "my-vault"
    vault.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_obsidian(manager, "Vault", str(vault))

    # No ``kbs/Vault`` directory exists, yet it must not be pruned.
    assert "Vault" in manager.list_knowledge_bases()
    persisted = json.loads(manager.config_file.read_text(encoding="utf-8"))
    assert "Vault" in persisted.get("knowledge_bases", {})


def test_get_metadata_surfaces_type_and_vault_path(tmp_path: Path) -> None:
    vault = tmp_path / "my-vault"
    vault.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_obsidian(manager, "Vault", str(vault))

    meta = manager.get_metadata("Vault")
    assert meta["type"] == "obsidian"
    assert meta["vault_path"] == str(vault)


def test_reconcile_does_not_clobber_obsidian_entry(tmp_path: Path) -> None:
    vault = tmp_path / "my-vault"
    vault.mkdir()
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _seed_obsidian(manager, "Vault", str(vault))

    # Force a fresh load (the reconcile path) and confirm the pointer is intact.
    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = reloaded.config["knowledge_bases"]["Vault"]
    assert entry["type"] == "obsidian"
    assert entry["vault_path"] == str(vault)
    assert entry.get("rag_provider") == "pageindex"  # untouched
    assert entry.get("needs_reindex") is not True  # never flagged for reindex
    assert "index_versions" not in entry  # embedding reconcile skipped it


def test_ordinary_kb_metadata_has_no_vault_fields(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = manager.base_dir / "plain"
    (kb_dir / "version-1").mkdir(parents=True)
    (kb_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    manager.config.setdefault("knowledge_bases", {})["plain"] = {"path": "plain", "status": "ready"}
    manager._save_config()

    meta = manager.get_metadata("plain")
    assert "type" not in meta and "vault_path" not in meta
