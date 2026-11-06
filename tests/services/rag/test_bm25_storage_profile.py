"""Indexing must honor the configured vector-only retrieval profile."""

from pathlib import Path
from types import SimpleNamespace

from llama_index.core import Document
import pytest

from deeptutor.services.rag.pipelines.llamaindex import config, retrievers, storage
from deeptutor.services.rag.source_pages import SOURCE_SCHEMA_VERSION


@pytest.mark.parametrize("profile", ["vector", "hybrid"])
@pytest.mark.parametrize("operation", ["create", "insert"])
def test_storage_builds_bm25_only_for_hybrid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str, operation: str
) -> None:
    """Both rebuilds and incremental inserts skip BM25 for vector-only settings."""
    monkeypatch.setattr(config, "_load_runtime_settings", lambda: {"retrieval_profile": profile})
    calls: list[str] = []

    class BM25:
        @classmethod
        def from_defaults(cls, **kwargs):
            calls.append("build")
            return cls()

        def persist(self, path):
            calls.append("persist")
            (Path(path) / "index.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(retrievers, "_import_bm25_retriever", lambda: BM25)
    target = tmp_path / "new"

    def persist(*, persist_dir):
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        (Path(persist_dir) / "docstore.json").write_text("{}", encoding="utf-8")

    index = SimpleNamespace(storage_context=SimpleNamespace(persist=persist), insert_nodes=True)

    def create(documents, storage_dir, **kwargs):
        persist(persist_dir=storage_dir)
        return index, len(documents)

    monkeypatch.setattr(storage.ingestion, "create_index_from_documents", create)
    monkeypatch.setattr(storage.vector_store, "load_index", lambda path: index)
    monkeypatch.setattr(storage.ingestion, "insert_documents_into_index", lambda i, d: len(d))
    documents = [
        Document(
            text="A synthetic page",
            metadata={
                "source_schema_version": SOURCE_SCHEMA_VERSION,
                "page_index": 0,
                "document_key": "demo.pdf",
            },
        )
    ]
    if operation == "create":
        count = storage.create_index(documents, target)
    else:
        count = storage.insert_documents(tmp_path / "old", target, documents)

    assert count == 1
    assert (target / "docstore.json").is_file()
    assert (target / "source_pages.json").is_file()
    assert calls == (["build", "persist"] if profile == "hybrid" else [])
    assert (target / retrievers.BM25_PERSIST_DIRNAME).exists() == (profile == "hybrid")
