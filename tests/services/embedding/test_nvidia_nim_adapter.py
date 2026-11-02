"""NVIDIA's explicit text embedding binding and retrieval request contract."""

from __future__ import annotations

from dataclasses import replace
import json

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingProviderError, EmbeddingRequest
from deeptutor.services.embedding.client import EmbeddingClient
from deeptutor.services.embedding.config import EmbeddingConfig


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,expected", [("search_document", "passage"), ("search_query", "query")]
)
async def test_nim_binding_sends_retrieval_role(monkeypatch, role, expected) -> None:
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    client = EmbeddingClient(
        EmbeddingConfig(
            model="nvidia/nemotron-3.5-embed-8b",
            binding="nvidia_nim",
            api_key="test-key",
            base_url="https://gateway.test/custom/embeddings?tenant=test",
            dim=2,
        )
    )
    assert await client.embed(["synthetic text"], input_type=role) == [[0.1, 0.2]]
    assert calls[0]["input_type"] == expected


MODEL = "nvidia/nemotron-3.5-embed-8b"
ENDPOINT = "https://gateway.test/prefix/embeddings?tenant=test"


def _config(**kwargs) -> EmbeddingConfig:
    return replace(
        EmbeddingConfig(
            model=MODEL,
            binding="nvidia_nim",
            api_key="test-key",
            base_url=ENDPOINT,
            dim=2,
            batch_size=2,
            extra_headers={"X-Tenant": "fixture"},
        ),
        **kwargs,
    )


def _transport(monkeypatch, handler):
    real_client = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    return calls


def _response(request):
    payload = json.loads(request.content)
    dim = payload.get("dimensions", 4096)
    return httpx.Response(
        200,
        json={
            "data": [
                {"index": i, "embedding": [float(text)] * dim}
                for i, text in reversed(list(enumerate(payload["input"])))
            ]
        },
    )


@pytest.mark.asyncio
async def test_nim_batches_preserve_input_order_endpoint_headers_and_progress(monkeypatch) -> None:
    calls = _transport(monkeypatch, _response)
    client = EmbeddingClient(_config())
    progress = []
    vectors = await client.embed(
        ["1", "2", "3"], lambda *p: progress.append(p), input_type="search_query"
    )
    assert vectors == [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]
    assert progress == [(1, 2), (2, 2)]
    assert [json.loads(r.content)["input"] for r in calls] == [["1", "2"], ["3"]]
    for request in calls:
        assert str(request.url) == ENDPOINT
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["X-Tenant"] == "fixture"
        assert json.loads(request.content)["input_type"] == "query"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dimension,send,expected", [(0, None, None), (2, None, 2), (2, True, 2), (2, False, None)]
)
async def test_nim_dimension_policy_and_unqualified_connection_checks(
    monkeypatch, dimension, send, expected
) -> None:
    calls = _transport(monkeypatch, _response)
    vectors = await EmbeddingClient(_config(dim=dimension, send_dimensions=send)).embed(["1"])
    payload = json.loads(calls[0].content)
    assert payload.get("dimensions") == expected
    assert payload["input_type"] == "passage"
    assert payload["encoding_format"] == "float"
    assert len(vectors[0]) == (expected or 4096)


