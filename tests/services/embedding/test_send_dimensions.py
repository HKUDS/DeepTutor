"""Tests for the tri-state ``send_dimensions`` opt-in.

Covers:

* ``OpenAICompatibleEmbeddingAdapter._should_send_dimensions`` (pure logic)
* The actual HTTP payload assembled by ``embed()`` (verified via httpx mock)

Tri-state semantics:

* ``True``  → always send the ``dimensions`` request param
* ``False`` → never send the param (e.g. Qwen ``text-embedding-v4`` gateways
  return HTTP 400 if it is present)
* ``None``  → fall back to the model-family heuristic from PR #368, i.e. send
  only for the OpenAI ``text-embedding-3*`` family
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)

# ---------------------------------------------------------------------------
# _should_send_dimensions — pure tri-state logic
# ---------------------------------------------------------------------------


def _make_adapter(*, model: str, send_dimensions: bool | None) -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1",
            "model": model,
            "dimensions": 512,
            "send_dimensions": send_dimensions,
            "request_timeout": 30,
        }
    )


class TestShouldSendDimensions:
    """Pure-logic tests against the helper."""

    @pytest.mark.parametrize(
        "model",
        [
            "text-embedding-3-small",
            "text-embedding-3-large",
            "text-embedding-3-foo",  # any future 3* variant
        ],
    )
    def test_auto_sends_for_text_embedding_3_family(self, model: str) -> None:
        adapter = _make_adapter(model=model, send_dimensions=None)
        assert adapter._should_send_dimensions(model) is True

    @pytest.mark.parametrize(
        "model",
        [
            "text-embedding-ada-002",
            "text-embedding-v4",  # Qwen / DashScope
            "embed-v4.0",  # Cohere
            "jina-embeddings-v3",
            "nomic-embed-text",
            "",  # empty / unknown
        ],
    )
    def test_auto_skips_for_non_3_family(self, model: str) -> None:
        adapter = _make_adapter(model=model, send_dimensions=None)
        assert adapter._should_send_dimensions(model) is False

    def test_explicit_true_overrides_heuristic(self) -> None:
        # Even for a model the heuristic would skip, ``True`` forces send.
        adapter = _make_adapter(model="text-embedding-v4", send_dimensions=True)
        assert adapter._should_send_dimensions("text-embedding-v4") is True

    def test_explicit_false_overrides_heuristic(self) -> None:
        # Even for OpenAI 3*, explicit ``False`` skips.
        adapter = _make_adapter(model="text-embedding-3-large", send_dimensions=False)
        assert adapter._should_send_dimensions("text-embedding-3-large") is False

    def test_none_model_treated_as_non_3(self) -> None:
        adapter = _make_adapter(model="", send_dimensions=None)
        assert adapter._should_send_dimensions(None) is False


# ---------------------------------------------------------------------------
# embed() — request payload assembly verified via httpx mock
# ---------------------------------------------------------------------------


class _CapturingTransport(httpx.AsyncBaseTransport):
    """Captures the outbound request and returns a canned OpenAI response."""

    def __init__(self, dim: int = 512) -> None:
        self.captured_payloads: list[dict[str, Any]] = []
        self._dim = dim

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        self.captured_payloads.append(_json.loads(request.content.decode("utf-8")))
        body = {
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * self._dim}],
            "model": "stub",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
        return httpx.Response(200, json=body)


@pytest.fixture
def capturing_httpx(monkeypatch: pytest.MonkeyPatch) -> _CapturingTransport:
    """Patch ``httpx.AsyncClient`` so every adapter call hits an in-memory mock."""

    transport = _CapturingTransport()
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)
    return transport


def _request(model: str) -> EmbeddingRequest:
    return EmbeddingRequest(texts=["hello"], model=model, dimensions=512)


@pytest.mark.asyncio
async def test_payload_omits_dimensions_when_explicitly_disabled(
    capturing_httpx: _CapturingTransport,
) -> None:
    adapter = _make_adapter(model="text-embedding-3-large", send_dimensions=False)
    await adapter.embed(_request("text-embedding-3-large"))
    payload = capturing_httpx.captured_payloads[-1]
    assert "dimensions" not in payload
    assert payload["model"] == "text-embedding-3-large"


@pytest.mark.asyncio
async def test_payload_includes_dimensions_when_explicitly_enabled(
    capturing_httpx: _CapturingTransport,
) -> None:
    # Even for a model the heuristic would skip (e.g. Qwen v4), the explicit
    # opt-in still sends `dimensions`.
    adapter = _make_adapter(model="text-embedding-v4", send_dimensions=True)
    await adapter.embed(_request("text-embedding-v4"))
    payload = capturing_httpx.captured_payloads[-1]
    assert payload.get("dimensions") == 512


@pytest.mark.asyncio
async def test_payload_auto_includes_dimensions_for_text_embedding_3(
    capturing_httpx: _CapturingTransport,
) -> None:
    adapter = _make_adapter(model="text-embedding-3-small", send_dimensions=None)
    await adapter.embed(_request("text-embedding-3-small"))
    assert capturing_httpx.captured_payloads[-1].get("dimensions") == 512


@pytest.mark.asyncio
async def test_payload_auto_skips_dimensions_for_non_openai_models(
    capturing_httpx: _CapturingTransport,
) -> None:
    # Regression guard for PR #368: a Qwen / DashScope deployment using the
    # default Auto setting must NOT trigger the gateway's HTTP 400.
    adapter = _make_adapter(model="text-embedding-v4", send_dimensions=None)
    await adapter.embed(_request("text-embedding-v4"))
    assert "dimensions" not in capturing_httpx.captured_payloads[-1]
