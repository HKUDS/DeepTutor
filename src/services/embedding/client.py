# -*- coding: utf-8 -*-
"""
Embedding Client
================

Unified embedding client for all DeepTutor services.
Now supports multiple providers through adapters.
"""

from typing import List, Optional

from src.logging import get_logger

from .adapters.base import EmbeddingRequest
from .config import EmbeddingConfig, get_embedding_config
from .provider import EmbeddingProviderManager, get_embedding_provider_manager


class EmbeddingClient:
    """
    Unified embedding client for all services.

    Delegates to provider-specific adapters based on configuration.
    Supports: OpenAI, Azure OpenAI, Cohere, Ollama, Jina, HuggingFace, Google.
    """

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        """
        Initialize embedding client.

        Args:
            config: Embedding configuration. If None, loads from environment.
        """
        self.config = config or get_embedding_config()
        self.logger = get_logger("EmbeddingClient")
        self.manager: EmbeddingProviderManager = get_embedding_provider_manager()

        # Initialize adapter based on binding configuration
        try:
            adapter = self.manager.get_adapter(
                self.config.binding,
                {
                    "api_key": self.config.api_key,
                    "base_url": self.config.base_url,
                    "api_version": getattr(self.config, "api_version", None),
                    "model": self.config.model,
                    "dimensions": self.config.dim,
                    "request_timeout": self.config.request_timeout,
                },
            )
            self.manager.set_adapter(adapter)

            self.logger.info(
                f"Initialized embedding client with {self.config.binding} adapter "
                f"(model: {self.config.model}, dimensions: {self.config.dim})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize embedding adapter: {e}")
            raise

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Get embeddings for texts using the configured adapter.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        adapter = self.manager.get_active_adapter()

        request = EmbeddingRequest(
            texts=texts,
            model=self.config.model,
            dimensions=self.config.dim,
            input_type=self.config.input_type,  # Pass input_type for task-aware embeddings
        )

        try:
            response = await adapter.embed(request)

            self.logger.debug(
                f"Generated {len(response.embeddings)} embeddings using {self.config.binding}"
            )

            return response.embeddings
        except Exception as e:
            self.logger.error(f"Embedding request failed: {e}")
            raise

    def embed_sync(self, texts: List[str]) -> List[List[float]]:
        """
        Synchronous wrapper for embed().

        Use this when you need to call from non-async context.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.embed(texts))
                    return future.result()
            else:
                return loop.run_until_complete(self.embed(texts))
        except RuntimeError:
            return asyncio.run(self.embed(texts))

    def get_embedding_func(self):
        """
        Get an EmbeddingFunc compatible with LightRAG.

        Returns:
            EmbeddingFunc instance
        """
        from lightrag.utils import EmbeddingFunc
        import numpy as np

        # Create async wrapper that uses our adapter system
        # LightRAG expects numpy arrays, not Python lists
        async def embedding_wrapper(texts: List[str]):
            embeddings = await self.embed(texts)
            # Convert list of lists to numpy array for LightRAG compatibility
            return np.array(embeddings)

        return EmbeddingFunc(
            embedding_dim=self.config.dim,
            max_token_size=self.config.max_tokens,
            func=embedding_wrapper,
        )


# Singleton instance
_client: Optional[EmbeddingClient] = None


def get_embedding_client(config: Optional[EmbeddingConfig] = None) -> EmbeddingClient:
    """
    Get or create the singleton embedding client.

    Args:
        config: Optional configuration. Only used on first call.

    Returns:
        EmbeddingClient instance
    """
    global _client
    if _client is None:
        _client = EmbeddingClient(config)
    return _client


def reset_embedding_client():
    """Reset the singleton embedding client."""
    global _client
    _client = None
