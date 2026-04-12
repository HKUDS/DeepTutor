"""OpenAI-compatible embedding adapter for OpenAI, Azure, HuggingFace, LM Studio, etc."""

import json
import logging
from typing import Any, Dict

import httpx

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbeddingAdapter(BaseEmbeddingAdapter):
    MODELS_INFO = {
        "text-embedding-3-large": {"default": 3072, "dimensions": [256, 512, 1024, 3072]},
        "text-embedding-3-small": {"default": 1536, "dimensions": [512, 1536]},
        "text-embedding-ada-002": 1536,
    }

    @staticmethod
    def _extract_embeddings_from_response(data: Any) -> list[list[float]]:
        """
        Extract embeddings from different OpenAI-compatible response schemas.

        Supported shapes include:
        - {"data": [{"embedding": [...]}, ...]}
        - {"embeddings": [[...], ...]}
        - {"result": {"data": [{"embedding": [...]}, ...]}}
        - {"output": {"embeddings": [[...], ...]}}
        """
        if not isinstance(data, dict):
            raise ValueError(f"Embedding response is not a JSON object: type={type(data).__name__}")

        # Some providers return HTTP 200 with {"error": ...} payload.
        if "error" in data:
            err = data.get("error")
            if isinstance(err, dict):
                msg = (
                    err.get("message")
                    or err.get("msg")
                    or err.get("detail")
                    or json.dumps(err, ensure_ascii=False)
                )
                code = err.get("code")
                etype = err.get("type")
                raise ValueError(
                    f"Embedding provider returned error payload: "
                    f"message={msg}, code={code}, type={etype}"
                )
            raise ValueError(f"Embedding provider returned error payload: {err}")

        candidates = []
        # Standard OpenAI schema
        if isinstance(data.get("data"), list):
            candidates.append(data["data"])
        # Common proxy schema
        if isinstance(data.get("embeddings"), list):
            candidates.append(data["embeddings"])
        # Nested result/output variants
        result = data.get("result")
        if isinstance(result, dict):
            if isinstance(result.get("data"), list):
                candidates.append(result["data"])
            if isinstance(result.get("embeddings"), list):
                candidates.append(result["embeddings"])
        output = data.get("output")
        if isinstance(output, dict):
            if isinstance(output.get("data"), list):
                candidates.append(output["data"])
            if isinstance(output.get("embeddings"), list):
                candidates.append(output["embeddings"])

        for c in candidates:
            if not c:
                continue
            first = c[0]
            # list of {"embedding":[...]}
            if isinstance(first, dict) and "embedding" in first:
                return [item.get("embedding", []) for item in c if isinstance(item, dict)]
            # list of vectors [[...], ...]
            if isinstance(first, list):
                return [item for item in c if isinstance(item, list)]

        keys = sorted(list(data.keys()))
        raise ValueError(
            "Cannot parse embeddings from response JSON. "
            f"Top-level keys={keys}, expected one of: data/embeddings/result/output."
        )

    _MAX_RETRIES = 2
    _RETRY_BACKOFF = 1.0

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        import asyncio

        headers = {"Content-Type": "application/json"}
        if self.api_version:
            if self.api_key:
                headers["api-key"] = self.api_key
        elif self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update({str(k): str(v) for k, v in self.extra_headers.items()})

        payload = {
            "input": request.texts,
            "model": request.model or self.model,
            "encoding_format": request.encoding_format or "float",
        }

        if request.dimensions or self.dimensions:
            payload["dimensions"] = request.dimensions or self.dimensions

        base = self.base_url.rstrip('/')
        if base.endswith('/embeddings'):
            url = base
        else:
            url = f"{base}/embeddings"
        if self.api_version:
            if "?" not in url:
                url += f"?api-version={self.api_version}"
            else:
                url += f"&api-version={self.api_version}"

        logger.debug(f"Sending embedding request to {url} with {len(request.texts)} texts")

        timeout = httpx.Timeout(
            connect=10.0,
            read=max(self.request_timeout, 60),
            write=10.0,
            pool=10.0,
        )
        last_exc: Exception | None = None
        for attempt in range(1 + self._MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code >= 400:
                        logger.error(f"HTTP {response.status_code} response body: {response.text}")

                    response.raise_for_status()
                    data = response.json()
                break
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    wait = self._RETRY_BACKOFF * (attempt + 1)
                    logger.warning(
                        f"Embedding request timeout (attempt {attempt + 1}/{1 + self._MAX_RETRIES}), "
                        f"retrying in {wait:.0f}s..."
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        f"Embedding request failed after {1 + self._MAX_RETRIES} attempts: {exc}"
                    )
                    raise

        embeddings = self._extract_embeddings_from_response(data)
        if not embeddings:
            raise ValueError("Embedding response parsed successfully but no vectors were found.")

        actual_dims = len(embeddings[0]) if embeddings else 0
        expected_dims = request.dimensions or self.dimensions
        model_name = data.get("model") if isinstance(data, dict) else None
        if not model_name:
            model_name = request.model or self.model

        if expected_dims and actual_dims != expected_dims:
            logger.warning(
                f"Dimension mismatch: expected {expected_dims}, got {actual_dims}. "
                f"Model '{model_name}' may not support custom dimensions."
            )

        logger.info(
            f"Successfully generated {len(embeddings)} embeddings "
            f"(model: {model_name}, dimensions: {actual_dims})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=model_name,
            dimensions=actual_dims,
            usage=data.get("usage", {}) if isinstance(data, dict) else {},
        )

    def get_model_info(self) -> Dict[str, Any]:
        model_info = self.MODELS_INFO.get(self.model, self.dimensions)

        if isinstance(model_info, dict):
            return {
                "model": self.model,
                "dimensions": model_info.get("default", self.dimensions),
                "supported_dimensions": model_info.get("dimensions", []),
                "supports_variable_dimensions": len(model_info.get("dimensions", [])) > 1,
                "provider": "openai_compatible",
            }
        else:
            return {
                "model": self.model,
                "dimensions": model_info or self.dimensions,
                "supports_variable_dimensions": False,
                "provider": "openai_compatible",
            }
