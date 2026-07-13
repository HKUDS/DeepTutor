"""Verify EmbeddingRequest carries the multimodal contents/enable_fusion fields
and that adapters route based on them."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.cohere import CohereEmbeddingAdapter
from deeptutor.services.embedding.adapters.jina import JinaEmbeddingAdapter
from deeptutor.services.embedding.adapters.ollama import OllamaEmbeddingAdapter
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)


def test_request_dataclass_accepts_contents_field() -> None:
    req = EmbeddingRequest(
        texts=[],
        model="qwen3-vl-embedding",
        contents=[{"text": "hi"}, {"image": "https://x.png"}],
        enable_fusion=True,
    )
    assert req.contents and req.contents[0] == {"text": "hi"}
    assert req.enable_fusion is True


@pytest.mark.asyncio
async def test_openai_compat_passes_contents_as_input(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["json"] = kwargs.get("json")
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=200,
            json={"data": [{"embedding": [0.1, 0.2]}], "model": "Qwen/Qwen3-VL-Embedding-8B"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    adapter = OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-sf",
            "base_url": "https://api.siliconflow.cn/v1/embeddings",
            "model": "Qwen/Qwen3-VL-Embedding-8B",
            "request_timeout": 5,
        }
    )
    contents = [{"text": "caption"}, {"image": "https://x.png"}]
    await adapter.embed(
        EmbeddingRequest(texts=[], model="Qwen/Qwen3-VL-Embedding-8B", contents=contents)
    )
    assert captured["json"]["input"] == contents


@pytest.mark.asyncio
async def test_openai_compat_rejects_contents_for_text_embedding_model() -> None:
    adapter = OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk",
            "base_url": "https://api.openai.com/v1/embeddings",
            "model": "text-embedding-3-small",
            "request_timeout": 5,
        }
    )

    with pytest.raises(ValueError, match="does not support multimodal"):
        await adapter.embed(
            EmbeddingRequest(
                texts=[],
                model="text-embedding-3-small",
                contents=[{"image": "data:image/png;base64,XXX"}],
            )
        )


@pytest.mark.asyncio
async def test_ollama_rejects_multimodal_contents() -> None:
    adapter = OllamaEmbeddingAdapter(
        {
            "api_key": "",
            "base_url": "http://localhost:11434/api/embed",
            "model": "nomic-embed-text",
            "request_timeout": 5,
        }
    )
    with pytest.raises(ValueError, match="does not support multimodal"):
        await adapter.embed(
            EmbeddingRequest(
                texts=[],
                model="nomic-embed-text",
                contents=[{"image": "https://x.png"}],
            )
        )


@pytest.mark.asyncio
async def test_jina_v3_rejects_multimodal_contents() -> None:
    adapter = JinaEmbeddingAdapter(
        {
            "api_key": "jina-test",
            "base_url": "https://api.jina.ai/v1/embeddings",
            "model": "jina-embeddings-v3",
            "request_timeout": 5,
        }
    )
    with pytest.raises(ValueError, match="does not support multimodal"):
        await adapter.embed(
            EmbeddingRequest(
                texts=[],
                model="jina-embeddings-v3",
                contents=[{"image": "data:image/png;base64,XXX"}],
            )
        )


@pytest.mark.asyncio
async def test_cohere_v2_translates_contents_to_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["json"] = kwargs.get("json")
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=200,
            json={"embeddings": {"float": [[0.1, 0.2, 0.3]]}, "model": "embed-v4.0"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    adapter = CohereEmbeddingAdapter(
        {
            "api_key": "co-test",
            "base_url": "https://api.cohere.com/v2/embed",
            "model": "embed-v4.0",
            "api_version": "v2",
            "dimensions": 1024,
            "request_timeout": 5,
        }
    )
    contents = [{"text": "hello"}, {"image": "data:image/png;base64,XXX"}]
    await adapter.embed(EmbeddingRequest(texts=[], model="embed-v4.0", contents=contents))

    inputs = captured["json"]["inputs"]
    assert inputs[0] == {"content": [{"type": "text", "text": "hello"}]}
    assert inputs[1] == {
        "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,XXX"}}]
    }


def test_model_info_reports_multimodal_at_model_level() -> None:
    assert (
        CohereEmbeddingAdapter(
            {
                "api_key": "co-test",
                "base_url": "https://api.cohere.com/v2/embed",
                "model": "embed-v4.0",
            }
        ).get_model_info()["multimodal"]
        is True
    )
    assert (
        CohereEmbeddingAdapter(
            {
                "api_key": "co-test",
                "base_url": "https://api.cohere.com/v2/embed",
                "model": "embed-multilingual-v3.0",
            }
        ).get_model_info()["multimodal"]
        is False
    )
    assert (
        JinaEmbeddingAdapter(
            {
                "api_key": "jina-test",
                "base_url": "https://api.jina.ai/v1/embeddings",
                "model": "jina-embeddings-v4",
            }
        ).get_model_info()["multimodal"]
        is True
    )
    assert (
        OpenAICompatibleEmbeddingAdapter(
            {
                "api_key": "sk-sf",
                "base_url": "https://api.siliconflow.cn/v1/embeddings",
                "model": "Qwen/Qwen3-Embedding-8B",
            }
        ).get_model_info()["multimodal"]
        is False
    )
