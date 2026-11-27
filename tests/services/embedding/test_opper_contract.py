"""Exercise the Opper catalog-to-HTTP path without paid provider calls.

The qualified model ID is documented at
https://opper.ai/openai/text-embedding-3-large. Transport stubbing validates
our wire contract, not live availability or whether aliases are accepted.
"""

from __future__ import annotations

import json

import httpx
import pytest

from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
from deeptutor.services.embedding.client import EmbeddingClient
from deeptutor.services.embedding.config import get_embedding_config


@pytest.mark.asyncio
async def test_opper_default_embedding_posts_qualified_model_and_reads_vectors(monkeypatch):
    spec = EMBEDDING_PROVIDERS["opper"]
    profile = {
        "id": "opper-profile",
        "binding": "opper",
        "base_url": "",
        "api_key": "test-opper-key",
        "models": [
            {"id": "embedding-model", "model": spec.default_model, "dimension": spec.default_dim}
        ],
    }
    catalog = {
        "version": 1,
        "services": {
            "embedding": {
                "active_profile_id": profile["id"],
                "active_model_id": "embedding-model",
                "profiles": [profile],
            }
        },
    }
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.opper.ai/v3/compat/embeddings"
        assert request.headers["Authorization"] == "Bearer test-opper-key"
        assert json.loads(request.content) == {
            "model": "openai/text-embedding-3-large",
            "input": ["first", "second"],
        }
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "openai/text-embedding-3-large",
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [0.1] * 3072},
                    {"object": "embedding", "index": 1, "embedding": [0.2] * 3072},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await EmbeddingClient(get_embedding_config(catalog=catalog)).embed(["first", "second"])
    assert result == [[0.1] * 3072, [0.2] * 3072]
    assert len(requests) == 1
