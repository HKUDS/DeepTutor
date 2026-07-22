"""RAGService end-to-end behavior tests (with a fake pipeline)."""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any, Dict

import pytest

import deeptutor.services.rag.service as rag_service_module
from deeptutor.services.rag.service import RAGService
from deeptutor.services.rag.smart_retriever import SmartRetriever


class _FakePipeline:
    """Minimal pipeline stub that records calls and returns canned results."""

    def __init__(self, search_result: Dict[str, Any] | None = None) -> None:
        self.calls: list[dict] = []
        self.search_result = search_result or {
            "answer": "fake answer",
            "sources": [{"id": 1}],
            "provider": "lightrag",  # deliberately wrong; service must overwrite
        }

    async def initialize(self, kb_name: str, file_paths, **kwargs) -> bool:
        self.calls.append({"op": "initialize", "kb_name": kb_name, "files": list(file_paths)})
        return True

    async def add_documents(self, kb_name: str, file_paths, **kwargs) -> bool:
        self.calls.append({"op": "add_documents", "kb_name": kb_name, "files": list(file_paths)})
        return True

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        self.calls.append({"op": "search", "query": query, "kb_name": kb_name, "kwargs": kwargs})
        return dict(self.search_result)

    async def delete(self, kb_name: str) -> bool:
        self.calls.append({"op": "delete", "kb_name": kb_name})
        return True


@pytest.fixture
def fake_service(tmp_path) -> tuple[RAGService, _FakePipeline]:
    pipeline = _FakePipeline()
    service = RAGService(kb_base_dir=str(tmp_path))
    # No metadata.json under tmp_path → KBs resolve to the default provider.
    service._pipelines["llamaindex"] = pipeline  # type: ignore[attr-defined]
    return service, pipeline


def test_provider_argument_honored_for_known_provider(tmp_path) -> None:
    """An explicit known provider wins (used at create time); unknown/legacy
    strings collapse to the default engine."""
    assert RAGService(kb_base_dir=str(tmp_path), provider="lightrag").provider == "lightrag"
    assert RAGService(kb_base_dir=str(tmp_path), provider="raganything").provider == "llamaindex"


@pytest.mark.asyncio
async def test_search_force_overwrites_provider_in_result(fake_service) -> None:
    """Even if the underlying pipeline lies about its provider, RAGService normalizes."""
    service, pipeline = fake_service
    pipeline.search_result = {"answer": "x", "provider": "raganything"}

    result = await service.search(query="hello", kb_name="kb")
    assert result["provider"] == "llamaindex"


@pytest.mark.asyncio
async def test_search_forwards_mode_kwarg_to_pipeline(fake_service) -> None:
    """Mode-aware engines must receive explicit retrieval mode overrides."""
    service, pipeline = fake_service
    await service.search(query="hi", kb_name="kb", mode="hybrid", top_k=5)

    last = pipeline.calls[-1]
    assert last["op"] == "search"
    assert last["kwargs"].get("mode") == "hybrid"
    assert last["kwargs"].get("top_k") == 5


