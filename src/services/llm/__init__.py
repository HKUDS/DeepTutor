# -*- coding: utf-8 -*-
"""
LLM Service
===========

Unified LLM service for all DeepTutor modules.

Architecture:
    Agents (ChatAgent, GuideAgent, etc.)
              ↓
         BaseAgent.call_llm() / stream_llm()
              ↓
         LLM Factory (complete / stream)
              ↓
    ┌─────────┴─────────┐
    ↓                   ↓
CloudProvider      LocalProvider
(cloud_provider)   (local_provider)

Features:
- Unified interface for all LLM providers (cloud + local)
- Automatic retry with exponential backoff
- Smart routing based on URL detection
- Provider capability detection

Usage:
    # Simple completion (with automatic retry)
    from src.services.llm import complete, stream
    response = await complete("Hello!", system_prompt="You are helpful.")

    # Streaming (with automatic retry on connection)
    async for chunk in stream("Hello!", system_prompt="You are helpful."):
        print(chunk, end="")

    # Custom retry configuration
    response = await complete(
        "Hello!",
        max_retries=5,
        retry_delay=2.0,
        exponential_backoff=True,
    )

    # Configuration
    from src.services.llm import get_llm_config, LLMConfig
    config = get_llm_config()

    # URL utilities for local LLM servers
    from src.services.llm import sanitize_url, is_local_llm_server
"""

# Note: cloud_provider and local_provider are lazy-loaded via __getattr__
# to avoid importing lightrag at module load time
from .capabilities import (
    DEFAULT_CAPABILITIES,
    MODEL_OVERRIDES,
    PROVIDER_CAPABILITIES,
    get_capability,
    has_thinking_tags,
    requires_api_version,
    supports_response_format,
    supports_streaming,
    supports_tools,
    system_in_messages,
)
from .client import LLMClient, get_llm_client, reset_llm_client
from .config import (
    LLMConfig,
    get_llm_config,
    get_token_limit_kwargs,
    uses_max_completion_tokens,
)
from .exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMConfigError,
    LLMError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .factory import (
    API_PROVIDER_PRESETS,
    DEFAULT_EXPONENTIAL_BACKOFF,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    LOCAL_PROVIDER_PRESETS,
    complete,
    fetch_models,
    get_provider_presets,
    stream,
)
from .utils import (
    build_auth_headers,
    build_chat_url,
    clean_thinking_tags,
    extract_response_content,
    is_local_llm_server,
    sanitize_url,
)

__all__ = [
    # Client (legacy, prefer factory functions)
    "LLMClient",
    "get_llm_client",
    "reset_llm_client",
    # Config
    "LLMConfig",
    "get_llm_config",
    "uses_max_completion_tokens",
    "get_token_limit_kwargs",
    # Capabilities
    "PROVIDER_CAPABILITIES",
    "MODEL_OVERRIDES",
    "DEFAULT_CAPABILITIES",
    "get_capability",
    "supports_response_format",
    "supports_streaming",
    "system_in_messages",
    "has_thinking_tags",
    "supports_tools",
    "requires_api_version",
    # Exceptions
    "LLMError",
    "LLMConfigError",
    "LLMProviderError",
    "LLMAPIError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
    "LLMModelNotFoundError",
    # Factory (main API)
    "complete",
    "stream",
    "fetch_models",
    "get_provider_presets",
    "API_PROVIDER_PRESETS",
    "LOCAL_PROVIDER_PRESETS",
    # Retry configuration
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_EXPONENTIAL_BACKOFF",
    # Providers (lazy loaded)
    "cloud_provider",
    "local_provider",
    # Utils
    "sanitize_url",
    "is_local_llm_server",
    "build_chat_url",
    "build_auth_headers",
    "clean_thinking_tags",
    "extract_response_content",
]


def __getattr__(name: str):
    """Lazy import for provider modules that depend on heavy libraries."""
    if name == "cloud_provider":
        from . import cloud_provider

        return cloud_provider
    if name == "local_provider":
        from . import local_provider

        return local_provider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
