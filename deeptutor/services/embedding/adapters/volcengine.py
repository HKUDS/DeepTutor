"""Volcengine Ark (火山方舟) embedding adapter (text + multimodal).

Ark serves text and multimodal embeddings from two endpoints:

* ``/api/v3/embeddings`` — OpenAI-compatible shape for text models
  (``doubao-embedding-text-*``, ``doubao-embedding-large-text-*``): body is
  ``{"model": ..., "input": [str, ...]}`` and the response mirrors OpenAI
  (``data`` is a list of ``{"embedding": [...]}`` entries).
* ``/api/v3/embeddings/multimodal`` — native shape for vision models
  (``doubao-embedding-vision-*``): ``input`` is a list of
  ``{"type": "text"|"image_url", ...}`` items and the response wraps a SINGLE
  fused vector in a dict: ``data = {"embedding": [...], "object": "embedding"}``.
  Vision models require at least one image in the input; a text-only request
  is rejected by the service with an internal error.

The endpoint is derived from the model id (same pattern as the DashScope
adapter). Multimodal requests embed one item at a time because the service
fuses all input items into a single vector, while DeepTutor's
``embed_contents`` contract expects one vector per item.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import httpx

from deeptutor.services.config.embedding_endpoint import (
    is_volcengine_vision_embedding_model,
    volcengine_embedding_dim,
    volcengine_embedding_endpoint,
)
from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled

from .base import BaseEmbeddingAdapter, EmbeddingProviderError, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class VolcengineEmbeddingAdapter(BaseEmbeddingAdapter):
    """Adapter for Volcengine Ark (Doubao) text + multimodal embedding."""

    _MAX_RETRIES = 4
    _RATE_LIMIT_BACKOFF = 2.0

    @staticmethod
    def _is_vision(model_name: str | None) -> bool:
        return is_volcengine_vision_embedding_model(model_name)

    def _resolve_url(self, model_name: str) -> str:
        """Use the configured URL verbatim when set, else route by model."""
        if self.base_url:
            return self.base_url
        return volcengine_embedding_endpoint(model_name)

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        headers.update({str(k): str(v) for k, v in self.extra_headers.items()})
        return headers

    @staticmethod
    def _to_ark_input_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """Map a DeepTutor content item to Ark's multimodal input shape."""
        if not isinstance(item, dict):
            raise ValueError(f"Volcengine multimodal content item must be a dict, got {type(item).__name__}.")
        if "text" in item:
            return {"type": "text", "text": str(item["text"])}
        if "image" in item:
            return {"type": "image_url", "image_url": {"url": str(item["image"])}}
        if "video" in item:
            # Ark vision embedding accepts video via the image_url slot with a
            # video data URL / public URL; forward it so providers that accept
            # it keep working instead of silently dropping the item.
            return {"type": "image_url", "image_url": {"url": str(item["video"])}}
        raise ValueError(
            "Volcengine multimodal content items must have 'text', 'image' or 'video', "
            f"got keys={sorted(item.keys())}."
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model_name = request.model or self.model
        if not model_name:
            raise ValueError("No embedding model configured for Volcengine Ark.")
        if self._is_vision(model_name):
            return await self._embed_multimodal(request, model_name)
        return await self._embed_text(request, model_name)

    # ---- multimodal (vision models) -------------------------------------

    async def _embed_multimodal(
        self, request: EmbeddingRequest, model_name: str
    ) -> EmbeddingResponse:
        # Vision models serve BOTH text and image inputs via the multimodal
        # endpoint: every input item becomes {"type": "text"|"image_url"|...}.
        # Plain-text embedding works (OpenViking uses exactly this model for
        # text memories); the endpoint may occasionally throw a transient
        # InternalServiceError, which `_post` retries.
        items: List[Dict[str, Any]] = []
        if request.contents:
            items = [item for item in request.contents if isinstance(item, dict)]
        elif request.texts:
            items = [{"text": text} for text in request.texts]

        if not items:
            raise ValueError("Volcengine multimodal embedding needs at least one input item.")

        url = self._resolve_url(model_name)
        headers = self._build_headers()
        timeout = httpx.Timeout(connect=10.0, read=max(self.request_timeout, 60), write=10.0, pool=10.0)

        # The service FUSES every input item into ONE vector, so each item is
        # embedded in its own request to keep the one-vector-per-item contract
        # DeepTutor expects (one vector per text / per content item).
        embeddings: List[List[float]] = []
        usage: Dict[str, Any] = {}
        dim_value = request.dimensions or self.dimensions
        for index, item in enumerate(items, 1):
            payload: Dict[str, Any] = {
                "model": model_name,
                "input": [self._to_ark_input_item(item)],
            }
            # Ark supports a `dimensions` knob on the multimodal endpoint
            # (e.g. 1024 or 2048); pass it through when configured.
            if dim_value:
                payload["dimensions"] = int(dim_value)
            logger.debug(
                f"Volcengine multimodal embedding item {index}/{len(items)} "
                f"(model={model_name}, type={payload['input'][0]['type']})"
            )
            data = await self._post(url, payload, headers, timeout, model_name)
            vector = self._extract_single_vector(data, model_name, url)
            embeddings.append(vector)
            if isinstance(data.get("usage"), dict):
                usage = data["usage"]

        actual_dims = len(embeddings[0]) if embeddings else 0
        logger.info(
            f"Generated {len(embeddings)} Volcengine embeddings "
            f"(model: {model_name}, dimensions: {actual_dims})"
        )
        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_name,
            dimensions=actual_dims,
            usage=usage,
        )

    # ---- text (OpenAI-compatible surface) --------------------------------

    async def _embed_text(self, request: EmbeddingRequest, model_name: str) -> EmbeddingResponse:
        texts = list(request.texts) if request.texts else []
        if request.contents:
            # A text model receiving multimodal items: keep only the text ones.
            texts = [
                str(item["text"])
                for item in (request.contents or [])
                if isinstance(item, dict) and item.get("text")
            ]
        if not texts:
            raise ValueError("Volcengine text embedding needs at least one text input.")

        url = self._resolve_url(model_name)
        headers = self._build_headers()
        timeout = httpx.Timeout(connect=10.0, read=max(self.request_timeout, 60), write=10.0, pool=10.0)

        payload: Dict[str, Any] = {"model": model_name, "input": texts}
        data = await self._post(url, payload, headers, timeout, model_name)

        # OpenAI-compatible: data is a list of {"embedding": [...]}.
        raw = data.get("data")
        embeddings: List[List[float]] = []
        if isinstance(raw, list):
            for entry in raw:
                vec = entry.get("embedding") if isinstance(entry, dict) else None
                if vec is None:
                    continue
                embeddings.append(list(vec))
        elif isinstance(raw, dict) and isinstance(raw.get("embedding"), list):
            embeddings.append(list(raw["embedding"]))

        if not embeddings:
            raise EmbeddingProviderError(
                "Volcengine text embedding returned no vectors.",
                model=model_name,
                url=url,
                provider="volcengine",
                body=str(data)[:300],
            )

        actual_dims = len(embeddings[0])
        logger.info(
            f"Generated {len(embeddings)} Volcengine text embeddings "
            f"(model: {model_name}, dimensions: {actual_dims})"
        )
        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_name,
            dimensions=actual_dims,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else {},
        )

    # ---- shared HTTP / parsing ------------------------------------------

    @staticmethod
    def _extract_single_vector(data: Dict[str, Any], model_name: str, url: str) -> List[float]:
        """Pull the fused vector out of the multimodal response (data is a dict)."""
        raw = data.get("data")
        if isinstance(raw, dict) and isinstance(raw.get("embedding"), list):
            return list(raw["embedding"])
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            vec = raw[0].get("embedding")
            if isinstance(vec, list):
                return list(vec)
        raise EmbeddingProviderError(
            "Volcengine multimodal embedding response missing `data.embedding`.",
            model=model_name,
            url=url,
            provider="volcengine",
            body=str(data)[:300],
        )

    async def _post(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        timeout: httpx.Timeout,
        model_name: str,
    ) -> Dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1 + self._MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=timeout, verify=not disable_ssl_verify_enabled()
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 429 and attempt < self._MAX_RETRIES:
                    await asyncio.sleep(self._RATE_LIMIT_BACKOFF * attempt)
                    continue
                if response.status_code >= 500 and attempt < self._MAX_RETRIES:
                    # Ark vision embedding occasionally returns a transient
                    # InternalServiceError (500) even for valid requests —
                    # retry with backoff like the 429 path.
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                if response.status_code >= 400:
                    raise EmbeddingProviderError(
                        f"Volcengine embedding request failed: {response.status_code} - {response.text[:500]}",
                        status=response.status_code,
                        body=response.text[:500],
                        model=model_name,
                        url=url,
                        provider="volcengine",
                    )
                data = response.json()
                error = data.get("error") if isinstance(data, dict) else None
                if error:
                    raise EmbeddingProviderError(
                        f"Volcengine embedding API error: {error}",
                        status=response.status_code,
                        body=str(error)[:500],
                        model=model_name,
                        url=url,
                        provider="volcengine",
                    )
                if not isinstance(data, dict):
                    raise EmbeddingProviderError(
                        "Volcengine embedding returned a non-object payload.",
                        model=model_name,
                        url=url,
                        provider="volcengine",
                        body=str(data)[:300],
                    )
                return data
            except EmbeddingProviderError:
                raise
            except Exception as exc:  # network errors etc.
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    await asyncio.sleep(min(2**attempt, 8))
        raise EmbeddingProviderError(
            f"Volcengine embedding request failed after retries: {last_exc}",
            model=model_name,
            url=url,
            provider="volcengine",
        )

    def get_model_info(self) -> Dict[str, Any]:
        model = self.model or ""
        return {
            "model": model,
            "dimensions": self.dimensions or volcengine_embedding_dim(model),
            "supported_dimensions": [],
            "supports_variable_dimensions": False,
            "multimodal": self._is_vision(model),
            "provider": "volcengine",
        }
