"""Manager handling of Tencent IMA KBs (``type: ima`` pointers).

An IMA KB is a connection pointer to a library the user keeps in IMA: no on-disk
folder under ``base_dir``, no local index, and deleting it must only drop our
pointer (never touch the user's IMA library). The stored credentials must never
leak into surfaced metadata. Mirrors the LightRAG-server pointer guarantees.
"""

from __future__ import annotations

import pytest

from deeptutor.knowledge.kb_types import CONNECTED_KB_TYPES, IMA_KB_TYPE
from deeptutor.knowledge.manager import KnowledgeBaseManager


def _register(manager: KnowledgeBaseManager, name: str = "IMA") -> dict:
    return manager.register_ima_kb(name, "cid", "secret", "kb-1")


def test_ima_is_a_connected_type() -> None:
    assert IMA_KB_TYPE in CONNECTED_KB_TYPES


def test_register_writes_pointer(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    entry = manager.register_ima_kb("IMA", " cid ", " secret ", " kb-1 ")

    assert entry["type"] == IMA_KB_TYPE
    assert entry["rag_provider"] == "ima"
    assert entry["client_id"] == "cid"  # trimmed
    assert entry["api_key"] == "secret"
    assert entry["knowledge_base_id"] == "kb-1"
    assert entry["status"] == "ready"
    assert entry["needs_reindex"] is False
    # No KB folder is created under base_dir.
    assert not (manager.base_dir / "IMA").exists()


def test_register_keeps_the_probed_description(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    entry = manager.register_ima_kb("IMA", "cid", "secret", "kb-1", description="My notes")

    assert entry["description"] == "My notes"


def test_register_without_credentials_defers_to_the_account_pair(tmp_path) -> None:
    # Omitting both halves means "use the engine's account credentials"; storing
    # a copy would pin the KB to today's key and break the next rotation.
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    entry = manager.register_ima_kb("IMA", "", "", "kb-1")

    assert entry["knowledge_base_id"] == "kb-1"
    assert "client_id" not in entry
    assert "api_key" not in entry


@pytest.mark.parametrize(
    "args",
    [
        ("", "cid", "secret", "kb-1"),
        # Half a credential pair is a mistake, not an account-level fallback.
        ("IMA", "", "secret", "kb-1"),
        ("IMA", "cid", "", "kb-1"),
        ("IMA", "cid", "secret", ""),
    ],
)
def test_register_rejects_missing_fields(tmp_path, args) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    with pytest.raises(ValueError):
        manager.register_ima_kb(*args)


def test_register_rejects_duplicate_name(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _register(manager)
    with pytest.raises(ValueError, match="already exists"):
        _register(manager)


def test_get_metadata_hides_credentials(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _register(manager)

    meta = manager.get_metadata("IMA")

    assert meta["type"] == IMA_KB_TYPE
    assert meta["knowledge_base_id"] == "kb-1"
    assert "api_key" not in meta
    assert "client_id" not in meta


def test_get_info_hides_credentials(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _register(manager)

    metadata = manager.get_info("IMA")["metadata"]

    assert metadata["knowledge_base_id"] == "kb-1"
    assert "api_key" not in metadata
    assert "client_id" not in metadata


def test_delete_only_drops_the_pointer(tmp_path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    _register(manager)

    assert manager.delete_knowledge_base("IMA", confirm=True) is True
    assert "IMA" not in manager.list_knowledge_bases()


def test_has_no_local_document_root(tmp_path) -> None:
    # Nothing of an IMA KB lives on this machine, so there is no folder to walk.
    from deeptutor.knowledge.manifest import document_root

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = _register(manager)

    assert document_root(manager.base_dir / "IMA", entry) is None


def test_documents_are_reported_as_non_enumerable(tmp_path) -> None:
    # IMA holds the documents behind its API; reporting "0 documents" would lie.
    from deeptutor.knowledge.manifest import UNAVAILABLE_REMOTE, build_manifest

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    entry = _register(manager)

    manifest = build_manifest(name="IMA", kb_dir=manager.base_dir / "IMA", entry=entry)

    assert manifest.unavailable == UNAVAILABLE_REMOTE
    assert manifest.total == 0
