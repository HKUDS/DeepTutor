from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from pathlib import Path

import pytest

from deeptutor.knowledge.add_documents import (
    DocumentAdder,
    RawDocumentRemoval,
    add_documents,
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
    elif provider == "lightrag":
        (version_dir / "kv_store_doc_status.json").write_text(
            json.dumps({"doc": {"status": "processed", "chunks_list": ["chunk"]}}),
            encoding="utf-8",
        )
    else:
        (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
        (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    meta = {"provider": provider, "signature": provider, "version": "version-1"}
    if provider == "lightrag":
        meta.update(
            {
                "lightrag_adapter_schema": 2,
                "parser_bridge_schema": 1,
                "state": "published",
            }
        )
    (version_dir / "meta.json").write_text(
        json.dumps(meta),
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


@pytest.mark.parametrize("provider", ["llamaindex", "lightrag"])
def test_document_adder_allows_empty_kb_to_bootstrap(monkeypatch, tmp_path: Path, provider) -> None:
    from deeptutor.services import config
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.rag.pipelines.lightrag import roles

    monkeypatch.setattr(
        config,
        "load_lightrag_settings",
        lambda: {
            "version": 2,
            "role_models": {"base": {"profile_id": "fixture", "model_id": "fixture"}},
        },
    )
    monkeypatch.setattr(
        roles,
        "resolve_selection",
        lambda *_args, **_kwargs: LLMConfig(
            model="fixture", binding="openai", api_key="offline-fixture"
        ),
    )
    from deeptutor.services.embedding.config import EmbeddingConfig

    monkeypatch.setattr(
        "deeptutor.services.embedding.get_embedding_config",
        lambda: EmbeddingConfig(
            model="embed-fixture", api_key="fake", dim=3, base_url="https://embed.test"
        ),
    )
    (tmp_path / "empty-kb").mkdir()

    adder = DocumentAdder(
        kb_name="empty-kb",
        base_dir=str(tmp_path),
        rag_provider=provider,
    )

    assert adder.rag_provider == provider
    assert adder.raw_dir.is_dir()
    if provider == "lightrag":
        assert adder.accepted_indexing_snapshot.extract.config.model == "fixture"
        assert adder.accepted_indexing_snapshot.vlm is None


def test_document_adder_rejects_unready_existing_version(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    version_dir = kb_dir / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reindex required"):
        DocumentAdder(kb_name="kb", base_dir=str(tmp_path), rag_provider="llamaindex")


def test_document_adder_rejects_legacy_rag_storage(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    (kb_dir / "rag_storage").mkdir(parents=True)

    with pytest.raises(ValueError, match="legacy index format"):
        DocumentAdder(kb_name="kb", base_dir=str(tmp_path), rag_provider="llamaindex")


def test_document_adder_allows_empty_llamaindex_kb_to_bootstrap(tmp_path: Path) -> None:
    """Create-then-upload (no files at create time) must not look uninitialized."""
    (tmp_path / "Medicine").mkdir()

    adder = DocumentAdder(
        kb_name="Medicine",
        base_dir=str(tmp_path),
        rag_provider="llamaindex",
    )

    assert adder.rag_provider == "llamaindex"
    assert adder.raw_dir.is_dir()


@pytest.mark.parametrize("provider", ["graphrag", "pageindex", "pageindex-oss"])
def test_empty_provider_kb_bootstraps_on_first_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    kb_dir = tmp_path / "empty"
    (kb_dir / "raw").mkdir(parents=True)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.register_knowledge_base("empty")
    manager.config["knowledge_bases"]["empty"]["rag_provider"] = provider
    manager._save_config()
    manager.update_kb_status(name="empty", status="ready")
    assert manager.get_info("empty")["status"] == "ready"

    doc = tmp_path / "lesson.md"
    doc.write_text("Lesson", encoding="utf-8")
    initialized: list[tuple[str, list[str]]] = []

    class FakeRagService:
        def __init__(self, *, kb_base_dir: str) -> None:
            assert kb_base_dir == str(tmp_path)

        async def initialize(
            self,
            *,
            kb_name: str,
            file_paths: list[str],
            indexed_file_callback: Callable[[list[str]], None],
        ) -> bool:
            initialized.append((kb_name, file_paths))
            indexed_file_callback(file_paths)
            return True

        def _resolve_provider(self, _kb_name: str) -> str:
            return provider

    monkeypatch.setattr("deeptutor.knowledge.add_documents.RAGService", FakeRagService)

    assert asyncio.run(add_documents("empty", [str(doc)], base_dir=str(tmp_path))) == 1
    assert initialized == [("empty", [str(doc)])]
    assert KnowledgeBaseManager(base_dir=str(tmp_path)).get_info("empty")["status"] == "ready"


def test_document_adder_unready_index_reports_probe_summary(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    (kb_dir / "raw").mkdir(parents=True)
    version = kb_dir / "version-1"
    version.mkdir()
    (version / "meta.json").write_text(
        '{"provider": "llamaindex", "signature": "sig", "version": "version-1"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no ready llamaindex index") as caught:
        DocumentAdder(kb_name="kb", base_dir=str(tmp_path), rag_provider="llamaindex")

    assert "not initialized" not in str(caught.value)
    assert "docstore.json" in str(caught.value)


def test_document_adder_unwritable_kb_is_not_reported_as_uninitialized(
    tmp_path: Path, monkeypatch
) -> None:
    kb_dir = tmp_path / "Medicine"
    kb_dir.mkdir()
    monkeypatch.setattr(
        "deeptutor.knowledge.add_documents.ensure_data_volume_writable",
        lambda _path: (_ for _ in ()).throw(
            PermissionError(
                "Data directory is not writable by the running process "
                "(euid=1000, egid=1000): /app/data/knowledge_bases/Medicine "
                "is uid=99 gid=100 mode=0755."
            )
        ),
    )

    with pytest.raises(PermissionError, match="not writable") as caught:
        DocumentAdder(kb_name="Medicine", base_dir=str(tmp_path), rag_provider="llamaindex")

    assert "not initialized" not in str(caught.value)


def test_empty_kb_bootstrap_hashes_only_files_confirmed_by_index(
    monkeypatch, tmp_path: Path
) -> None:
    from deeptutor.knowledge import add_documents as add_module

    raw_dir = tmp_path / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    indexed = raw_dir / "indexed.txt"
    skipped = raw_dir / "skipped.txt"
    indexed.write_text("searchable", encoding="utf-8")
    skipped.write_text("", encoding="utf-8")

    class PartialIndexService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self, *_args, **kwargs) -> bool:
            kwargs["indexed_file_callback"]([str(indexed)])
            return True

        def _resolve_provider(self, _name: str) -> str:
            return "llamaindex"

    statuses: list[dict] = []
    manager = type(
        "Manager", (), {"update_kb_status": lambda _self, **kwargs: statuses.append(kwargs)}
    )()
    monkeypatch.setattr(add_module, "RAGService", PartialIndexService)

    count = asyncio.run(
        add_module._bootstrap_index_from_files(
            "kb", [str(indexed), str(skipped)], str(tmp_path), manager
        )
    )

    metadata = json.loads((tmp_path / "kb" / "metadata.json").read_text(encoding="utf-8"))
    assert count == 1
    assert set(metadata["file_hashes"]) == {"indexed.txt"}
    assert metadata["last_indexed_count"] == 1
    assert statuses[-1]["progress"]["indexed_count"] == 1


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


def test_lightrag_hash_bookkeeping_failure_does_not_deny_published_success(
    monkeypatch, tmp_path: Path
) -> None:
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_provider_version(kb_dir, "lightrag")
    doc = raw_dir / "published.txt"
    doc.write_text("hello", encoding="utf-8")

    class _SuccessfulRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr("deeptutor.knowledge.add_documents.RAGService", _SuccessfulRagService)
    adder = DocumentAdder(
        kb_name="kb",
        base_dir=str(tmp_path),
        rag_provider="lightrag",
        accepted_indexing_snapshot=object(),
    )
    monkeypatch.setattr(
        adder,
        "_record_successful_hash",
        lambda _path: (_ for _ in ()).throw(OSError("metadata unavailable")),
    )

    result = asyncio.run(adder.process_new_documents([doc]))

    assert result.processed_files == [doc]
    assert result.failures == []


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


@pytest.mark.parametrize("storage", ["version-1", "rag_storage"])
def test_empty_bootstrap_does_not_replace_broken_existing_index(tmp_path, storage):
    kb_dir = tmp_path / "kb"
    (kb_dir / storage).mkdir(parents=True)
    with pytest.raises(ValueError, match="reindex|not initialized"):
        DocumentAdder(kb_name="kb", base_dir=str(tmp_path), rag_provider="llamaindex")
