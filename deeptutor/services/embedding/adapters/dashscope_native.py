"""Aliyun DashScope embedding adapter (text + multimodal).

Uses the ``dashscope`` Python SDK rather than the OpenAI contract because
DashScope's native API shape does not match it. DashScope splits embeddings
across two surfaces served from different endpoints, and the SDK derives the
endpoint from the model id:

* multimodal models (``qwen3-vl-embedding``, ``multimodal-embedding-v1``) use
  ``dashscope.MultiModalEmbedding.call`` (``input=[{text|image|video}]`` +
  ``parameters={dimension, enable_fusion}``);
* text models (``text-embedding-v1..v4``) use ``dashscope.TextEmbedding.call``
  (``input=[str, ...]``).

Routing a text model through the multimodal call sends it to the multimodal
endpoint and fails with HTTP 400 "url error" (issue #660), so ``embed`` picks
the surface from the model id. Both calls are synchronous, so we run them in a
thread pool to keep the embedding stack non-blocking.
"""

from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from typing import Any, Dict, List

from deeptutor.services.config.embedding_endpoint import (
    is_dashscope_multimodal_embedding_model,
)

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class DashScopeMultiModalEmbeddingAdapter(BaseEmbeddingAdapter):
    """Adapter for Aliyun DashScope (Bailian) text + multimodal embedding."""

    MODELS_INFO = {
        "qwen3-vl-embedding": {
            "default": 2560,
            "dimensions": [256, 512, 768, 1024, 1536, 2048, 2560],
            "multimodal": True,
        },
        "multimodal-embedding-v1": {
            "default": 1536,
            "dimensions": [],
            "multimodal": True,
        },
        "text-embedding-v3": {
            "default": 1024,
            "dimensions": [],
            "multimodal": False,
        },
        "text-embedding-v4": {
            "default": 1024,
            "dimensions": [],
            "multimodal": False,
        },
    }

    def _build_contents(self, request: EmbeddingRequest) -> List[Dict[str, Any]]:
        if request.contents:
            return [item for item in request.contents if isinstance(item, dict)]
        return [{"text": text} for text in request.texts]

    def _build_parameters(self, request: EmbeddingRequest) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        dim_value = request.dimensions or self.dimensions
        if dim_value:
            params["dimension"] = dim_value
        if request.enable_fusion is not None:
            params["enable_fusion"] = bool(request.enable_fusion)
        return params

    def _build_text_inputs(self, request: EmbeddingRequest) -> List[str]:
        """Flatten the request to the plain string list TextEmbedding expects."""
        if request.texts:
            return list(request.texts)
        return [
            item["text"]
            for item in (request.contents or [])
            if isinstance(item, dict) and item.get("text")
        ]

    def _build_text_parameters(self, request: EmbeddingRequest) -> Dict[str, Any]:
        # TextEmbedding takes `dimension` (v3/v4 support it) but has no
        # `enable_fusion` — that is a multimodal-only knob.
        params: Dict[str, Any] = {}
        dim_value = request.dimensions or self.dimensions
        if dim_value:
            params["dimension"] = dim_value
        return params

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model_name = request.model or self.model
        if is_dashscope_multimodal_embedding_model(model_name):
            return await self._embed_multimodal(request, model_name)
        return await self._embed_text(request, model_name)

    async def _embed_multimodal(
        self, request: EmbeddingRequest, model_name: str
    ) -> EmbeddingResponse:
        try:
            from dashscope import MultiModalEmbedding
        except ImportError as exc:
            raise ImportError(
                "dashscope SDK not installed. Run `pip install dashscope` "
                "(or add to your project deps) to enable Aliyun DashScope."
            ) from exc

        contents = self._build_contents(request)
        parameters = self._build_parameters(request)

        logger.debug(
            "Calling dashscope.MultiModalEmbedding.call "
            f"(model={model_name}, items={len(contents)}, params={parameters})"
        )

        # SDK call is sync — run in worker thread to avoid blocking the loop.
        # IMPORTANT: the dashscope SDK takes a flat list for `input`
        # (e.g. ``input=[{"text": "..."}]``) and internally wraps it as
        # ``{"contents": [...]}`` before POSTing to the REST endpoint. Do NOT
        # pass ``{"contents": contents}`` here — that produces a double-wrap
        # and the API responds with HTTP 400 ("Input should be a valid list").
        resp = await asyncio.to_thread(
            MultiModalEmbedding.call,
            api_key=self.api_key,
            model=model_name,
            input=contents,
            **parameters,
        )

        self._raise_on_error(resp, model_name)
        return self._parse_response(resp, model_name, request)

    async def _embed_text(self, request: EmbeddingRequest, model_name: str) -> EmbeddingResponse:
        try:
            from dashscope import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "dashscope SDK not installed. Run `pip install dashscope` "
                "(or add to your project deps) to enable Aliyun DashScope."
            ) from exc

        inputs = self._build_text_inputs(request)
        parameters = self._build_text_parameters(request)

        logger.debug(
            "Calling dashscope.TextEmbedding.call "
            f"(model={model_name}, items={len(inputs)}, params={parameters})"
        )

        # TextEmbedding.call POSTs to the DashScope text-embedding endpoint and
        # accepts a flat list of strings for `input`. Response/usage/error shape
        # matches MultiModalEmbedding, so we reuse the shared parsers below.
        resp = await asyncio.to_thread(
            TextEmbedding.call,
            api_key=self.api_key,
            model=model_name,
            input=inputs,
            **parameters,
        )

        self._raise_on_error(resp, model_name)
        return self._parse_response(resp, model_name, request)

    def _raise_on_error(self, resp: Any, model_name: str) -> None:
        status_code = getattr(resp, "status_code", None)
        if status_code is None or status_code == HTTPStatus.OK:
            return
        code = getattr(resp, "code", "") or ""
        message = getattr(resp, "message", "") or ""
        request_id = getattr(resp, "request_id", "") or ""
        raise RuntimeError(
            f"DashScope MultiModalEmbedding call failed: "
            f"status={status_code}, code={code}, message={message}, "
            f"model={model_name}, request_id={request_id}"
        )

    def _parse_response(
        self, resp: Any, model_name: str, request: EmbeddingRequest
    ) -> EmbeddingResponse:
        output = getattr(resp, "output", None)
        if output is None:
            raise ValueError(
                f"DashScope response missing `output` (request_id={getattr(resp, 'request_id', '')})"
            )

        # `output` is dict-like in the SDK.
        if isinstance(output, dict):
            raw = output.get("embeddings") or []
        else:
            raw = getattr(output, "embeddings", None) or []

        embeddings: List[List[float]] = []
        for item in raw:
            if isinstance(item, dict):
                vec = item.get("embedding")
            else:
                vec = getattr(item, "embedding", None)
            if vec is None:
                continue
            embeddings.append(list(vec))

        if not embeddings:
            raise ValueError(
                "DashScope response parsed successfully but no embedding vectors were returned."
            )

        usage = getattr(resp, "usage", {}) or {}
        if not isinstance(usage, dict):
            usage = {
                k: getattr(usage, k, None)
                for k in ("input_tokens", "output_tokens", "total_tokens")
                if hasattr(usage, k)
            }

        actual_dims = len(embeddings[0]) if embeddings else 0
        logger.info(
            f"Successfully generated {len(embeddings)} DashScope embeddings "
            f"(model: {model_name}, dimensions: {actual_dims}, "
            f"fusion={request.enable_fusion})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_name,
            dimensions=actual_dims,
            usage=usage,
        )

    def get_model_info(self) -> Dict[str, Any]:
        info = self.MODELS_INFO.get(self.model or "", {})
        return {
            "model": self.model,
            "dimensions": info.get("default", self.dimensions),
            "supported_dimensions": info.get("dimensions", []),
            "supports_variable_dimensions": bool(info.get("dimensions")),
            "multimodal": bool(info.get("multimodal", False)),
            "provider": "aliyun",
        }
