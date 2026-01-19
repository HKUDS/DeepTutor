# -*- coding: utf-8 -*-
"""
Base Embedding Adapter
=======================

Abstract base class for all embedding adapters.
Defines the contract that all embedding providers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class EmbeddingRequest:
    """
    Standard embedding request structure.

    Provider-agnostic request format. Different providers interpret fields differently:

    Args:
        texts: List of texts to embed
        model: Model name to use
        dimensions: Embedding vector dimensions (optional)
        input_type: Input type hint for task-aware embeddings (optional)
            - Cohere: Maps to 'input_type' ("search_document", "search_query", "classification", "clustering")
            - Jina: Maps to 'task' ("retrieval.passage", "retrieval.query", etc.)
            - OpenAI/Ollama: Ignored
        encoding_format: Output format ("float" or "base64", default: "float")
        truncate: Whether to truncate texts that exceed max tokens (default: True)
        normalized: Whether to return L2-normalized embeddings (Jina/Ollama only)
        late_chunking: Enable late chunking for long context (Jina v3 only)
    """

    texts: List[str]
    model: str
    dimensions: Optional[int] = None
    input_type: Optional[str] = None
    encoding_format: Optional[str] = "float"
    truncate: Optional[bool] = True
    normalized: Optional[bool] = True
    late_chunking: Optional[bool] = False


@dataclass
class EmbeddingResponse:
    """Standard embedding response structure."""

    embeddings: List[List[float]]
    model: str
    dimensions: int
    usage: Dict[str, Any]


class BaseEmbeddingAdapter(ABC):
    """
    Base class for all embedding adapters.

    Each adapter implements the specific API interface for a provider
    (OpenAI, Cohere, Ollama, etc.) while exposing a unified interface.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the adapter with configuration.

        Args:
            config: Dictionary containing:
                - api_key: API authentication key (optional for local)
                - base_url: API endpoint URL
                - model: Model name to use
                - dimensions: Embedding vector dimensions
                - request_timeout: Request timeout in seconds
        """
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.api_version = config.get("api_version")
        self.model = config.get("model")
        self.dimensions = config.get("dimensions")
        self.request_timeout = config.get("request_timeout", 30)

    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """
        Generate embeddings for a list of texts.

        Args:
            request: EmbeddingRequest with texts and parameters

        Returns:
            EmbeddingResponse with embeddings and metadata

        Raises:
            httpx.HTTPError: If the API request fails
        """
        pass

    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """
        Return information about the configured model.

        Returns:
            Dictionary with model metadata (name, dimensions, etc.)
        """
        pass