@pytest.mark.asyncio
async def test_nim_empty_input_and_multimodal_rejection_do_not_send_http(monkeypatch) -> None:
    calls = _transport(monkeypatch, lambda r: pytest.fail("unexpected HTTP"))
    client = EmbeddingClient(_config())
    assert await client.embed([]) == []
    assert (await client.adapter.embed(EmbeddingRequest(texts=[], model=MODEL))).embeddings == []
    assert not client.supports_multimodal_contents()
    with pytest.raises(ValueError, match="multimodal"):
        await client.embed_contents([{"image": "data:image/png;base64,fixture"}])
    for contents in ([], [{"text": "1"}], [{"image": "fixture"}]):
        with pytest.raises(ValueError, match="multimodal"):
            await client.adapter.embed(
                EmbeddingRequest(texts=["1"], model=MODEL, contents=contents)
            )
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", [-1, 4097, True])
async def test_nim_rejects_invalid_hosted_dimensions_before_http(monkeypatch, dimension) -> None:
    calls = _transport(monkeypatch, lambda r: pytest.fail("unexpected HTTP"))
    with pytest.raises(ValueError, match="dimensions"):
        await EmbeddingClient(_config(dim=dimension)).embed(["1"])
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,error",
    [("input_type", "classification", "role"), ("encoding_format", "base64", "float")],
)
async def test_nim_rejects_unsupported_request_options(monkeypatch, field, value, error) -> None:
    _transport(monkeypatch, lambda r: pytest.fail("unexpected HTTP"))
    request = replace(EmbeddingRequest(texts=["1"], model=MODEL), **{field: value})
    with pytest.raises(ValueError, match=error):
        await EmbeddingClient(_config()).adapter.embed(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        [],
        [{"embedding": [1, 2]}],
        [{"index": True, "embedding": [1, 2]}],
        [{"index": -1, "embedding": [1, 2]}],
        [{"index": 2, "embedding": [1, 2]}],
        [{"index": 0, "embedding": [1, 2]}, {"index": 0, "embedding": [1, 2]}],
        [{"index": 0, "embedding": [1, 2]}],  # One vector for two inputs.
        [{"index": 0, "embedding": [1, 2]}, {"index": 1, "embedding": [1]}],
        [{"index": 0, "embedding": [1, None]}, {"index": 1, "embedding": [1, 2]}],
        [{"index": 0, "embedding": [1, 2, 3]}, {"index": 1, "embedding": [1, 2, 3]}],
    ],
)
async def test_nim_refuses_ambiguous_or_invalid_vectors(monkeypatch, data) -> None:
    _transport(monkeypatch, lambda r: httpx.Response(200, json={"data": data}))
    with pytest.raises(ValueError):
        await EmbeddingClient(_config()).embed(["1", "2"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401])
async def test_nim_permanent_http_errors_are_not_retried(monkeypatch, status) -> None:
    calls = _transport(monkeypatch, lambda r: httpx.Response(status, json={"error": "rejected"}))
    with pytest.raises(EmbeddingProviderError) as error:
        await EmbeddingClient(_config()).embed(["1"])
    assert error.value.status == status
    assert error.value.provider == "nvidia_nim"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["429", "timeout", "exhausted"])
async def test_nim_reuses_bounded_shared_retries(monkeypatch, failure) -> None:
    import asyncio

    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    attempts = 0

    def respond(request):
        nonlocal attempts
        attempts += 1
        if failure == "exhausted" or (failure == "429" and attempts == 1):
            return httpx.Response(429, headers={"Retry-After": "1"})
        if failure == "timeout" and attempts == 1:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return _response(request)

    _transport(monkeypatch, respond)
    client = EmbeddingClient(_config())
    if failure == "exhausted":
        with pytest.raises(EmbeddingProviderError) as error:
            await client.embed(["1"])
        assert error.value.status == 429
        assert attempts == 9 and len(sleeps) == 8
    else:
        assert await client.embed(["1"]) == [[1, 1]]
        assert attempts == 2 and len(sleeps) == 1


@pytest.mark.asyncio
async def test_custom_profile_on_nvidia_host_keeps_legacy_wire_contract(monkeypatch) -> None:
    calls = _transport(monkeypatch, _response)
    client = EmbeddingClient(
        _config(binding="custom", base_url="https://integrate.api.nvidia.com/v1/embeddings")
    )
    await client.embed(["1"], input_type="search_query")
    payload = json.loads(calls[0].content)
    assert "input_type" not in payload
    assert "encoding_format" not in payload
    assert "dimensions" not in payload


def test_nim_catalog_resolution_and_default_endpoint() -> None:
    from deeptutor.services.config.embedding_endpoint import (
        normalize_embedding_endpoint_for_display,
    )
    from deeptutor.services.embedding.config import get_embedding_config

    catalog = {
        "services": {
            "embedding": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "binding": "nvidia_nim",
                        "api_key": "test-key",
                        "models": [
                            {
                                "id": "m",
                                "model": MODEL,
                                "dimension": 4096,
                            }
                        ],
                    }
                ],
            }
        }
    }
    config = get_embedding_config(catalog=catalog)
    assert config.binding == "nvidia_nim"
    assert config.effective_url == "https://integrate.api.nvidia.com/v1/embeddings"
    assert normalize_embedding_endpoint_for_display("nvidia_nim", "") == config.effective_url
    assert not EmbeddingClient(config).supports_multimodal_contents()
