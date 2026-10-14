"""RAGService query-rewrite integration tests (with a fake pipeline).

These verify that :meth:`RAGService.search` threads the rewrite layer through
the production path: the rewritten query reaches the pipeline, the ``rewrite``
control kwarg never leaks to the engine, and provenance is attached to the
result only when a rewrite actually ran.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

import deeptutor.services.rag.service as rag_service_module
from deeptutor.services.rag.service import RAGService


class _RecordingPipeline:
    """Pipeline stub that records the exact query/kwargs it receives."""

    def __init__(self, search_result: Dict[str, Any] | None = None) -> None:
        self.calls: list[dict] = []
        self.search_result = search_result or {
            "answer": "fake answer",
            "sources": [{"id": 1}],
            "provider": "llamaindex",
        }

    async def initialize(self, kb_name: str, file_paths, **kwargs) -> bool:
        return True

    async def add_documents(self, kb_name: str, file_paths, **kwargs) -> bool:
        return True

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        self.calls.append({"query": query, "kb_name": kb_name, "kwargs": kwargs})
        return dict(self.search_result)

    async def delete(self, kb_name: str) -> bool:
        return True


@pytest.fixture
def service_with_pipeline(tmp_path, monkeypatch) -> tuple[RAGService, _RecordingPipeline]:
    """An RAGService whose default provider resolves to a recording stub."""
    from deeptutor.services.rag import index_probe

    monkeypatch.setattr(
        index_probe, "latest_ready_provider_version", lambda *args: {"version": "fake"}
    )
    pipeline = _RecordingPipeline()
    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = pipeline  # type: ignore[attr-defined]
    return service, pipeline


def _patch_rewrite(monkeypatch, effective_query: str, outcome: Any):
    """Replace the service's maybe_rewrite with a deterministic stub."""
    import deeptutor.services.rag.query_rewrite as qr

    async def _fake(query, *, rewrite=None, settings=None, complete_fn=None):
        return effective_query, outcome

    monkeypatch.setattr(qr, "maybe_rewrite", _fake)


@pytest.mark.asyncio
async def test_search_passes_rewritten_query_to_pipeline(service_with_pipeline, monkeypatch):
    """When a rewrite runs, the pipeline receives the rewritten query."""
    from deeptutor.services.rag.query_rewrite import RewriteOutcome

    service, pipeline = service_with_pipeline
    outcome = RewriteOutcome(
        original="what is x", rewritten="explicit keyword query", strategy="standalone"
    )
    _patch_rewrite(monkeypatch, "explicit keyword query", outcome)

    result = await service.search(query="what is x", kb_name="kb", rewrite=True)

    assert pipeline.calls[-1]["query"] == "explicit keyword query"
    assert result["query_rewrite"] == outcome.to_dict()
    assert result["query_rewrite"]["rewritten"] == "explicit keyword query"


@pytest.mark.asyncio
async def test_search_does_not_leak_rewrite_kwarg_to_pipeline(service_with_pipeline, monkeypatch):
    """The ``rewrite`` control kwarg must never reach the engine."""
    from deeptutor.services.rag.query_rewrite import RewriteOutcome

    service, pipeline = service_with_pipeline
    outcome = RewriteOutcome(original="q", rewritten="q2", strategy="standalone")
    _patch_rewrite(monkeypatch, "q2", outcome)

    await service.search(query="q", kb_name="kb", rewrite=True, top_k=5, mode="hybrid")

    kwargs = pipeline.calls[-1]["kwargs"]
    assert "rewrite" not in kwargs
    # Unrelated kwargs still forward untouched.
    assert kwargs.get("top_k") == 5
    assert kwargs.get("mode") == "hybrid"


@pytest.mark.asyncio
async def test_search_no_rewrite_omits_provenance(service_with_pipeline, monkeypatch):
    """When the layer is off (outcome None), no query_rewrite is attached."""
    service, pipeline = service_with_pipeline
    _patch_rewrite(monkeypatch, "original query", None)

    result = await service.search(query="original query", kb_name="kb", rewrite=False)

    assert pipeline.calls[-1]["query"] == "original query"
    assert "query_rewrite" not in result


@pytest.mark.asyncio
async def test_search_emits_rewrite_status_event(service_with_pipeline, monkeypatch):
    """A rewrite emits a status event carrying the provenance dict."""
    from deeptutor.services.rag.query_rewrite import RewriteOutcome

    service, pipeline = service_with_pipeline
    outcome = RewriteOutcome(original="what is x", rewritten="kw query", strategy="standalone")
    _patch_rewrite(monkeypatch, "kw query", outcome)

    events: list[tuple[str, dict]] = []

    async def _sink(event_type, message, metadata=None):
        events.append((event_type, metadata or {}))

    await service.search(query="what is x", kb_name="kb", rewrite=True, event_sink=_sink)

    rewrite_events = [m for (t, m) in events if "rewrite_outcome" in m]
    assert rewrite_events, "expected a status event carrying rewrite_outcome"
    assert rewrite_events[0]["rewrite_outcome"]["rewritten"] == "kw query"


@pytest.mark.asyncio
async def test_search_error_path_keeps_rewrite_provenance(service_with_pipeline, monkeypatch):
    """If the engine errors after a rewrite, provenance is still attached."""
    from deeptutor.services.rag.query_rewrite import RewriteOutcome

    service, pipeline = service_with_pipeline
    pipeline.search_result = {"error_type": "index_missing", "answer": "reindex needed"}
    outcome = RewriteOutcome(original="q", rewritten="q2", strategy="standalone")
    _patch_rewrite(monkeypatch, "q2", outcome)

    result = await service.search(query="q", kb_name="kb", rewrite=True)

    assert result.get("error_type") == "index_missing"
    assert result["query_rewrite"] == outcome.to_dict()
