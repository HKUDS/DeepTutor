"""Unified embedding client and adapters for all DeepTutor modules.

Supported bindings are resolved by ``services.config.provider_runtime`` and
currently include openai, custom, azure_openai, cohere, jina, ollama, vllm,
siliconflow, aliyun, openrouter, plus legacy custom_openai_sdk configs.
"""

from importlib import import_module

from .config import EmbeddingConfig, get_embedding_config
from .validation import validate_embedding_batch

_CLIENT_EXPORTS = {"EmbeddingClient", "get_embedding_client", "reset_embedding_client"}


def __getattr__(name: str):
    # Reading model metadata must not initialize every embedding SDK. Background
    # KB catalog scans need configuration even when no embedding call will run.
    if name in _CLIENT_EXPORTS:
        value = getattr(import_module(".client", __name__), name)
    elif name in __all__:
        value = getattr(import_module(".adapters", __name__), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


__all__ = [
    "EmbeddingClient",
    "EmbeddingConfig",
    "get_embedding_client",
    "get_embedding_config",
    "reset_embedding_client",
    "validate_embedding_batch",
    "BaseEmbeddingAdapter",
    "EmbeddingProviderError",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "OpenAICompatibleEmbeddingAdapter",
    "OpenAISDKEmbeddingAdapter",
    "DashScopeMultiModalEmbeddingAdapter",
    "CohereEmbeddingAdapter",
    "JinaEmbeddingAdapter",
    "OllamaEmbeddingAdapter",
]
