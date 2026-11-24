"""Provider vector indices must preserve the association with requested texts."""

import json

import httpx
import pytest

from deeptutor.services.embedding.adapters.openai_compatible import OpenAICompatibleEmbeddingAdapter
from deeptutor.services.embedding.client import EmbeddingClient
from deeptutor.services.embedding.config import EmbeddingConfig


@pytest.mark.parametrize("wrapper", ["data", "result", "output"])
def test_indexed_response_is_reordered_without_mutating_provider_data(wrapper):
    rows = [{"index": 1, "embedding": [2.0, 1.0]}, {"index": 0, "embedding": [1.0, 1.0]}]
    payload = {"data": rows} if wrapper == "data" else {wrapper: {"data": rows}}
    assert OpenAICompatibleEmbeddingAdapter._extract_embeddings_from_response(payload) == [
        [1.0, 1.0],
        [2.0, 1.0],
    ]
    assert rows[0]["index"] == 1


@pytest.mark.parametrize(
    "indices", [[0, 0], [0, 2], [1, 2], [-1, 0], [True, 0], ["0", 1], [None, 1]]
)
def test_invalid_or_partial_indices_are_rejected(indices):
    rows = [{"index": i, "embedding": [1.0, 2.0]} for i in indices]
    with pytest.raises(ValueError, match="indices"):
        OpenAICompatibleEmbeddingAdapter._extract_embeddings_from_response({"data": rows})


def test_missing_index_in_otherwise_indexed_response_is_rejected():
    with pytest.raises(ValueError, match="indices"):
        OpenAICompatibleEmbeddingAdapter._extract_embeddings_from_response(
            {
                "data": [
                    {"index": 0, "embedding": [1.0]},
                    {"embedding": [2.0]},
                ]
            }
        )


@pytest.mark.asyncio
async def test_client_preserves_text_vector_association_across_batches(monkeypatch):
    original = httpx.AsyncClient
    batches = []

    def handle(request):
        texts = json.loads(request.content)["input"]
        batches.append(texts)
        return httpx.Response(
            200,
            json={
                "data": list(
                    reversed(
                        [
                            {"index": i, "embedding": [float(text), 1.0]}
                            for i, text in enumerate(texts)
                        ]
                    )
                )
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    client = EmbeddingClient(
        EmbeddingConfig(
            binding="custom",
            model="synthetic",
            api_key="test",
            base_url="https://fixture.invalid/v1/embeddings",
            dim=2,
            batch_size=2,
        )
    )
    vectors = await client.embed(["1", "2", "3", "4", "5"])
    assert vectors == [[float(i), 1.0] for i in range(1, 6)]
    assert sorted(len(batch) for batch in batches) == [1, 2, 2]


@pytest.mark.asyncio
async def test_invalid_indexed_http_success_is_not_retried(monkeypatch):
    original = httpx.AsyncClient
    attempts = []

    def handle(request):
        attempts.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 2.0]},
                    {"index": 0, "embedding": [3.0, 4.0]},
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    client = EmbeddingClient(
        EmbeddingConfig(
            binding="custom",
            model="synthetic",
            api_key="test",
            base_url="https://fixture.invalid/v1/embeddings",
            dim=2,
            batch_size=2,
        )
    )
    with pytest.raises(ValueError, match="indices"):
        await client.embed(["first", "second"])
    assert len(attempts) == 1
