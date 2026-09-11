"""Tests for role-aware Jina embedding requests."""

from __future__ import annotations

import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.jina import JinaEmbeddingAdapter


@pytest.mark.asyncio
async def test_jina_adapter_maps_retrieval_roles_to_tasks(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": [{"embedding": [0.1, 0.2]}],
                "model": "jina-embeddings-v3",
            }

    class _AsyncClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, object], **_kwargs):
            captured["url"] = url
            captured["payload"] = json
            return _Response()

    monkeypatch.setattr(
        "deeptutor.services.embedding.adapters.jina.httpx.AsyncClient", _AsyncClient
    )
    adapter = JinaEmbeddingAdapter(
        {
            "api_key": "test-key",
            "base_url": "https://api.jina.ai/v1/embeddings",
            "model": "jina-embeddings-v3",
            "dimensions": 2,
        }
    )

    document_request = EmbeddingRequest(
        texts=["document text"],
        model="jina-embeddings-v3",
        dimensions=2,
        input_type="search_document",
    )
    await adapter.embed(document_request)
    assert captured["payload"]["task"] == "retrieval.passage"

    query_request = EmbeddingRequest(
        texts=["query text"],
        model="jina-embeddings-v3",
        dimensions=2,
        input_type="search_query",
    )
    await adapter.embed(query_request)
    assert captured["payload"]["task"] == "retrieval.query"
