# -*- coding: utf-8 -*-
"""Jina AI embedding adapter with task-aware embeddings and late chunking."""

import logging
from typing import Any, Dict

import httpx

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class JinaEmbeddingAdapter(BaseEmbeddingAdapter):
    MODELS_INFO = {
        "jina-embeddings-v3": {"default": 1024, "dimensions": [32, 64, 128, 256, 512, 768, 1024]},
        "jina-embeddings-v4": {"default": 1024, "dimensions": [32, 64, 128, 256, 512, 768, 1024]},
    }

    INPUT_TYPE_TO_TASK = {
        "search_document": "retrieval.passage",
        "search_query": "retrieval.query",
        "classification": "classification",
        "clustering": "separation",
        "text-matching": "text-matching",
    }

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "input": request.texts,
            "model": request.model or self.model,
        }

        if request.dimensions:
            payload["dimensions"] = request.dimensions
        elif self.dimensions:
            payload["dimensions"] = self.dimensions

        if request.input_type:
            task = self.INPUT_TYPE_TO_TASK.get(request.input_type, request.input_type)
            payload["task"] = task
            logger.debug(f"Using Jina task: {task}")

        if request.normalized is not None:
            payload["normalized"] = request.normalized

        if request.late_chunking:
            payload["late_chunking"] = True

        url = f"{self.base_url}/embeddings"

        logger.debug(f"Sending embedding request to {url} with {len(request.texts)} texts")

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
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
                "provider": "jina",
            }
        else:
            return {
                "model": self.model,
                "dimensions": model_info or self.dimensions,
                "supports_variable_dimensions": False,
                "provider": "jina",
            }
