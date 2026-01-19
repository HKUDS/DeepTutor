# -*- coding: utf-8 -*-
"""
Embedding Provider Manager
===========================

Factory and manager for embedding adapters.
Provides centralized configuration and adapter selection.
"""

import logging
from typing import Any, Dict, Optional, Type

from .adapters.base import BaseEmbeddingAdapter
from .adapters.cohere import CohereEmbeddingAdapter
from .adapters.jina import JinaEmbeddingAdapter
from .adapters.ollama import OllamaEmbeddingAdapter
from .adapters.openai_compatible import OpenAICompatibleEmbeddingAdapter

logger = logging.getLogger(__name__)


class EmbeddingProviderManager:
    """
    Centralized manager for embedding providers.

    Responsibilities:
    - Map binding names to adapter classes
    - Instantiate and configure adapters
    - Maintain active adapter reference
    """

    # Mapping of binding names to adapter classes
    ADAPTER_MAPPING: Dict[str, Type[BaseEmbeddingAdapter]] = {
        "openai": OpenAICompatibleEmbeddingAdapter,
        "azure_openai": OpenAICompatibleEmbeddingAdapter,
        "jina": JinaEmbeddingAdapter,
        "huggingface": OpenAICompatibleEmbeddingAdapter,
        "google": OpenAICompatibleEmbeddingAdapter,
        "cohere": CohereEmbeddingAdapter,
        "ollama": OllamaEmbeddingAdapter,
        "lm_studio": OpenAICompatibleEmbeddingAdapter,  # LM Studio (OpenAI-compatible)
    }

    def __init__(self):
        """Initialize the provider manager."""
        self.adapter: Optional[BaseEmbeddingAdapter] = None

    def get_adapter(self, binding: str, config: Dict[str, Any]) -> BaseEmbeddingAdapter:
        """
        Get and instantiate an adapter for the specified binding.

        Args:
            binding: Provider binding name (e.g., "openai", "ollama")
            config: Configuration dictionary for the adapter

        Returns:
            Instantiated adapter instance

        Raises:
            ValueError: If the binding is not supported
        """
        adapter_class = self.ADAPTER_MAPPING.get(binding)

        if not adapter_class:
            supported = ", ".join(self.ADAPTER_MAPPING.keys())
            raise ValueError(
                f"Unknown embedding binding: '{binding}'. Supported providers: {supported}"
            )

        logger.info(f"Initializing embedding adapter for binding: {binding}")
        return adapter_class(config)

    def set_adapter(self, adapter: BaseEmbeddingAdapter) -> None:
        """
        Set the active adapter.

        Args:
            adapter: Adapter instance to set as active
        """
        self.adapter = adapter
        logger.debug(f"Active embedding adapter set to: {adapter.__class__.__name__}")

    def get_active_adapter(self) -> BaseEmbeddingAdapter:
        """
        Get the currently active adapter.

        Returns:
            Active adapter instance

        Raises:
            RuntimeError: If no adapter is configured
        """
        if not self.adapter:
            raise RuntimeError(
                "No active embedding adapter configured. Please initialize EmbeddingClient first."
            )
        return self.adapter


# Global singleton instance
_manager: Optional[EmbeddingProviderManager] = None


def get_embedding_provider_manager() -> EmbeddingProviderManager:
    """
    Get or create the singleton embedding provider manager.

    Returns:
        EmbeddingProviderManager instance
    """
    global _manager
    if _manager is None:
        _manager = EmbeddingProviderManager()
    return _manager


def reset_embedding_provider_manager():
    """Reset the singleton provider manager (useful for testing)."""
    global _manager
    _manager = None
