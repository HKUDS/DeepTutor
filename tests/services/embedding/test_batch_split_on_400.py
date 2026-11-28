"""Tests for splitting a rejected embedding batch into halves.

Some OpenAI-compatible gateways answer HTTP 400 for a batch they consider too
large instead of 413. SiliconFlow's bge-m3 is one: ten documents of 1.0-1.7k
characters get ``20015 parameter is invalid`` while the same documents embed
fine in smaller groups, which used to abort a whole reindex.

The adapter now halves the batch on 400 and retries. These tests pin the parts
that are easy to get wrong: input order, usage accounting, and the bound on
how many requests a persistent failure may cost.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingProviderError, EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
    _merge_usage,
)


class _BatchLimitTransport(httpx.AsyncBaseTransport):
    """Rejects any batch above ``max_batch`` the way SiliconFlow bge-m3 does.

    Successful responses encode each input's length in its first dimension so
    the caller can assert the vectors came back in the order the texts went in.
    """

    def __init__(self, max_batch: int = 2, status: int = 400) -> None:
        self.max_batch = max_batch
        self.status = status
        self.payloads: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        payload = _json.loads(request.content.decode("utf-8"))
        self.payloads.append(payload)
        texts = payload.get("input")
        if not isinstance(texts, list) or len(texts) > self.max_batch:
            return httpx.Response(
                self.status,
                json={"code": 20015, "message": "The parameter is invalid. Please check again."},
            )
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": index, "embedding": [float(len(text)), 1.0]}
                    for index, text in enumerate(texts)
                ],
                "model": "bge-m3",
                "usage": {
                    "prompt_tokens": sum(len(text) for text in texts),
                    "total_tokens": sum(len(text) for text in texts),
                },
            },
        )


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.AsyncBaseTransport
) -> None:
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _make_adapter(model: str = "bge-m3") -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1/embeddings",
            "model": model,
            "request_timeout": 30,
        }
    )


@pytest.mark.asyncio
async def test_oversized_batch_is_split_and_keeps_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _BatchLimitTransport(max_batch=2)
    _install_transport(monkeypatch, transport)
    texts = ["a", "bb", "ccc", "dddd", "eeeee", "ffffff"]

    response = await _make_adapter().embed(EmbeddingRequest(texts=texts, model="bge-m3"))

    assert [vector[0] for vector in response.embeddings] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    # 6 -> 3+3 -> 1+2 for each half: seven requests, all on the same payload shape.
    assert len(transport.payloads) == 7
    assert all(payload["model"] == "bge-m3" for payload in transport.payloads)


@pytest.mark.asyncio
async def test_usage_is_summed_across_sub_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _BatchLimitTransport(max_batch=2)
    _install_transport(monkeypatch, transport)
    texts = ["a", "bb", "ccc", "dddd"]

    response = await _make_adapter().embed(EmbeddingRequest(texts=texts, model="bge-m3"))

    assert response.usage["prompt_tokens"] == 10
    assert response.usage["total_tokens"] == 10


@pytest.mark.asyncio
async def test_a_single_text_that_still_fails_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The split must bottom out: one text cannot be halved any further."""
    transport = _BatchLimitTransport(max_batch=0)
    _install_transport(monkeypatch, transport)

    with pytest.raises(EmbeddingProviderError) as raised:
        await _make_adapter().embed(EmbeddingRequest(texts=["hello"], model="bge-m3"))

    assert raised.value.status == 400
    assert len(transport.payloads) == 1


@pytest.mark.asyncio
async def test_non_400_failures_are_not_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a 400 can be a batch-size complaint; a 500 would just multiply."""
    transport = _BatchLimitTransport(max_batch=0, status=500)
    _install_transport(monkeypatch, transport)

    with pytest.raises(EmbeddingProviderError) as raised:
        await _make_adapter().embed(EmbeddingRequest(texts=["a", "b", "c", "d"], model="bge-m3"))

    assert raised.value.status == 500
    assert len(transport.payloads) == 1


@pytest.mark.asyncio
async def test_multimodal_contents_are_not_split(monkeypatch: pytest.MonkeyPatch) -> None:
    """``contents`` replaces ``texts``, so halving the text list is a no-op."""
    transport = _BatchLimitTransport(max_batch=0)
    _install_transport(monkeypatch, transport)
    request = EmbeddingRequest(
        texts=[],
        model="qwen3-vl-embedding",
        contents=[{"text": "a"}, {"text": "b"}],
    )

    with pytest.raises(EmbeddingProviderError):
        await _make_adapter("qwen3-vl-embedding").embed(request)

    assert len(transport.payloads) == 1


def test_merge_usage_sums_counters_and_keeps_the_first_non_numeric_value() -> None:
    merged = _merge_usage(
        {"prompt_tokens": 3, "total_tokens": 3, "model": "bge-m3"},
        {"prompt_tokens": 4, "total_tokens": 4, "model": "other"},
    )

    assert merged == {"prompt_tokens": 7, "total_tokens": 7, "model": "bge-m3"}
