"""Tests for Gemini native and legacy-compatible embedding requests."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import (
    EmbeddingProviderError,
    EmbeddingRequest,
)
from deeptutor.services.embedding.adapters.gemini import GeminiEmbeddingAdapter

NATIVE_GEMINI2_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents"
)
NATIVE_GEMINI001_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-001:batchEmbedContents"
)
LEGACY_OPENAI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"


class _CapturingTransport(httpx.AsyncBaseTransport):
    """Capture outbound requests and return deterministic embeddings."""

    def __init__(self, dimension: int = 768) -> None:
        self.requests: list[dict[str, Any]] = []
        self.dimension = dimension
        self.status_code = 200
        self.error_body = ""
        self.transport_error: httpx.TransportError | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.transport_error is not None:
            raise self.transport_error
        payload = json.loads(request.content.decode("utf-8"))
        self.requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": payload,
            }
        )
        if self.status_code >= 400:
            return httpx.Response(self.status_code, text=self.error_body)

        if "requests" in payload:
            embeddings = [{"values": [0.1] * self.dimension} for _ in payload["requests"]]
            return httpx.Response(200, json={"embeddings": embeddings})

        inputs = payload["input"] if isinstance(payload["input"], list) else [payload["input"]]
        embeddings = [
            {"index": index, "embedding": [0.1] * self.dimension} for index, _ in enumerate(inputs)
        ]
        return httpx.Response(
            200,
            json={"data": embeddings, "model": payload["model"], "usage": {}},
        )


@pytest.fixture
def capturing_httpx(monkeypatch: pytest.MonkeyPatch) -> _CapturingTransport:
    """Route adapter HTTP calls through an in-memory transport."""

    transport = _CapturingTransport()
    real_client_init = httpx.AsyncClient.__init__

    def _patched_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = transport
        real_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)
    return transport


def _adapter(
    *,
    model: str = "gemini-embedding-2",
    base_url: str = NATIVE_GEMINI2_ENDPOINT,
    dimensions: int = 768,
    send_dimensions: bool | None = None,
    extra_headers: dict[str, str] | None = None,
) -> GeminiEmbeddingAdapter:
    return GeminiEmbeddingAdapter(
        {
            "api_key": "gemini-test-key",
            "base_url": base_url,
            "model": model,
            "dimensions": dimensions,
            "send_dimensions": send_dimensions,
            "request_timeout": 5,
            "extra_headers": extra_headers or {},
        }
    )


@pytest.mark.asyncio
async def test_gemini2_native_formats_retrieval_query_and_output_dimension(
    capturing_httpx: _CapturingTransport,
) -> None:
    response = await _adapter().embed(
        EmbeddingRequest(
            texts=["현재완료와 과거시제는 어떻게 달라?"],
            model="gemini-embedding-2",
            dimensions=768,
            input_type="search_query",
        )
    )

    captured = capturing_httpx.requests[-1]
    assert captured["url"] == NATIVE_GEMINI2_ENDPOINT
    assert captured["headers"]["x-goog-api-key"] == "gemini-test-key"
    assert "authorization" not in captured["headers"]
    assert captured["json"] == {
        "requests": [
            {
                "model": "models/gemini-embedding-2",
                "content": {
                    "parts": [
                        {
                            "text": (
                                "task: search result | query: 현재완료와 과거시제는 어떻게 달라?"
                            )
                        }
                    ]
                },
                "outputDimensionality": 768,
            }
        ]
    }
    assert response.dimensions == 768


@pytest.mark.asyncio
async def test_gemini2_native_formats_retrieval_documents(
    capturing_httpx: _CapturingTransport,
) -> None:
    await _adapter().embed(
        EmbeddingRequest(
            texts=[
                "The present perfect connects a past event to the present.",
                "The simple past describes a completed event in the past.",
            ],
            model="gemini-embedding-2",
            dimensions=768,
            input_type="search_document",
        )
    )

    requests = capturing_httpx.requests[-1]["json"]["requests"]
    assert [item["content"]["parts"][0]["text"] for item in requests] == [
        "title: none | text: The present perfect connects a past event to the present.",
        "title: none | text: The simple past describes a completed event in the past.",
    ]


@pytest.mark.asyncio
async def test_gemini001_native_maps_retrieval_role_to_task_type(
    capturing_httpx: _CapturingTransport,
) -> None:
    await _adapter(
        model="gemini-embedding-001",
        base_url=NATIVE_GEMINI001_ENDPOINT,
    ).embed(
        EmbeddingRequest(
            texts=["legacy document"],
            model="gemini-embedding-001",
            dimensions=768,
            input_type="search_document",
        )
    )

    native_request = capturing_httpx.requests[-1]["json"]["requests"][0]
    assert native_request["content"] == {"parts": [{"text": "legacy document"}]}
    assert native_request["taskType"] == "RETRIEVAL_DOCUMENT"
    assert native_request["outputDimensionality"] == 768


@pytest.mark.asyncio
async def test_saved_gemini001_openai_compatible_endpoint_still_works(
    capturing_httpx: _CapturingTransport,
) -> None:
    await _adapter(
        model="gemini-embedding-001",
        base_url=LEGACY_OPENAI_ENDPOINT,
    ).embed(
        EmbeddingRequest(
            texts=["legacy document"],
            model="gemini-embedding-001",
            dimensions=768,
            input_type="search_document",
        )
    )

    captured = capturing_httpx.requests[-1]
    assert captured["json"]["input"] == ["legacy document"]
    assert captured["headers"]["authorization"] == "Bearer gemini-test-key"
    assert "dimensions" not in captured["json"]


@pytest.mark.asyncio
async def test_explicit_gemini2_openai_compatible_endpoint_remains_available(
    capturing_httpx: _CapturingTransport,
) -> None:
    await _adapter(base_url=LEGACY_OPENAI_ENDPOINT).embed(
        EmbeddingRequest(
            texts=["query"],
            model="gemini-embedding-2",
            dimensions=768,
            input_type="search_query",
        )
    )

    captured = capturing_httpx.requests[-1]
    assert captured["json"]["input"] == ["task: search result | query: query"]
    assert "dimensions" not in captured["json"]
    assert captured["headers"]["authorization"] == "Bearer gemini-test-key"


@pytest.mark.asyncio
async def test_native_endpoint_model_must_match_selected_model() -> None:
    adapter = _adapter(model="gemini-embedding-001")

    with pytest.raises(ValueError, match="endpoint model .* does not match"):
        await adapter.embed(EmbeddingRequest(texts=["query"], model="gemini-embedding-001"))


@pytest.mark.asyncio
async def test_native_dimension_can_be_explicitly_omitted(
    capturing_httpx: _CapturingTransport,
) -> None:
    await _adapter(send_dimensions=False).embed(
        EmbeddingRequest(
            texts=["query"],
            model="gemini-embedding-2",
            dimensions=768,
        )
    )

    native_request = capturing_httpx.requests[-1]["json"]["requests"][0]
    assert "outputDimensionality" not in native_request


@pytest.mark.asyncio
async def test_custom_native_gateway_keeps_bearer_auth_compatibility(
    capturing_httpx: _CapturingTransport,
) -> None:
    await _adapter(
        base_url=(
            "https://proxy.example.com/google/v1beta/models/gemini-embedding-2:batchEmbedContents"
        )
    ).embed(EmbeddingRequest(texts=["query"], model="gemini-embedding-2"))

    headers = capturing_httpx.requests[-1]["headers"]
    assert headers["authorization"] == "Bearer gemini-test-key"
    assert "x-goog-api-key" not in headers


@pytest.mark.asyncio
async def test_native_provider_error_redacts_credentials(
    capturing_httpx: _CapturingTransport,
) -> None:
    capturing_httpx.status_code = 400
    capturing_httpx.error_body = "invalid key gemini-test-key url-secret oauth-secret for query"
    adapter = _adapter(
        base_url=f"{NATIVE_GEMINI2_ENDPOINT}?key=url-secret",
        extra_headers={"Authorization": "Bearer oauth-secret"},
    )

    with pytest.raises(EmbeddingProviderError) as caught:
        await adapter.embed(EmbeddingRequest(texts=["query"], model="gemini-embedding-2"))

    rendered = str(caught.value)
    assert "gemini-test-key" not in rendered
    assert "url-secret" not in rendered
    assert "oauth-secret" not in rendered
    assert "for query" not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.asyncio
async def test_native_transport_error_redacts_explicit_auth_header(
    capturing_httpx: _CapturingTransport,
) -> None:
    capturing_httpx.transport_error = httpx.LocalProtocolError(
        "Illegal header value b'Bearer oauth-secret\\nbad'"
    )
    adapter = _adapter(
        extra_headers={"Authorization": "Bearer oauth-secret\nbad"},
    )
    adapter._MAX_RETRIES = 0

    with pytest.raises(EmbeddingProviderError) as caught:
        await adapter.embed(EmbeddingRequest(texts=["private query"], model="gemini-embedding-2"))

    rendered = str(caught.value)
    assert "oauth-secret" not in rendered
    assert "private query" not in rendered
    assert caught.value.__cause__ is None


def test_gemini2_model_info_advertises_matryoshka_dimensions() -> None:
    info = _adapter().get_model_info()

    assert info["provider"] == "gemini"
    assert info["dimensions"] == 3072
    assert 768 in info["supported_dimensions"]
    assert info["supports_variable_dimensions"] is True
    # Was False while the adapter was text-only; Embedding 2 maps text, images,
    # video and audio into one space and the adapter now sends them (#814).
    assert info["multimodal"] is True


# ── Multimodal contents (#814) ──────────────────────────────────────────────
#
# The reporter's scenario: a textbook knowledge base whose image nodes should be
# retrievable by a natural-language query. That needs the parsed image to reach
# the model as an embedding, which the adapter used to refuse outright.

_PNG_DATA_URI = "data:image/png;base64,iVBORw0KGgo="
_INLINE_PNG = {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}}


def _multimodal_request(contents: list[dict[str, Any]], **kwargs: Any) -> EmbeddingRequest:
    return EmbeddingRequest(
        texts=[],
        model="gemini-embedding-2",
        contents=contents,
        **kwargs,
    )


def test_image_content_becomes_an_inline_data_part() -> None:
    payload = _adapter()._native_multimodal_payload(
        _multimodal_request([{"image": _PNG_DATA_URI}]),
        "gemini-embedding-2",
    )

    (request,) = payload["requests"]
    assert request["content"]["parts"] == [_INLINE_PNG]
    assert request["model"] == "models/gemini-embedding-2"


def test_each_content_item_gets_its_own_vector() -> None:
    """One vector per node is what makes an image node independently retrievable."""
    payload = _adapter()._native_multimodal_payload(
        _multimodal_request([{"text": "a number line"}, {"image": _PNG_DATA_URI}]),
        "gemini-embedding-2",
    )

    assert [r["content"]["parts"][0] for r in payload["requests"]] == [
        {"text": "a number line"},
        _INLINE_PNG,
    ]


def test_fusion_folds_every_item_into_one_vector() -> None:
    payload = _adapter()._native_multimodal_payload(
        _multimodal_request(
            [{"text": "caption"}, {"image": _PNG_DATA_URI}],
            enable_fusion=True,
        ),
        "gemini-embedding-2",
    )

    (request,) = payload["requests"]
    assert request["content"]["parts"] == [{"text": "caption"}, _INLINE_PNG]


def test_multimodal_payload_carries_output_dimensionality() -> None:
    payload = _adapter(dimensions=768)._native_multimodal_payload(
        _multimodal_request([{"image": _PNG_DATA_URI}]),
        "gemini-embedding-2",
    )

    assert payload["requests"][0]["outputDimensionality"] == 768


def test_remote_urls_are_refused_with_an_actionable_message() -> None:
    """batchEmbedContents has no remote-URL part, and this path must not fetch."""
    with pytest.raises(ValueError) as caught:
        _adapter()._native_multimodal_payload(
            _multimodal_request([{"image": "https://example.com/x.png"}]),
            "gemini-embedding-2",
        )

    assert "http(s) URL" in str(caught.value)
    assert "data: URI" in str(caught.value)


@pytest.mark.parametrize("value", ["data:image/png;base64,", "data:;base64,abc", "not-a-uri"])
def test_malformed_inline_values_are_refused(value: str) -> None:
    with pytest.raises(ValueError):
        _adapter()._native_multimodal_payload(
            _multimodal_request([{"image": value}]),
            "gemini-embedding-2",
        )


def test_unknown_content_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="content type 'hologram'"):
        _adapter()._native_multimodal_payload(
            _multimodal_request([{"hologram": _PNG_DATA_URI}]),
            "gemini-embedding-2",
        )


@pytest.mark.asyncio
async def test_text_only_model_refuses_contents_naming_the_alternative() -> None:
    adapter = _adapter(model="gemini-embedding-001", base_url=NATIVE_GEMINI001_ENDPOINT)

    with pytest.raises(ValueError) as caught:
        await adapter._embed_native(
            EmbeddingRequest(
                texts=[],
                model="gemini-embedding-001",
                contents=[{"image": _PNG_DATA_URI}],
            ),
            "gemini-embedding-001",
        )

    assert "text-only" in str(caught.value)
    assert "gemini-embedding-2" in str(caught.value)


@pytest.mark.asyncio
async def test_multimodal_contents_reach_the_provider(
    capturing_httpx: _CapturingTransport,
) -> None:
    """End to end: the image survives into the posted body, one vector per item."""
    response = await _adapter().embed(
        _multimodal_request([{"text": "a number line"}, {"image": _PNG_DATA_URI}])
    )

    posted = capturing_httpx.requests[-1]["json"]["requests"]
    assert posted[1]["content"]["parts"] == [_INLINE_PNG]
    assert len(response.embeddings) == 2


def test_text_only_path_is_unchanged_by_the_multimodal_addition() -> None:
    """No `contents` must produce byte-identical requests to before."""
    payload = _adapter()._native_payload(
        EmbeddingRequest(
            texts=["hello"],
            model="gemini-embedding-2",
            input_type="search_document",
        ),
        "gemini-embedding-2",
    )

    (request,) = payload["requests"]
    assert request["content"]["parts"] == [{"text": "title: none | text: hello"}]
    assert "taskType" not in request