def test_ragservice_routes_provider_from_kb_config_when_metadata_missing(tmp_path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (tmp_path / "kb_config.json").write_text(
        '{"knowledge_bases": {"kb": {"rag_provider": "lightrag"}}}',
        encoding="utf-8",
    )

    service = RAGService(kb_base_dir=str(tmp_path))

    assert service._resolve_provider("kb") == "lightrag"


def test_ragservice_prefers_authoritative_config_over_stale_metadata(tmp_path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "metadata.json").write_text('{"rag_provider": "llamaindex"}', encoding="utf-8")
    (tmp_path / "kb_config.json").write_text(
        '{"knowledge_bases": {"kb": {"rag_provider": "lightrag"}}}',
        encoding="utf-8",
    )

    service = RAGService(kb_base_dir=str(tmp_path))

    assert service._resolve_provider("kb") == "lightrag"


@pytest.mark.asyncio
async def test_search_aliases_answer_and_content(fake_service) -> None:
    """Pipelines that only return ``content`` should still expose ``answer`` and vice versa."""
    service, pipeline = fake_service

    pipeline.search_result = {"content": "only-content", "provider": "x"}
    result = await service.search(query="q", kb_name="kb")
    assert result["answer"] == "only-content"
    assert result["content"] == "only-content"
    assert result["query"] == "q"

    pipeline.search_result = {"answer": "only-answer", "provider": "x"}
    result = await service.search(query="q2", kb_name="kb")
    assert result["content"] == "only-answer"
    assert result["answer"] == "only-answer"


@pytest.mark.asyncio
async def test_search_forwards_lightrag_native_logs_to_event_sink(
    fake_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, pipeline = fake_service
    lightrag_logger = logging.getLogger("lightrag")
    original_handlers = list(lightrag_logger.handlers)
    original_propagate = lightrag_logger.propagate
    original_level = lightrag_logger.level
    events: list[tuple[str, str, dict]] = []

    async def event_sink(event_type: str, message: str, metadata: dict) -> None:
        events.append((event_type, message, metadata))

    async def search_with_native_log(query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        lightrag_logger.info("Final context: 14 entities, 13 relations, 1 chunks")
        lightrag_logger.warning("Rerank is enabled but no rerank model is configured.")
        return {"answer": "ok", "provider": "lightrag"}

    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "lightrag.utils":
            lightrag_logger.propagate = False
            return object()
        return original_import_module(name, package)

    monkeypatch.setattr(pipeline, "search", search_with_native_log)
    monkeypatch.setattr(rag_service_module.importlib, "import_module", fake_import_module)

    try:
        lightrag_logger.handlers = []
        lightrag_logger.propagate = True
        lightrag_logger.setLevel(logging.INFO)

        await service.search(query="hello", kb_name="kb", event_sink=event_sink)
        await asyncio.sleep(0)
    finally:
        lightrag_logger.handlers = original_handlers
        lightrag_logger.propagate = original_propagate
        lightrag_logger.setLevel(original_level)

    raw_logs = [
        (message, metadata) for event_type, message, metadata in events if event_type == "raw_log"
    ]
    assert any(
        message == "Final context: 14 entities, 13 relations, 1 chunks"
        and metadata.get("logger") == "lightrag"
        and metadata.get("level") == "INFO"
        for message, metadata in raw_logs
    )
    assert any(
        message == "Rerank is enabled but no rerank model is configured."
        and metadata.get("logger") == "lightrag"
        and metadata.get("level") == "WARNING"
        for message, metadata in raw_logs
    )


@pytest.mark.asyncio
async def test_search_forwards_graphrag_native_logs_to_event_sink(
    fake_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, pipeline = fake_service
    graphrag_logger = logging.getLogger("graphrag.api.query")
    original_handlers = list(graphrag_logger.handlers)
    original_propagate = graphrag_logger.propagate
    original_level = graphrag_logger.level
    events: list[tuple[str, str, dict]] = []

    async def event_sink(event_type: str, message: str, metadata: dict) -> None:
        events.append((event_type, message, metadata))

    async def search_with_native_log(query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        graphrag_logger.info("Executing local search query: %s", query)
        return {"answer": "ok", "provider": "graphrag"}

    monkeypatch.setattr(pipeline, "search", search_with_native_log)

    try:
        graphrag_logger.handlers = []
        graphrag_logger.propagate = True
        graphrag_logger.setLevel(logging.INFO)

        await service.search(query="hello", kb_name="kb", event_sink=event_sink)
        await asyncio.sleep(0)
    finally:
        graphrag_logger.handlers = original_handlers
        graphrag_logger.propagate = original_propagate
        graphrag_logger.setLevel(original_level)

    assert any(
        event_type == "raw_log"
        and message == "Executing local search query: hello"
        and metadata.get("logger") == "graphrag.api.query"
        for event_type, message, metadata in events
    )


@pytest.mark.asyncio
async def test_search_filters_noisy_vector_and_embedding_logs(
    fake_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, pipeline = fake_service
    lightrag_logger = logging.getLogger("lightrag")
    original_lightrag_level = lightrag_logger.level
    original_lightrag_propagate = lightrag_logger.propagate
    events: list[tuple[str, str, dict]] = []

    async def event_sink(event_type: str, message: str, metadata: dict) -> None:
        events.append((event_type, message, metadata))

    async def search_with_noisy_logs(query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        logging.getLogger("nano-vectordb").info("Load (13, 4096) data")
        logging.getLogger("nano-vectordb").info(
            "Init {'embedding_dim': 4096, 'metric': 'cosine'} 13 data"
        )
        logging.getLogger("deeptutor.services.embedding.adapters.openai_compatible").info(
            "Successfully generated 1 embeddings (model: Qwen/Qwen3-Embedding-8B, dimensions: 4096)"
        )
        logging.getLogger("lightrag").info(
            "Raw search results: 14 entities, 13 relations, 0 vector chunks"
        )
        return {"answer": "ok", "provider": "lightrag"}

    monkeypatch.setattr(pipeline, "search", search_with_noisy_logs)

    try:
        lightrag_logger.setLevel(logging.INFO)
        lightrag_logger.propagate = True

        await service.search(query="hello", kb_name="kb", event_sink=event_sink)
        await asyncio.sleep(0)
    finally:
        lightrag_logger.setLevel(original_lightrag_level)
        lightrag_logger.propagate = original_lightrag_propagate

    raw_messages = [message for event_type, message, _metadata in events if event_type == "raw_log"]
    assert "Raw search results: 14 entities, 13 relations, 0 vector chunks" in raw_messages
    assert not any(message.startswith("Load ") for message in raw_messages)
    assert not any(message.startswith("Init ") for message in raw_messages)
    assert not any("Successfully generated 1 embeddings" in message for message in raw_messages)


@pytest.mark.asyncio
async def test_add_documents_delegates_to_pipeline(fake_service) -> None:
    service, pipeline = fake_service

    assert await service.add_documents(kb_name="kb", file_paths=["doc.txt"]) is True
    assert pipeline.calls[-1] == {
        "op": "add_documents",
        "kb_name": "kb",
        "files": ["doc.txt"],
    }


@pytest.mark.asyncio
async def test_smart_retrieve_aggregates_passages_with_query_hints(
    fake_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, pipeline = fake_service
    pipeline.search_result = {"answer": "PASSAGE", "content": "PASSAGE", "provider": "x"}

    async def _fake_aggregate(_self, _ctx, passages):
        return "AGG:" + "|".join(passages)

    monkeypatch.setattr(SmartRetriever, "_aggregate", _fake_aggregate, raising=True)

    out = await service.smart_retrieve(
        context="anything",
        kb_name="kb",
        query_hints=["q1", "q2"],
    )
    assert out["answer"].startswith("AGG:")
    assert out["answer"].count("PASSAGE") == 2
    assert len(out["sources"]) == 2
    queries = [c["query"] for c in pipeline.calls if c["op"] == "search"]
    assert queries == ["q1", "q2"]


@pytest.mark.asyncio
async def test_smart_retrieve_returns_empty_when_no_passages(
    fake_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, pipeline = fake_service
    pipeline.search_result = {"answer": "", "content": "", "provider": "x"}

    out = await service.smart_retrieve(
        context="anything",
        kb_name="kb",
        query_hints=["q"],
    )
    assert out == {"answer": "", "sources": []}


@pytest.mark.asyncio
async def test_delete_removes_kb_directory_when_pipeline_lacks_delete(tmp_path) -> None:
    """Fallback path: delete the KB dir directly if the pipeline does not implement delete."""
    kb_dir = tmp_path / "demo"
    (kb_dir / "raw").mkdir(parents=True)
    (kb_dir / "raw" / "f.txt").write_text("hi")

    class _NoDeletePipeline:
        async def initialize(self, *a, **k):
            return True

        async def search(self, *a, **k):
            return {}

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = _NoDeletePipeline()  # type: ignore[attr-defined]

    assert await service.delete(kb_name="demo") is True
    assert not kb_dir.exists()
