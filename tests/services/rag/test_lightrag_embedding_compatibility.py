"""Published vector identity and operation-local embedding consistency."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager, _reconcile_embedding_flags
from deeptutor.services.embedding.config import EmbeddingConfig
from deeptutor.services.rag.embedding_signature import signature_from_config
from deeptutor.services.rag.pipelines.lightrag import config, engine, indexing_policy, storage
from deeptutor.services.rag.pipelines.lightrag import pipeline as pipeline_module
from deeptutor.services.rag.pipelines.lightrag.pipeline import BatchOutcome, LightRagPipeline


@pytest.fixture
def embedding(monkeypatch: pytest.MonkeyPatch) -> EmbeddingConfig:
    cfg = EmbeddingConfig(
        model="embed-original", dim=3, base_url="https://embedding.test/v1", api_key="test-key"
    )
    monkeypatch.setattr("deeptutor.services.embedding.get_embedding_config", lambda: cfg)
    monkeypatch.setattr(engine, "installed_version", lambda: "1.5.7rc2")
    return cfg


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        vision_available=False,
        persisted_policy=lambda: {"policy": "pinned", "fingerprint": "a" * 64},
    )


def _published(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "kv_store_doc_status.json").write_text(
        json.dumps({"doc": {"status": "processed"}}), encoding="utf-8"
    )
    storage.write_meta(root, indexing_policy=_snapshot().persisted_policy())


def _pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LightRagPipeline:
    pipeline = LightRagPipeline(str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)
    monkeypatch.setattr(pipeline, "_resolve_mode", lambda *_args: "hybrid")
    monkeypatch.setattr(pipeline_module, "resolve_write_snapshot", lambda *_a, **_k: _snapshot())
    monkeypatch.setattr(pipeline, "_clear_pending_policy", lambda *_args: None)
    return pipeline


@pytest.mark.parametrize(
    "field,value",
    [("model", "embed-other"), ("dim", 4), ("base_url", "https://other.test/v1")],
)
def test_changed_identity_blocks_query_and_append_before_vectors_open(
    embedding: EmbeddingConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    root = tmp_path / "kb" / "version-1"
    _published(root)
    before = (root / "meta.json").read_bytes()
    setattr(embedding, field, value)
    pipeline = _pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(engine, "build_rag", lambda *_a, **_k: pytest.fail("opened vectors"))

    result = asyncio.run(pipeline.search("question", "kb"))
    assert result["sources"] == []
    assert result["error_type"] == "lightrag_embedding_incompatible"
    assert "Restore the original" in result["answer"]
    with pytest.raises(indexing_policy.IndexingPolicyError, match="Restore the original"):
        asyncio.run(pipeline.add_documents("kb", ["new.md"]))
    assert (root / "meta.json").read_bytes() == before


def test_missing_identity_requires_rebuild(
    embedding: EmbeddingConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "kb" / "version-1"
    _published(root)
    meta_path = root / "meta.json"
    meta = json.loads(meta_path.read_text())
    del meta["embedding_signature"]
    meta_path.write_text(json.dumps(meta))
    entries = {"kb": {"rag_provider": "lightrag", "status": "ready"}}
    assert _reconcile_embedding_flags(entries, tmp_path)
    assert entries["kb"]["embedding_mismatch"] is True
    pipeline = _pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(engine, "build_rag", lambda *_a, **_k: pytest.fail("opened vectors"))
    assert asyncio.run(pipeline.search("question", "kb"))["error_type"] == (
        "lightrag_embedding_incompatible"
    )
    with pytest.raises(indexing_policy.IndexingPolicyError):
        asyncio.run(pipeline.add_documents("kb", ["new.md"]))


def test_restoring_identity_recovers_query_and_incremental_append(
    embedding: EmbeddingConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "kb" / "version-1"
    _published(root)
    index_before = (root / "kv_store_doc_status.json").read_bytes()
    original = embedding.model
    embedding.model = "other"
    entries = {"kb": {"rag_provider": "lightrag", "status": "ready"}}
    assert _reconcile_embedding_flags(entries, tmp_path)
    embedding.model = original
    assert _reconcile_embedding_flags(entries, tmp_path)
    assert not entries["kb"].get("embedding_mismatch")
    assert entries["kb"]["needs_reindex"] is False
    assert (root / "kv_store_doc_status.json").read_bytes() == index_before

    pipeline = _pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(engine, "build_rag", lambda *_a, **_k: object())

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    async def query(*_a: Any, **_k: Any) -> tuple[str, list]:
        return "retrieved", []

    roots = []

    async def append(path: Path, *_a: Any, **_k: Any) -> BatchOutcome:
        roots.append(path)
        return BatchOutcome(requested=1, accepted=1, processed=("new.md",))

    monkeypatch.setattr(engine, "initialize", noop)
    monkeypatch.setattr(engine, "finalize", noop)
    monkeypatch.setattr(engine, "query_with_sources", query)
    monkeypatch.setattr(pipeline, "_run_indexing", append)
    assert asyncio.run(pipeline.search("question", "kb"))["answer"] == "retrieved"
    assert asyncio.run(pipeline.add_documents("kb", ["new.md"]))
    assert roots == [root]
    assert not (root.parent / "version-2").exists()


@pytest.mark.parametrize("operation", ["initialize", "add_documents"])
def test_index_operation_metadata_uses_captured_embedding_after_default_change(
    embedding: EmbeddingConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
) -> None:
    original = deepcopy(embedding)
    if operation == "add_documents":
        _published(tmp_path / "kb" / "version-1")
    pipeline = _pipeline(tmp_path, monkeypatch)
    captured = []

    async def index(root: Path, *_a: Any, embedding_config: EmbeddingConfig) -> BatchOutcome:
        captured.append(embedding_config)
        embedding.model = "later-default"
        assert embedding_config.model == original.model
        root.mkdir(parents=True, exist_ok=True)
        (root / "kv_store_doc_status.json").write_text('{"doc":{"status":"processed"}}')
        return BatchOutcome(requested=1, accepted=1, processed=("doc.md",))

    monkeypatch.setattr(pipeline, "_run_indexing", index)
    kwargs = {"indexing_snapshot": _snapshot()} if operation == "initialize" else {}
    assert asyncio.run(getattr(pipeline, operation)("kb", ["doc.md"], **kwargs))
    root = storage.latest_published_root(tmp_path / "kb")
    assert root is not None
    meta = json.loads((root / "meta.json").read_text())
    assert len(captured) == 1
    assert meta["embedding_signature"] == signature_from_config(original).hash()
    assert meta["embedding_model"] == original.model
    assert meta["embedding_dim"] == original.dim
    assert "test-key" not in json.dumps(meta)


def test_query_keeps_captured_embedding_while_worker_waits(
    embedding: EmbeddingConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _published(tmp_path / "kb" / "version-1")
    original = embedding.model
    pipeline = _pipeline(tmp_path, monkeypatch)
    captured = []

    async def worker(job: Any) -> Any:
        embedding.model = "later-default"
        return await job(None)

    def build(*_a: Any, embedding_config: EmbeddingConfig, **_k: Any) -> object:
        captured.append(embedding_config.model)
        return object()

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    async def query(*_a: Any, **_k: Any) -> tuple[str, list]:
        return "retrieved", []

    monkeypatch.setattr(pipeline_module, "run_in_worker_loop", worker)
    monkeypatch.setattr(engine, "build_rag", build)
    monkeypatch.setattr(engine, "initialize", noop)
    monkeypatch.setattr(engine, "finalize", noop)
    monkeypatch.setattr(engine, "query_with_sources", query)
    assert asyncio.run(pipeline.search("question", "kb"))["answer"] == "retrieved"
    assert captured == [original]


@pytest.mark.skipif(importlib.util.find_spec("lightrag") is None, reason="optional LightRAG SDK")
def test_adapter_calls_captured_config_and_preserves_query_role(
    embedding: EmbeddingConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = deepcopy(embedding)
    embedding.model = "later-default"
    calls = []

    class Client:
        def __init__(self, *, config: EmbeddingConfig) -> None:
            self.config = config

        async def embed(self, texts: list[str], *, input_type: str | None) -> list[list[float]]:
            calls.append((self.config.model, texts, input_type))
            return [[1.0, 2.0, 3.0]]

    monkeypatch.setattr("deeptutor.services.embedding.client.EmbeddingClient", Client)
    adapter = config.build_embedding_func(embedding_config=original)
    original.model = "mutated-input"
    asyncio.run(adapter(["question"], context="query"))
    assert calls == [("embed-original", ["question"], "search_query")]
    assert adapter.embedding_dim == 3


def test_manager_surfaces_old_current_identity_and_ignores_llm_default(
    embedding: EmbeddingConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "kb" / "version-1"
    _published(root)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.config["knowledge_bases"]["kb"] = {"rag_provider": "lightrag", "status": "ready"}
    monkeypatch.setattr(
        "deeptutor.services.config.load_lightrag_settings",
        lambda: {"llm_profile_id": "different", "llm_model_id": "different"},
    )
    assert not _reconcile_embedding_flags(manager.config["knowledge_bases"], tmp_path)
    embedding.model = "current-model"
    assert _reconcile_embedding_flags(manager.config["knowledge_bases"], tmp_path)
    info = manager.get_info("kb")
    assert info["metadata"]["indexed_embedding_model"] == "embed-original"
    assert info["metadata"]["current_embedding_model"] == "current-model"
    assert info["metadata"]["indexed_embedding_dim"] == 3
    assert info["metadata"]["current_embedding_dim"] == 3
