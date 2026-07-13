"""Manager handling of LightRAG Server KBs (``type: lightrag_server`` pointers).

A LightRAG Server KB is a connection pointer to an external server: no on-disk
folder under ``base_dir``, no local index, and deleting it must only drop our
pointer (never touch the user's server). The stored API key must never leak into
surfaced metadata. Mirrors the linked/obsidian pointer guarantees.
"""

from __future__ import annotations

import pytest

from deeptutor.knowledge.kb_types import CONNECTED_KB_TYPES, LIGHTRAG_SERVER_KB_TYPE
from deeptutor.knowledge.manager import KnowledgeBaseManager


def test_lightrag_server_is_a_connected_type() -> None:
    assert LIGHTRAG_SERVER_KB_TYPE in CONNECTED_KB_TYPES


def test_register_writes_pointer(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    entry = manager.register_lightrag_server_kb(
        "Remote",
        "http://localhost:9621/",
        api_key="secret",
        search_mode="mix",
    )

    assert entry["type"] == LIGHTRAG_SERVER_KB_TYPE
    assert entry["rag_provider"] == "lightrag-server"
    assert entry["server_url"] == "http://localhost:9621"  # trailing slash trimmed
    assert entry["api_key"] == "secret"
    assert entry["search_mode"] == "mix"
    assert entry["status"] == "ready"
    assert entry["needs_reindex"] is False
    # No KB folder is created under base_dir.
    assert not (manager.base_dir / "Remote").exists()


def test_register_rejects_missing_url(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    with pytest.raises(ValueError):
        manager.register_lightrag_server_kb("X", "")


def test_register_rejects_name_clash(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_lightrag_server_kb("Dup", "http://x:9621")
    with pytest.raises(ValueError):
        manager.register_lightrag_server_kb("Dup", "http://y:9621")


def test_delete_drops_pointer(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_lightrag_server_kb("Remote", "http://x:9621")

    assert manager.delete_knowledge_base("Remote", confirm=True) is True
    assert "Remote" not in manager.list_knowledge_bases()


def test_entry_survives_orphan_prune(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_lightrag_server_kb("Remote", "http://x:9621")

    # No ``kbs/Remote`` directory exists, yet the pointer must not be pruned.
    assert "Remote" in manager.list_knowledge_bases()


def test_get_info_surfaces_url_but_hides_api_key(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_lightrag_server_kb("Remote", "http://x:9621", api_key="secret")

    info = manager.get_info("Remote")
    assert info["status"] == "ready"
    metadata = info["metadata"]
    assert metadata["type"] == LIGHTRAG_SERVER_KB_TYPE
    assert metadata["server_url"] == "http://x:9621"
    # The API key must never be surfaced anywhere in the metadata.
    assert "api_key" not in metadata
    assert "secret" not in str(metadata)


def test_get_metadata_hides_api_key(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_lightrag_server_kb("Remote", "http://x:9621", api_key="secret")

    meta = manager.get_metadata("Remote")
    assert meta["type"] == LIGHTRAG_SERVER_KB_TYPE
    assert meta["server_url"] == "http://x:9621"
    assert "api_key" not in meta
    assert "secret" not in str(meta)


def test_reconcile_skips_server_entry(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    manager.register_lightrag_server_kb("Remote", "http://x:9621")

    # A fresh load runs the reconcile path; the pointer stays intact and is
    # never flagged for reindex or given on-disk index versions.
    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = reloaded.config["knowledge_bases"]["Remote"]
    assert entry["type"] == LIGHTRAG_SERVER_KB_TYPE
    assert entry.get("needs_reindex") is not True
    assert "index_versions" not in entry
