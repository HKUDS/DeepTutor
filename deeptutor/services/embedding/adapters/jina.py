"""Jina AI embedding adapter with task-aware embeddings and late chunking."""

import logging
from typing import Any, Dict

import httpx

from deeptutor.services.llm.openai_http_client import disable_ssl_verify_enabled

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class JinaEmbeddingAdapter(BaseEmbeddingAdapter):
    MODELS_INFO = {
        "jina-embeddings-v3": {
            "default": 1024,
            "dimensions": [32, 64, 128, 256, 512, 768, 1024],
            "multimodal": False,
        },
        "jina-embeddings-v4": {
            "default": 1024,
            "dimensions": [32, 64, 128, 256, 512, 768, 1024],
            "multimodal": True,
        },
    }

    INPUT_TYPE_TO_TASK = {
        "search_document": "retrieval.passage",
        "search_query": "retrieval.query",
        "classification": "classification",
        "clustering": "separation",
        "text-matching": "text-matching",
    }

    def _should_send_dimensions(self, model_name: str | None, dim: int) -> bool:
        """Decide whether to attach `dimensions` (Matryoshka truncation)."""
        if self.send_dimensions is True:
            return True
        if self.send_dimensions is False:
            return False
        info = self.MODELS_INFO.get(model_name or "", {})
        supported = info.get("dimensions") if isinstance(info, dict) else None
        if isinstance(supported, list) and dim in supported:
            return True
        if isinstance(supported, list):
            logger.warning(
                f"Jina model '{model_name}' supports dims {supported} but {dim} requested; "
                "dropping `dimensions` from payload."
            )
        return False

    def _supports_multimodal(self, model_name: str | None) -> bool:
        info = self.MODELS_INFO.get(model_name or "")
        return bool(isinstance(info, dict) and info.get("multimodal", False))

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update({str(k): str(v) for k, v in self.extra_headers.items()})

        # Jina v4 accepts mixed `["text", "https://image.url", "data:..."]`
        # arrays in `input`; v3 is text-only. Treat `contents` as advisory:
        # if set, flatten each {"text"|"image"|"video": value} to its value.
        if request.contents:
            if not self._supports_multimodal(request.model or self.model):
                raise ValueError(
                    f"Jina model '{request.model or self.model}' does not support "
                    "multimodal `contents`."
                )
            input_payload = [
                next(iter(item.values())) for item in request.contents if isinstance(item, dict)
            ]
        else:
            input_payload = request.texts

        payload = {
            "input": input_payload,
            "model": request.model or self.model,
        }

        # `dimensions` opt-in: tri-state send_dimensions wins; otherwise only
        # send when the configured model is in MODELS_INFO and exposes a
        # supported list (Matryoshka). Avoids HTTP 400 on models that reject
        # the param.
        dim_value = request.dimensions or self.dimensions
        if dim_value and self._should_send_dimensions(request.model or self.model, dim_value):
            payload["dimensions"] = dim_value

        if request.input_type:
            task = self.INPUT_TYPE_TO_TASK.get(request.input_type, request.input_type)
            payload["task"] = task
            logger.debug(f"Using Jina task: {task}")

        if request.normalized is not None:
            payload["normalized"] = request.normalized

        if request.late_chunking:
            payload["late_chunking"] = True

        url = self.base_url

        logger.debug(f"Sending embedding request to {url} with {len(request.texts)} texts")

        async with httpx.AsyncClient(
            timeout=self.request_timeout, verify=not disable_ssl_verify_enabled()
        ) as client:
            response = await client.post(url, json=payload, headers=headers)

            if response.status_code >= 400:
                logger.error(f"HTTP {response.status_code} response body: {response.text}")

            response.raise_for_status()
            data = response.json()

        embeddings = [item["embedding"] for item in data["data"]]
        actual_dims = len(embeddings[0]) if embeddings else 0

        logger.info(
            f"Successfully generated {len(embeddings)} embeddings "
            f"(model: {data['model']}, dimensions: {actual_dims})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=data["model"],
            dimensions=actual_dims,
            usage=data.get("usage", {}),
        )

    def get_model_info(self) -> Dict[str, Any]:
        model_info = self.MODELS_INFO.get(self.model, self.dimensions)

        if isinstance(model_info, dict):
            return {
                "model": self.model,
                "dimensions": model_info.get("default", self.dimensions),
                "supported_dimensions": model_info.get("dimensions", []),
                "supports_variable_dimensions": True,
                "multimodal": bool(model_info.get("multimodal", False)),
                "provider": "jina",
            }
        else:
            return {
                "model": self.model,
                "dimensions": model_info or self.dimensions,
                "supports_variable_dimensions": False,
                "multimodal": False,
                "provider": "jina",
            }
