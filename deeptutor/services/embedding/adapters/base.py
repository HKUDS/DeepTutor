"""
Base Embedding Adapter
=======================

Abstract base class for all embedding adapters.
Defines the contract that all embedding providers must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def looks_like_multimodal_embedding_model(model_name: Optional[str]) -> bool:
    """Best-effort guard for OpenAI-compatible multimodal embedding models."""
    if not model_name:
        return False
    normalized = model_name.lower().replace("_", "-")
    return any(
        marker in normalized
        for marker in (
            "qwen3-vl-embedding",
            "multimodal-embedding",
            "vision-embedding",
            "vl-embedding",
            "image-embedding",
        )
    )


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
        contents: Multimodal content list of dicts like
            ``[{"text": "..."}, {"image": "url|data: URI"}, {"video": "..."}]``.
            Adapters that support multimodal (DashScope, SiliconFlow Qwen3-VL,
            Cohere v4) consume this directly; text-only adapters MUST raise
            ``ValueError`` if it is set so the caller can route differently.
            When ``contents`` is set, ``texts`` is ignored.
        enable_fusion: DashScope-specific. ``True`` fuses all multimodal items
            into one vector; ``False`` (or None) returns one vector per item.
    """

    texts: List[str]
    model: str
    dimensions: Optional[int] = None
    input_type: Optional[str] = None
    encoding_format: Optional[str] = "float"
    truncate: Optional[bool] = True
    normalized: Optional[bool] = True
    late_chunking: Optional[bool] = False
    contents: Optional[List[Dict[str, Any]]] = None
    enable_fusion: Optional[bool] = None


@dataclass
class EmbeddingResponse:
    """Standard embedding response structure."""

    embeddings: List[List[float]]
    model: str
    dimensions: int
    usage: Dict[str, Any]


class EmbeddingProviderError(RuntimeError):
    """Structured error raised by embedding adapters on provider failures.

    Carries the HTTP status, response body excerpt, model name, and request
    URL so downstream callers (task log streams, UI surfaces) can show
    actionable diagnostics instead of a bare exception string.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        body: Optional[str] = None,
        model: Optional[str] = None,
        url: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.model = model
        self.url = url
        self.provider = provider

    def __str__(self) -> str:  # noqa: D401 - succinct
        parts = [super().__str__()]
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.model:
            parts.append(f"model={self.model}")
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.url:
            parts.append(f"url={self.url}")
        if self.body:
            snippet = self.body if len(self.body) <= 500 else self.body[:500] + "...(truncated)"
            parts.append(f"body={snippet}")
        return " | ".join(parts)


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
                - send_dimensions: Tri-state opt-in for the `dimensions`
                  request param. ``True`` always sends, ``False`` never
                  sends, ``None`` lets the adapter decide based on the
                  model family (default).
                - request_timeout: Request timeout in seconds
        """
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.api_version = config.get("api_version")
        self.model = config.get("model")
        self.dimensions = config.get("dimensions")
        self.send_dimensions: Optional[bool] = config.get("send_dimensions")
        self.request_timeout = config.get("request_timeout", 60)
        self.extra_headers = config.get("extra_headers") or {}

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
