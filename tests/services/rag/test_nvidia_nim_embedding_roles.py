"""Retrieval roles reach NIM through the existing RAG bridges."""

from __future__ import annotations

import json
import sys
from types import ModuleType

import httpx
import pytest

from deeptutor.services.embedding.client import EmbeddingClient
from deeptutor.services.embedding.config import EmbeddingConfig


@pytest.fixture
def nim_client(monkeypatch):
    calls = []
    real_client = httpx.AsyncClient

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [float(text), 1.0]}
                    for i, text in enumerate(payload["input"])
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    client = EmbeddingClient(
        EmbeddingConfig(
            model="nvidia/nemotron-3.5-embed-8b",
            binding="nvidia_nim",
            dim=2,
            api_key="test-key",
            base_url="https://gateway.test/v1/embeddings",
        )
    )
    return client, calls


@pytest.mark.asyncio
async def test_llamaindex_document_query_and_batch_reach_nim(nim_client, monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import embedding_adapter

    client, calls = nim_client
    monkeypatch.setattr(embedding_adapter, "get_embedding_client", lambda config=None: client)
    adapter = embedding_adapter.CustomEmbedding(embedding_config=client.config)
    assert await adapter.aget_text_embedding("1") == [1, 1]
    assert await adapter.aget_query_embedding("2") == [2, 1]
    assert await adapter.aget_text_embedding_batch(["3", "4"]) == [[3, 1], [4, 1]]
    assert [p["input_type"] for p in calls] == ["passage", "query", "passage"]


@pytest.mark.asyncio
async def test_lightrag_context_reaches_nim_with_lightweight_sdk_wrapper(
    nim_client, monkeypatch
) -> None:
    from deeptutor.services.rag.pipelines.lightrag.config import build_embedding_func

    client, calls = nim_client

    # Exercise DeepTutor's real bridge with a minimal SDK shell; no graph/vector
    # server is required to verify the requests leaving its embedding callback.
    class EmbeddingFunc:
        def __init__(self, *, func, embedding_dim, max_token_size, supports_asymmetric=False):
            self.func = func
            self.supports_asymmetric = supports_asymmetric

    sdk = ModuleType("lightrag.utils")
    sdk.EmbeddingFunc = EmbeddingFunc
    monkeypatch.setitem(sys.modules, "lightrag.utils", sdk)
    adapter = build_embedding_func(embedding_config=client.config)
    assert adapter.supports_asymmetric
    assert (await adapter.func(["1"], context="document")).tolist() == [[1, 1]]
    assert (await adapter.func(["2"], context="query")).tolist() == [[2, 1]]
    assert [p["input_type"] for p in calls] == ["passage", "query"]
