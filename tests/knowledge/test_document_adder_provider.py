from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from deeptutor.knowledge.add_documents import (
    DocumentAdder,
    RawDocumentRemoval,
    remove_raw_document,
)


def _write_provider_version(kb_dir: Path, provider: str) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    if provider == "pageindex":
        (version_dir / "pageindex_docs.json").write_text(
            json.dumps({"provider": "pageindex", "docs": {"doc.pdf": {"doc_id": "doc-1"}}}),
            encoding="utf-8",
        )
    elif provider == "graphrag":
        output_dir = version_dir / "output"
        output_dir.mkdir()
        (output_dir / "entities.parquet").write_bytes(b"placeholder")
    else:
        (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
        (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "signature": provider,
                "version": "version-1",
            }
        ),
        encoding="utf-8",
    )


def test_document_adder_reads_provider_from_kb_config_when_metadata_missing(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "page-kb"
    (kb_dir / "raw").mkdir(parents=True)
    _write_provider_version(kb_dir, "pageindex")
    (tmp_path / "kb_config.json").write_text(
        json.dumps(
            {"knowledge_bases": {"page-kb": {"path": "page-kb", "rag_provider": "pageindex"}}}
        ),
        encoding="utf-8",
    )

    adder = DocumentAdder(kb_name="page-kb", base_dir=str(tmp_path))

    assert adder.rag_provider == "pageindex"


def test_document_adder_preserves_explicit_bound_provider(tmp_path: Path) -> None:
    kb_dir = tmp_path / "graph-kb"
    (kb_dir / "raw").mkdir(parents=True)
    _write_provider_version(kb_dir, "graphrag")

    adder = DocumentAdder(
        kb_name="graph-kb",
        base_dir=str(tmp_path),
        rag_provider="graphrag",
    )

    assert adder.rag_provider == "graphrag"


def test_process_new_documents_returns_failures_without_marking_processed(
    monkeypatch, tmp_path: Path
) -> None:
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_provider_version(kb_dir, "llamaindex")
    doc = raw_dir / "bad.txt"
    doc.write_text("hello", encoding="utf-8")

    class _FailingRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            raise RuntimeError("provider exploded")

    monkeypatch.setattr(
        "deeptutor.knowledge.add_documents.RAGService",
        _FailingRagService,
    )

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    result = asyncio.run(adder.process_new_documents([doc]))

    assert result.processed_files == []
    assert result.failed_count == 1
    assert "provider exploded" in result.failure_summary()
    assert adder.get_ingested_hashes() == {}


def test_remove_raw_document_deletes_file_and_hash_without_index(
    tmp_path: Path,
) -> None:
    # Deliberately NO provider index: an error-state KB may have none, yet its
    # raw files must stay removable (DocumentAdder would refuse to construct).
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    doc = raw_dir / "big.pdf"
    doc.write_text("x", encoding="utf-8")
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {"big.pdf": "deadbeef"}, "keep": True}),
        encoding="utf-8",
    )

    removal = remove_raw_document(kb_dir, doc)

    assert removal == RawDocumentRemoval(rel_path="big.pdf", was_indexed=True)
    assert not doc.exists()
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"] == {}
    assert metadata["keep"] is True  # unrelated metadata is preserved


def test_remove_raw_document_reports_unindexed_file(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    doc = raw_dir / "never_indexed.pdf"
    doc.write_text("x", encoding="utf-8")
    # No metadata.json at all — the file failed before any hash was recorded.

    removal = remove_raw_document(kb_dir, doc)

    assert removal.rel_path == "never_indexed.pdf"
    assert removal.was_indexed is False
    assert not doc.exists()


def test_remove_raw_document_uses_relative_key_for_nested_file(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    nested = kb_dir / "raw" / "papers" / "2024"
    nested.mkdir(parents=True)
    doc = nested / "a.pdf"
    doc.write_text("x", encoding="utf-8")
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {"papers/2024/a.pdf": "hash", "other.pdf": "keep"}}),
        encoding="utf-8",
    )

    removal = remove_raw_document(kb_dir, doc)

    assert removal.was_indexed is True
    assert removal.rel_path == "papers/2024/a.pdf"
    remaining = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert remaining["file_hashes"] == {"other.pdf": "keep"}


def test_cli_add_documents_fails_closed_on_final_checkpoint_ownership_loss(
    monkeypatch, tmp_path: Path
) -> None:
    """A stale CLI writer whose lease is taken over before the final metadata /
    status writes must stop instead of marking the KB ready."""
    from deeptutor.knowledge.add_documents import add_documents as cli_add_documents
    from deeptutor.knowledge.write_coordinator import (
        KbOwnershipLostError,
        KbWriteCoordinator,
        KbWriteOperation,
    )

    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_provider_version(kb_dir, "llamaindex")
    (kb_dir / "metadata.json").write_text(json.dumps({"file_hashes": {}}), encoding="utf-8")
    (tmp_path / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "ok.txt"
    source.write_text("ok", encoding="utf-8")

    class _OkRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr("deeptutor.knowledge.add_documents.RAGService", _OkRagService)

    coordinator = KbWriteCoordinator(base_dir=str(tmp_path))
    real_update_metadata = DocumentAdder.update_metadata

    def _takeover_update_metadata(self, added_count: int) -> None:
        # A newer holder replaced the operation right before the CLI's final
        # completion writes.
        new_op = KbWriteOperation.from_dict(
            {
                "id": "new-holder-op",
                "kb_name": "kb",
                "operation_type": "reindex",
                "status": "running",
                "lease_owner": "holder-b",
                "lease_expires_at": "2099-01-01T00:00:00Z",
                "created_at": "2026-08-04T12:00:00Z",
                "updated_at": "2026-08-04T12:00:00Z",
            }
        )
        coordinator._save({"kb": new_op})
        real_update_metadata(self, added_count)

    monkeypatch.setattr(DocumentAdder, "update_metadata", _takeover_update_metadata)

    with pytest.raises(KbOwnershipLostError):
        asyncio.run(
            cli_add_documents(
                kb_name="kb",
                source_files=[str(source)],
                base_dir=str(tmp_path),
            )
        )

    # The stale CLI writer did not mark the KB ready, and it did not close its
    # own operation as succeeded — the new holder's op is preserved.
    config = json.loads((tmp_path / "kb_config.json").read_text(encoding="utf-8"))
    assert config["knowledge_bases"]["kb"]["status"] != "ready"
    current = coordinator.current_operation("kb")
    assert current.id == "new-holder-op"
    assert current.status == "running"
