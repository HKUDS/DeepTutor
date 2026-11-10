"""Check vector width across multimodal batches through the real HTTP client."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters import EmbeddingRequest
from deeptutor.services.embedding.client import EmbeddingClient
from deeptutor.services.embedding.config import EmbeddingConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("widths", [(2, 3), (3, 2)])
async def test_multimodal_dimension_drift_stops_before_the_next_batch(
    monkeypatch: pytest.MonkeyPatch, widths: tuple[int, int]
) -> None:
    real_client = httpx.AsyncClient
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        width = widths[min(len(requests) - 1, 1)]
        return httpx.Response(
            200, json={"data": [{"embedding": [0.25] * width} for _ in payload["input"]]}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    client = EmbeddingClient(
        EmbeddingConfig(
            binding="openai",
            model="Qwen3-VL-Embedding-8B",
            api_key="fixture",
            dim=0,
            base_url="https://fixture.example/v1/embeddings",
            effective_url="https://fixture.example/v1/embeddings",
            batch_size=2,
        )
    )
    progress = []
    with pytest.raises(ValueError, match="inconsistent vector dimensions across batches"):
        await client.embed_contents(
            [
                {"text": "first"},
                {"image": "https://fixture.example/image"},
                {"text": "third"},
                {"text": "fourth"},
                {"text": "unsubmitted"},
            ],
            progress_callback=lambda current, total: progress.append((current, total)),
        )
    assert len(requests) == 2
    assert progress == [(1, 3)]


@pytest.mark.asyncio
async def test_multimodal_width_is_local_to_each_call_and_preserves_item_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    class Adapter:
        width = 2

        def __init__(self, config: dict[str, Any]) -> None:
            pass

        def get_model_info(self) -> dict[str, bool]:
            return {"multimodal": True}

        async def embed(self, request: EmbeddingRequest) -> SimpleNamespace:
            return SimpleNamespace(
                embeddings=[[float(item["text"])] * self.width for item in request.contents]
            )

    monkeypatch.setattr(
        "deeptutor.services.embedding.client._resolve_adapter_class", lambda _: Adapter
    )
    client = EmbeddingClient(
        EmbeddingConfig(
            binding="openai",
            model="fixture",
            api_key="fixture",
            batch_size=2,
            dim=0,
            base_url="https://fixture.example/v1/embeddings",
        )
    )
    items = [{"text": str(i)} for i in range(5)]
    assert await client.embed_contents(items) == [[float(i)] * 2 for i in range(5)]
    client.adapter.width = 3
    assert await client.embed_contents(items) == [[float(i)] * 3 for i in range(5)]
