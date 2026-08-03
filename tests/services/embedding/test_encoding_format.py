"""Tests for the opt-in ``encoding_format`` request param.

The dataclass default is ``None`` (see ``EmbeddingRequest``). Adapters then
diverge on purpose:

* ``OpenAICompatibleEmbeddingAdapter`` (gateways) OMITS the param unless the
  caller sets one explicitly — several gateways (e.g. SiliconFlow) return
  HTTP 400 when it is present. Regression guard for #651.
* ``OpenAISDKEmbeddingAdapter`` (official OpenAI/Azure) pins ``"float"`` when
  none is set, because that API accepts it and callers expect float vectors.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)


def test_request_default_encoding_format_is_none() -> None:
    """Root-cause guard: the default must stay ``None`` so gateways omit it."""
    assert EmbeddingRequest(texts=["hi"], model="m").encoding_format is None


# ---------------------------------------------------------------------------
# OpenAI-compatible gateway payload — verified via httpx mock
# ---------------------------------------------------------------------------


class _CapturingTransport(httpx.AsyncBaseTransport):
    """Captures the outbound request and returns a canned OpenAI response."""

    def __init__(self, dim: int = 4) -> None:
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
    transport = _CapturingTransport()
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)
    return transport


def _make_adapter() -> OpenAICompatibleEmbeddingAdapter:
    return OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.example.test/v1",
            "model": "bge-large",
            "request_timeout": 30,
        }
    )


@pytest.mark.asyncio
async def test_payload_omits_encoding_format_by_default(
    capturing_httpx: _CapturingTransport,
) -> None:
    adapter = _make_adapter()
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="bge-large"))
    payload = capturing_httpx.captured_payloads[-1]
    assert "encoding_format" not in payload
    assert payload["model"] == "bge-large"


@pytest.mark.asyncio
async def test_payload_includes_encoding_format_when_set(
    capturing_httpx: _CapturingTransport,
) -> None:
    adapter = _make_adapter()
    await adapter.embed(
        EmbeddingRequest(texts=["hello"], model="bge-large", encoding_format="base64")
    )
    assert capturing_httpx.captured_payloads[-1].get("encoding_format") == "base64"
