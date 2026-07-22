from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager


class _Signature:
    def __init__(self, sig_hash: str = "active-signature") -> None:
        self._hash = sig_hash

    def hash(self) -> str:
        return self._hash


def _patch_active_embedding(
    monkeypatch: pytest.MonkeyPatch, sig_hash: str = "active-signature"
) -> None:
    from deeptutor.knowledge import manager as manager_module
    from deeptutor.services.rag import embedding_signature

    monkeypatch.setattr(
        manager_module, "_get_embedding_fingerprint", lambda: ("embed-active", 4096)
    )
    monkeypatch.setattr(
        embedding_signature,
        "signature_from_embedding_config",
        lambda: _Signature(sig_hash),
    )


def test_in_progress_empty_version_dir_does_not_mark_new_kb_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_embedding(monkeypatch)

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(
        name="new-kb",
        status="processing",
        progress={
            "stage": "processing_documents",
            "message": "Embedding chunks",
            "percent": 20,
        },
    )

    # The LlamaIndex writer allocates version-N before it has persisted docstore.json.
    (tmp_path / "new-kb" / "version-1").mkdir(parents=True)

    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path))
    entry = reloaded.config["knowledge_bases"]["new-kb"]
    assert entry.get("needs_reindex", False) is False
    assert entry.get("embedding_mismatch", False) is False

    info = reloaded.get_info("new-kb")
    assert info["status"] == "processing"
    assert info["statistics"]["needs_reindex"] is False


def test_ready_version_without_active_signature_marks_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_embedding(monkeypatch, sig_hash="active-signature")

    kb_dir = tmp_path / "old-kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": "old-signature", "version": "version-1"}),
        encoding="utf-8",
    )

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.config.setdefault("knowledge_bases", {})["old-kb"] = {
        "path": "old-kb",
        "rag_provider": "llamaindex",
    }
    manager._save_config()

    reloaded = KnowledgeBaseManager(base_dir=str(tmp_path))
    entry = reloaded.config["knowledge_bases"]["old-kb"]
    assert entry["needs_reindex"] is True
    assert entry["embedding_mismatch"] is True


def test_ready_non_embedding_provider_version_does_not_mark_reindex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_embedding(monkeypatch, sig_hash="active-signature")

    kb_dir = tmp_path / "page-kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "pageindex_docs.json").write_text(
        json.dumps({"provider": "pageindex", "docs": {"a.pdf": {"doc_id": "doc-1"}}}),
        encoding="utf-8",
    )
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "provider": "pageindex",
                "signature": "pageindex",
                "version": "version-1",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "page-kb": {
                        "path": "page-kb",
                        "rag_provider": "pageindex",
                        "needs_reindex": True,
                        "embedding_mismatch": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    entry = manager.config["knowledge_bases"]["page-kb"]
    assert entry["rag_provider"] == "pageindex"
    assert entry.get("needs_reindex", False) is False
    assert entry.get("embedding_mismatch", False) is False
    assert entry["index_versions"][0]["signature"] == "pageindex"


def test_ready_status_records_last_indexed_only_when_index_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_embedding(monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))

    manager.update_kb_status(
        name="kb",
        status="ready",
        progress={
            "stage": "completed",
            "timestamp": "2026-05-04T10:00:00",
            "indexed_count": 2,
            "index_changed": True,
            "index_action": "upload",
        },
    )

    entry = KnowledgeBaseManager(base_dir=str(tmp_path)).config["knowledge_bases"]["kb"]
    assert entry["last_indexed_at"] == "2026-05-04T10:00:00"
    assert entry["last_indexed_count"] == 2
    assert entry["last_indexed_action"] == "upload"

    manager.update_kb_status(
        name="kb",
        status="ready",
        progress={
            "stage": "completed",
            "timestamp": "2026-05-04T11:00:00",
            "indexed_count": 0,
            "index_changed": False,
            "index_action": "upload",
        },
    )

    info = KnowledgeBaseManager(base_dir=str(tmp_path)).get_info("kb")
    assert info["metadata"]["last_indexed_at"] == "2026-05-04T10:00:00"
    assert info["metadata"]["last_indexed_count"] == 2
