"""
Embedding Configuration
=======================

Configuration management for embedding services.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)


@dataclass
class EmbeddingConfig:
    """Embedding configuration dataclass."""

    model: str
    api_key: str
    base_url: Optional[str] = None
    binding: str = "openai"
    dim: int = 3072
    max_tokens: int = 8192
    request_timeout: int = 30
    input_type: Optional[str] = None  # For task-aware embeddings (Cohere, Jina)

    # Optional provider-specific settings
    encoding_format: str = "float"
    normalized: bool = True
    truncate: bool = True
    late_chunking: bool = False


def _strip_value(value: Optional[str]) -> Optional[str]:
    """Remove leading/trailing whitespace and quotes from string."""
    if value is None:
        return None
    return value.strip().strip("\"'")


def _to_int(value: Optional[str], default: int) -> int:
    """Convert environment variable to int, fallback to default value on failure."""
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _to_bool(value: Optional[str], default: bool) -> bool:
    """Convert environment variable to bool."""
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def get_embedding_config() -> EmbeddingConfig:
    """
    Load embedding configuration from environment variables or provider manager.

    Priority:
    1. Active provider from embedding_providers.json
    2. Environment variables (.env)

    Strategy for environment variables:
    1. Read EMBEDDING_BINDING to determine active provider
    2. Try provider-specific variables first (e.g., JINA_EMBEDDING_MODEL)
    3. Fall back to generic EMBEDDING_* variables

    This allows easy switching between providers without changing all vars.

    Returns:
        EmbeddingConfig: Configuration dataclass

    Raises:
        ValueError: If required configuration is missing
    """
    # 1. Try to get active provider from provider config manager
    try:
        from .provider_config import embedding_provider_config_manager

        active_provider = embedding_provider_config_manager.get_active_provider()

        if active_provider:
            return EmbeddingConfig(
                binding=active_provider.binding,
                model=active_provider.model,
                api_key=active_provider.api_key or "",  # Empty string for local providers
                base_url=active_provider.base_url,
                dim=active_provider.dimensions,
                input_type=active_provider.input_type,
                normalized=active_provider.normalized,
                truncate=active_provider.truncate,
            )
    except Exception as e:
        print(f"⚠️ Failed to load active embedding provider: {e}")

    # 2. Fallback to environment variables
    binding = _strip_value(os.getenv("EMBEDDING_BINDING", "openai"))

    # Provider-specific prefix mapping
    prefix_map = {
        "openai": "OPENAI",
        "jina": "JINA",
        "google": "GOOGLE",
        "cohere": "COHERE",
        "azure_openai": "AZURE",
        "huggingface": "HF",
        "ollama": "OLLAMA",
        "lm_studio": "LM_STUDIO",
        "doubao": "DOUBAO",
    }

    prefix = prefix_map.get(binding, "")

    # Try provider-specific vars first, then fall back to generic
    def get_with_fallback(var_name: str, generic_name: str) -> Optional[str]:
        if prefix:
            specific = _strip_value(os.getenv(f"{prefix}_{var_name}"))
            if specific:
                return specific
        return _strip_value(os.getenv(generic_name))

    model = get_with_fallback("EMBEDDING_MODEL", "EMBEDDING_MODEL")
    api_key = get_with_fallback("EMBEDDING_API_KEY", "EMBEDDING_API_KEY")
    base_url = get_with_fallback("EMBEDDING_HOST", "EMBEDDING_HOST")
    dim_str = get_with_fallback("EMBEDDING_DIM", "EMBEDDING_DIM")

    # Strict mode: Model is required
    if not model:
        raise ValueError(
            f"Error: EMBEDDING_MODEL not set for binding '{binding}'. "
            f"Set either {prefix}_EMBEDDING_MODEL or EMBEDDING_MODEL in .env file"
        )

    # Check if API key is required
    # Local providers (Ollama, LM Studio) don't need API keys
    providers_without_key = ["ollama", "lm_studio"]
    requires_key = binding not in providers_without_key

    if requires_key and not api_key:
        raise ValueError(
            f"Error: EMBEDDING_API_KEY not set for binding '{binding}'. "
            f"Set {prefix}_EMBEDDING_API_KEY or EMBEDDING_API_KEY in .env file"
        )
    if not base_url:
        raise ValueError(
            f"Error: EMBEDDING_HOST not set for binding '{binding}'. "
            f"Set {prefix}_EMBEDDING_HOST or EMBEDDING_HOST in .env file"
        )

    # Get optional configuration
    dim = _to_int(dim_str, 3072)
    max_tokens = _to_int(_strip_value(os.getenv("EMBEDDING_MAX_TOKENS")), 8192)
    request_timeout = _to_int(_strip_value(os.getenv("EMBEDDING_REQUEST_TIMEOUT")), 30)
    input_type = _strip_value(os.getenv("EMBEDDING_INPUT_TYPE"))  # Optional

    # Provider-specific optional settings
    encoding_format = _strip_value(os.getenv("EMBEDDING_ENCODING_FORMAT")) or "float"
    normalized = _to_bool(_strip_value(os.getenv("EMBEDDING_NORMALIZED")), True)
    truncate = _to_bool(_strip_value(os.getenv("EMBEDDING_TRUNCATE")), True)
    late_chunking = _to_bool(_strip_value(os.getenv("EMBEDDING_LATE_CHUNKING")), False)

    return EmbeddingConfig(
        binding=binding,
        model=model,
        api_key=api_key,
        base_url=base_url,
        dim=dim,
        max_tokens=max_tokens,
        request_timeout=request_timeout,
        input_type=input_type,
        encoding_format=encoding_format,
        normalized=normalized,
        truncate=truncate,
        late_chunking=late_chunking,
    )
