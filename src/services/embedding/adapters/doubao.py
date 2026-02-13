"""Doubao (Volcano Engine) multimodal embedding adapter."""

import logging
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse

logger = logging.getLogger(__name__)


class DoubaoEmbeddingAdapter(BaseEmbeddingAdapter):
    """
    Adapter for Doubao (Volcano Engine) multimodal embedding API.
    
    Supports Doubao's embedding models like doubao-embedding-vision-251215.
    Uses the /embeddings/multimodal endpoint with a different input format.
    """
    
    MODELS_INFO = {
        "doubao-embedding-vision-251215": {
            "default": 1024,
            "dimensions": [1024, 2048],
        },
    }

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Doubao embedding adapter.
        
        Args:
            config: Configuration dictionary with:
                - api_key: Doubao API key (ARK_API_KEY)
                - base_url: API base URL (e.g., https://ark.cn-beijing.volces.com/api/v3)
                - model: Model name (e.g., doubao-embedding-vision-251215)
                - dimensions: Embedding dimensions
                - request_timeout: Request timeout in seconds
                - instructions: Optional instructions for the model
        """
        super().__init__(config)
        self.instructions = config.get("instructions")

    async def _embed_single(self, text: str, client: httpx.AsyncClient) -> List[float]:
        """Generate embedding for a single text."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Doubao input format for single text
        input_data = [{"type": "text", "text": text}]

        payload = {
            "model": self.model,
            "input": input_data,
            "encoding_format": "float",
            "sparse_embedding": {"type": "enabled"},
        }
        
        # Add dimensions if specified (must use self.dimensions as fallback)
        if self.dimensions:
            payload["dimensions"] = self.dimensions
            
        if self.instructions:
            payload["instructions"] = self.instructions

        url = f"{self.base_url}/embeddings/multimodal"
        
        response = await client.post(url, json=payload, headers=headers)
        
        if response.status_code >= 400:
            logger.error(f"HTTP {response.status_code} response body: {response.text}")
            response.raise_for_status()
            
        data = response.json()
        
        # Parse response
        # Structure: {"data": {"embedding": [0.1, 0.2, ...], ...}}
        try:
            embedding = data["data"]["embedding"]
            return embedding
        except (KeyError, TypeError) as e:
            logger.error(f"Failed to parse Doubao response: {data}")
            raise Exception(f"Unexpected response format from Doubao: {e}")

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        Generate embeddings using Doubao's multimodal API.
        Handles batch requests by sending concurrent single requests.
        
        Args:
            request: EmbeddingRequest with texts to embed
            
        Returns:
            EmbeddingResponse with embeddings and metadata
        """
        import asyncio
        
        logger.debug(f"Process {len(request.texts)} texts with Doubao adapter")

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            # Create concurrent tasks for all texts
            tasks = [self._embed_single(text, client) for text in request.texts]
            embeddings = await asyncio.gather(*tasks)

        actual_dims = len(embeddings[0]) if embeddings else 0
        expected_dims = request.dimensions or self.dimensions

        if expected_dims and actual_dims != expected_dims:
            logger.warning(
                f"Dimension mismatch: expected {expected_dims}, got {actual_dims}. "
                f"Model '{self.model}' may not support custom dimensions."
            )

        logger.info(
            f"Successfully generated {len(embeddings)} embeddings "
            f"(model: {self.model}, dimensions: {actual_dims})"
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=self.model,
            dimensions=actual_dims,
            usage={"total_tokens": sum(len(t) for t in request.texts)}, # Approx usage
        )

    def get_model_info(self) -> Dict[str, Any]:
        """
        Return information about the configured Doubao model.
        
        Returns:
            Dictionary with model metadata
        """
        model_info = self.MODELS_INFO.get(self.model, self.dimensions)

        if isinstance(model_info, dict):
            return {
                "model": self.model,
                "dimensions": model_info.get("default", self.dimensions),
                "supported_dimensions": model_info.get("dimensions", []),
                "supports_variable_dimensions": len(model_info.get("dimensions", [])) > 1,
                "provider": "doubao",
            }
        else:
            return {
                "model": self.model,
                "dimensions": model_info or self.dimensions,
                "supports_variable_dimensions": False,
                "provider": "doubao",
            }
