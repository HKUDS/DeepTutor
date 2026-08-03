"""Tests for the DashScope (Aliyun) MultiModalEmbedding adapter."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.dashscope_native import (
    DashScopeMultiModalEmbeddingAdapter,
)


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        output: dict | None = None,
        usage: dict | None = None,
        code: str = "",
        message: str = "",
        request_id: str = "req-1",
    ) -> None:
        self.status_code = status_code
        self.output = output if output is not None else {"embeddings": []}
        self.usage = usage or {}
        self.code = code
        self.message = message
        self.request_id = request_id


def _install_fake_sdk(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> dict[str, Any]:
    """Stub both DashScope embedding surfaces and record which one is called."""
    captured: dict[str, Any] = {}

    def _surface(name: str):
        def fake_call(*, api_key: str, model: str, input: Any, **kwargs: Any) -> _FakeResponse:  # noqa: A002
            captured.update(
                surface=name,
                api_key=api_key,
                model=model,
                input=input,
                kwargs=kwargs,
            )
            return response

        return fake_call

    fake_module = types.SimpleNamespace(
        MultiModalEmbedding=types.SimpleNamespace(call=_surface("multimodal")),
        TextEmbedding=types.SimpleNamespace(call=_surface("text")),
    )
    monkeypatch.setitem(sys.modules, "dashscope", fake_module)
    return captured


@pytest.mark.asyncio
async def test_text_only_translates_texts_to_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        output={"embeddings": [{"index": 0, "embedding": [0.1, 0.2, 0.3], "type": "vl"}]},
    )
    captured = _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
            "model": "qwen3-vl-embedding",
            "dimensions": 1024,
            "request_timeout": 5,
        }
    )
    resp = await adapter.embed(
        EmbeddingRequest(texts=["hello", "world"], model="qwen3-vl-embedding")
    )

    # SDK takes a flat list — it wraps as {"contents": ...} internally.
    assert captured["surface"] == "multimodal"
    assert captured["input"] == [{"text": "hello"}, {"text": "world"}]
    assert captured["model"] == "qwen3-vl-embedding"
    assert captured["api_key"] == "sk-dashscope"
    assert captured["kwargs"].get("dimension") == 1024
    assert "enable_fusion" not in captured["kwargs"]
    assert resp.embeddings == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_text_model_uses_text_embedding_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression for issue #660: a text model (text-embedding-v4) must go to the
    # TextEmbedding surface with a flat string list, NOT the multimodal endpoint
    # (which returns HTTP 400 "url error").
    response = _FakeResponse(
        output={"embeddings": [{"text_index": 0, "embedding": [0.1, 0.2]}]},
    )
    captured = _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope",
            "base_url": "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
            "model": "text-embedding-v4",
            "dimensions": 1024,
            "request_timeout": 5,
        }
    )
    resp = await adapter.embed(
        EmbeddingRequest(texts=["hello", "world"], model="text-embedding-v4")
    )

    assert captured["surface"] == "text"
    assert captured["input"] == ["hello", "world"]  # flat strings, not {"text": ...}
    assert captured["model"] == "text-embedding-v4"
    assert captured["kwargs"].get("dimension") == 1024
    assert "enable_fusion" not in captured["kwargs"]
    assert resp.embeddings == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_multimodal_contents_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        output={"embeddings": [{"index": 0, "embedding": [0.4, 0.5], "type": "fusion"}]},
    )
    captured = _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk-dashscope",
            "base_url": "https://dashscope.aliyuncs.com/...",
            "model": "qwen3-vl-embedding",
            "dimensions": 0,
            "request_timeout": 5,
        }
    )
    contents = [{"text": "a slide"}, {"image": "https://example.com/img.png"}]
    resp = await adapter.embed(
        EmbeddingRequest(
            texts=[],
            model="qwen3-vl-embedding",
            contents=contents,
            enable_fusion=True,
        )
    )
    # SDK takes a flat list — it wraps as {"contents": ...} internally.
    assert captured["input"] == contents
    assert captured["kwargs"].get("enable_fusion") is True
    assert resp.embeddings == [[0.4, 0.5]]


@pytest.mark.asyncio
async def test_failure_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        status_code=400,
        output={"embeddings": []},
        code="InvalidParameter",
        message="dimension out of range",
    )
    _install_fake_sdk(monkeypatch, response)

    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk",
            "base_url": "https://dashscope.aliyuncs.com/...",
            "model": "qwen3-vl-embedding",
            "request_timeout": 5,
        }
    )
    with pytest.raises(RuntimeError) as ei:
        await adapter.embed(EmbeddingRequest(texts=["x"], model="qwen3-vl-embedding"))
    assert "InvalidParameter" in str(ei.value)


def test_get_model_info_reports_multimodal_capability() -> None:
    adapter = DashScopeMultiModalEmbeddingAdapter(
        {
            "api_key": "sk",
            "base_url": "https://...",
            "model": "qwen3-vl-embedding",
        }
    )
    info = adapter.get_model_info()
    assert info["multimodal"] is True
    assert info["provider"] == "aliyun"
    assert 2560 in info["supported_dimensions"]


@pytest.mark.parametrize(
    ("model", "multimodal", "endpoint_tail"),
    [
        ("text-embedding-v4", False, "/text-embedding/text-embedding"),
        ("text-embedding-v3", False, "/text-embedding/text-embedding"),
        ("some-unknown-model", False, "/text-embedding/text-embedding"),
        ("qwen3-vl-embedding", True, "/multimodal-embedding/multimodal-embedding"),
        ("multimodal-embedding-v1", True, "/multimodal-embedding/multimodal-embedding"),
    ],
)
def test_dashscope_endpoint_routing(model: str, multimodal: bool, endpoint_tail: str) -> None:
    # Issue #660: the single source of truth that decides text vs multimodal
    # DashScope endpoint per model.
    from deeptutor.services.config.embedding_endpoint import (
        dashscope_embedding_endpoint,
        is_dashscope_multimodal_embedding_model,
    )

    assert is_dashscope_multimodal_embedding_model(model) is multimodal
    assert dashscope_embedding_endpoint(model).endswith(endpoint_tail)
