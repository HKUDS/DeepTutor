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

from deeptutor.services.embedding.adapters.base import EmbeddingProviderError, EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
    rejects_absent_encoding_format,
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


# ---------------------------------------------------------------------------
# Gateways that require the param — recovered from their own refusal (#934)
# ---------------------------------------------------------------------------


class _RequiresEncodingFormatTransport(httpx.AsyncBaseTransport):
    """ModelScope's behaviour: reject the request until the param is present.

    Its 400 reads ``encoding_format must be 'float' or 'base64', got ''`` —
    the missing field is read as an empty value rather than as absent.
    """

    def __init__(self, dim: int = 4) -> None:
        self.captured_payloads: list[dict[str, Any]] = []
        self._dim = dim

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        payload = _json.loads(request.content.decode("utf-8"))
        self.captured_payloads.append(payload)
        if not payload.get("encoding_format"):
            return httpx.Response(
                400,
                json={"errors": {"message": "encoding_format must be 'float' or 'base64', got ''"}},
            )
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1] * self._dim}],
                "model": "stub",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
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


@pytest.mark.asyncio
async def test_gateway_requiring_encoding_format_succeeds_on_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#934: ModelScope + Qwen3-Embedding-8B embedded nothing at all."""
    transport = _RequiresEncodingFormatTransport()
    _install_transport(monkeypatch, transport)

    adapter = OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api-inference.modelscope.cn/v1/embeddings",
            "model": "Qwen/Qwen3-Embedding-8B",
            "request_timeout": 30,
        }
    )
    response = await adapter.embed(
        EmbeddingRequest(texts=["hello"], model="Qwen/Qwen3-Embedding-8B")
    )

    assert response.embeddings
    # First attempt omits it (so #651's gateways stay unbroken), second adds it.
    assert "encoding_format" not in transport.captured_payloads[0]
    assert transport.captured_payloads[1]["encoding_format"] == "float"
    assert len(transport.captured_payloads) == 2


def test_recovery_only_fires_when_the_provider_names_param_and_value() -> None:
    """The discriminator against #651, whose 400 names neither."""
    assert rejects_absent_encoding_format(
        400, "{\"errors\":{\"message\":\"encoding_format must be 'float' or 'base64', got ''\"}}"
    )
    # SiliconFlow rejecting the param's *presence* — must not trigger a retry
    # that would add it back.
    assert not rejects_absent_encoding_format(
        400, '{"code":20015,"message":"The parameter is invalid. Please check again."}'
    )
    # A gateway that does not support the param at all names it but not "float".
    assert not rejects_absent_encoding_format(400, "unknown parameter: encoding_format")
    # Only a 400 is a parameter complaint.
    assert not rejects_absent_encoding_format(500, "encoding_format must be 'float'")


@pytest.mark.asyncio
async def test_a_persistent_400_still_surfaces_after_one_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry is bounded: a gateway that keeps refusing must not loop."""

    class _AlwaysRefuses(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(
                400, json={"error": "encoding_format must be 'float' or 'base64'"}
            )

    transport = _AlwaysRefuses()
    _install_transport(monkeypatch, transport)

    adapter = _make_adapter()
    with pytest.raises(EmbeddingProviderError):
        await adapter.embed(EmbeddingRequest(texts=["hello"], model="bge-large"))
    assert transport.calls == 2
