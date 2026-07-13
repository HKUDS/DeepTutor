from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag.index_versioning import EmbeddingSignature


def _signature() -> EmbeddingSignature:
    return EmbeddingSignature(
        binding="openai",
        model="embed-a",
        dimension=1024,
        base_url="https://example.test/v1",
        api_version="",
    )


@pytest.mark.asyncio
async def test_incremental_add_migrates_matching_legacy_index_to_flat_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import storage as storage_module
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    sig = _signature()
    kb_dir = tmp_path / "kb"
    raw_file = kb_dir / "raw" / "new.txt"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("new content", encoding="utf-8")

    legacy_version_dir = kb_dir / "index_versions" / sig.hash()
    legacy_storage_dir = legacy_version_dir / "llamaindex_storage"
    legacy_storage_dir.mkdir(parents=True)
    (legacy_storage_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (legacy_version_dir / "meta.json").write_text(
        json.dumps({"signature": sig.hash(), "version": sig.hash()}),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class _FakeStorageContext:
        def persist(self, persist_dir: str) -> None:
            captured["persist_dir"] = persist_dir
            target = Path(persist_dir)
            target.mkdir(parents=True, exist_ok=True)
            (target / "docstore.json").write_text("{}", encoding="utf-8")

    class _FakeIndex:
        def __init__(self) -> None:
            self.storage_context = _FakeStorageContext()
            self.inserted = []

        def insert(self, document) -> None:
            self.inserted.append(document)

    def _fake_load_index(storage_dir) -> _FakeIndex:
        captured["load_dir"] = str(storage_dir)
        return _FakeIndex()

    async def _verify_embedding_connectivity(self) -> None:
        return None

    monkeypatch.setattr(
        LlamaIndexPipeline,
        "_configure_settings",
        lambda self: None,
    )
    monkeypatch.setattr(
        LlamaIndexPipeline,
        "_verify_embedding_connectivity",
        _verify_embedding_connectivity,
    )
    monkeypatch.setattr(storage_module.vector_store, "load_index", _fake_load_index)

    pipeline = LlamaIndexPipeline(
        kb_base_dir=str(tmp_path),
        signature_provider=lambda: sig,
    )

    assert await pipeline.add_documents("kb", [str(raw_file)]) is True

    flat_storage_dir = kb_dir / "version-1"
    assert captured["load_dir"] == str(legacy_storage_dir)
    assert captured["persist_dir"] == str(flat_storage_dir)
    assert (flat_storage_dir / "docstore.json").exists()
    assert json.loads((flat_storage_dir / "meta.json").read_text())["signature"] == sig.hash()


def test_hybrid_retriever_uses_official_query_fusion_when_bm25_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
    from deeptutor.services.rag.pipelines.llamaindex.config import RetrievalConfig

    captured: dict[str, object] = {}

    class _FakeVectorRetriever:
        def __init__(self, top_k: int) -> None:
            self.top_k = top_k

    class _FakeIndex:
        def as_retriever(self, similarity_top_k: int):
            captured["vector_top_k"] = similarity_top_k
            return _FakeVectorRetriever(similarity_top_k)

    class _FakeBM25:
        @classmethod
        def from_defaults(cls, index, similarity_top_k: int):
            captured["bm25_top_k"] = similarity_top_k
            return cls()

    class _FakeFusion:
        def __init__(self, retrievers, **kwargs):
            captured["retrievers"] = retrievers
            captured["kwargs"] = kwargs

    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _FakeBM25)
    monkeypatch.setattr(retriever_module, "QueryFusionRetriever", _FakeFusion)

    retriever = retriever_module.build_retriever(
        _FakeIndex(),
        tmp_path,
        top_k=4,
        config=RetrievalConfig(profile="hybrid"),
    )

    assert isinstance(retriever, _FakeFusion)
    assert captured["vector_top_k"] == 8
    assert captured["bm25_top_k"] == 8
    assert captured["kwargs"]["similarity_top_k"] == 4
    assert captured["kwargs"]["num_queries"] == 1


def test_hybrid_retriever_falls_back_to_vector_when_bm25_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
    from deeptutor.services.rag.pipelines.llamaindex.config import RetrievalConfig

    calls: list[int] = []

    class _FakeIndex:
        def as_retriever(self, similarity_top_k: int):
            calls.append(similarity_top_k)
            return {"top_k": similarity_top_k}

    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)

    retriever = retriever_module.build_retriever(
        _FakeIndex(),
        tmp_path,
        top_k=4,
        config=RetrievalConfig(profile="hybrid"),
    )

    assert retriever == {"top_k": 4}
    assert calls == [4]


def test_bm25_retriever_overrides_persisted_top_k(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module

    persist_dir = tmp_path / retriever_module.BM25_PERSIST_DIRNAME
    persist_dir.mkdir()

    class _FakeBM25:
        def __init__(self) -> None:
            self.similarity_top_k = 99

        @classmethod
        def from_persist_dir(cls, path: str):
            assert path == str(persist_dir)
            return cls()

    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _FakeBM25)

    retriever = retriever_module.build_bm25_retriever(object(), tmp_path, top_k=6)

    assert retriever.similarity_top_k == 6


def test_bm25_persistence_drops_stale_sidecar_on_rebuild_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module

    persist_dir = tmp_path / retriever_module.BM25_PERSIST_DIRNAME
    persist_dir.mkdir()
    (persist_dir / "old.json").write_text("stale", encoding="utf-8")

    class _FailingBM25:
        @classmethod
        def from_defaults(cls, index, similarity_top_k: int):
            raise RuntimeError("boom")

    monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: _FailingBM25)

    assert retriever_module.persist_bm25_retriever(object(), tmp_path, top_k=6) is False
    assert not persist_dir.exists()


def test_retrieval_config_reads_profile_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import config as config_module

    monkeypatch.setenv("DEEPTUTOR_RAG_RETRIEVAL_PROFILE", " vector ")

    config = config_module.retrieval_config_from_env()

    assert config.profile == config_module.VECTOR_PROFILE
