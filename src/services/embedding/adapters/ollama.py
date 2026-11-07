# -*- coding: utf-8 -*-
"""Ollama Embedding Adapter for local embeddings."""

import logging
from typing import Any, Dict

import httpx

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class OllamaEmbeddingAdapter(BaseEmbeddingAdapter):
    MODELS_INFO = {
        "all-minilm": 384,
        "all-mpnet-base-v2": 768,
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "snowflake-arctic-embed": 1024,
    }

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        payload = {
            "model": request.model or self.model,
            "input": request.texts,
        }

        if request.dimensions or self.dimensions:
            payload["dimensions"] = request.dimensions or self.dimensions

        if request.truncate is not None:
            payload["truncate"] = request.truncate

        payload["keep_alive"] = "5m"

        url = f"{self.base_url}/api/embed"

        logger.debug(f"Sending embedding request to {url} with {len(request.texts)} texts")

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.post(url, json=payload)

                if response.status_code == 404:
                    try:
                        health_check = await client.get(f"{self.base_url}/api/tags")
                        if health_check.status_code == 200:
                            available_models = [
                                m.get("name", "") for m in health_check.json().get("models", [])
                            ]
                            raise ValueError(
                                f"Model '{payload['model']}' not found in Ollama. "
                                f"Available models: {', '.join(available_models[:10])}. "
                                f"Download it with: ollama pull {payload['model']}"
                            )
                    except httpx.HTTPError:
                        pass

                    raise ValueError(
                        f"Model '{payload['model']}' not found. "
                        f"Download it with: ollama pull {payload['model']}"
                    )

                response.raise_for_status()
                data = response.json()

        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Make sure Ollama is running. Start it with: ollama serve"
            ) from e

        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Request to Ollama timed out after {self.request_timeout}s. "
                f"The model might be too large or the server is overloaded."
            ) from e

        except httpx.HTTPError as e:
            logger.error(f"Ollama API error: {e}")
            raise

        embeddings = data["embeddings"]

        actual_dims = len(embeddings[0]) if embeddings else 0
        expected_dims = request.dimensions or self.dimensions

        if expected_dims and actual_dims != expected_dims:
            logger.warning(
                f"Dimension mismatch: expected {expected_dims}, got {actual_dims}. "
                f"Model '{payload['model']}' may not support custom dimensions."
            )

        logger.info(
            f"Successfully generated {len(embeddings)} embeddings "
            f"(model: {data.get('model', self.model)}, dimensions: {actual_dims})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=data.get("model", self.model),
            dimensions=actual_dims,
            usage={
                "prompt_eval_count": data.get("prompt_eval_count", 0),
                "total_duration": data.get("total_duration", 0),
            },
        )

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "dimensions": self.MODELS_INFO.get(self.model, self.dimensions),
            "local": True,
            "supports_variable_dimensions": False,
            "provider": "ollama",
        }
