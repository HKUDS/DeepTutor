"""
LLM Configuration
=================

Configuration management for LLM services.
Simplified version - loads from unified config service or falls back to .env.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, TypedDict

from dotenv import load_dotenv

if TYPE_CHECKING:
    from .traffic_control import TrafficController


class LLMConfigUpdate(TypedDict, total=False):
    """Fields allowed when cloning an LLMConfig instance."""

    model: str
    api_key: str
    base_url: str | None
    effective_url: str | None
    binding: str
    provider_name: str
    api_version: str | None
    max_tokens: int
    temperature: float
    max_concurrency: int
    requests_per_minute: int
    traffic_controller: "TrafficController" | None


from .exceptions import LLMConfigError

logger = logging.getLogger(__name__)

# Load environment variables
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(PROJECT_ROOT / ".env.local", override=False)


def _setup_openai_env_vars_early() -> None:
    """
    Set OPENAI_API_KEY environment variable early for LightRAG compatibility.

    LightRAG's internal functions (e.g., create_openai_async_client) read directly
    from os.environ["OPENAI_API_KEY"] instead of using the api_key parameter.
    This function ensures the environment variable is set as soon as this module
    is imported, before any LightRAG operations can occur.

    This is called at module load time to ensure env vars are set before any
    RAG operations, including those in worker threads/processes.
    """
    binding = os.getenv("LLM_BINDING", "openai")
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_HOST")

    # Only set env vars for OpenAI-compatible bindings
    if binding in ("openai", "azure_openai", "gemini"):
        if api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = api_key
            logger.debug("Set OPENAI_API_KEY env var for LightRAG compatibility (early init)")

        if base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = base_url
            logger.debug(
                "Set OPENAI_BASE_URL env var to %s (early init)",
                base_url,
            )


# Execute early setup at module import time
_setup_openai_env_vars_early()


@dataclass
class LLMConfig:
    """LLM configuration dataclass."""

    model: str
    api_key: str
    base_url: str | None = None
    effective_url: str | None = None
    binding: str = "openai"
    provider_name: str = "routing"
    api_version: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    max_concurrency: int = 20
    requests_per_minute: int = 600
    traffic_controller: TrafficController | None = None

    def __post_init__(self) -> None:
        if self.effective_url is None:
            self.effective_url = self.base_url

    def model_copy(self, update: LLMConfigUpdate | None = None) -> "LLMConfig":
        """Return a copy of the config with optional updates."""
        return replace(self, **(update or {}))

    def get_api_key(self) -> str:
        """Return the API key string for provider consumers."""
        return self.api_key


_LLM_CONFIG_CACHE: LLMConfig | None = None


def initialize_environment() -> None:
    """
    Explicitly initialize environment variables for compatibility.

    LightRAG's internal functions (e.g., create_openai_async_client) read directly
    from os.environ["OPENAI_API_KEY"] instead of using the api_key parameter.
    This function ensures the environment variable is set.

    Should be called during application startup (main.py/run_server.py).
    """
    binding = _strip_value(os.getenv("LLM_BINDING")) or "openai"
    api_key = _strip_value(os.getenv("LLM_API_KEY"))
    base_url = _strip_value(os.getenv("LLM_HOST"))

    # Only set env vars for OpenAI-compatible bindings
    if binding in ("openai", "azure_openai", "gemini"):
        if api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = api_key
            logger.debug("Set OPENAI_API_KEY env var (LightRAG compatibility)")

        if base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = base_url
            logger.debug("Set OPENAI_BASE_URL env var to %s", base_url)


def _strip_value(value: str | None) -> str | None:
    """Remove leading/trailing whitespace and quotes from string."""
    if value is None:
        return None
    return value.strip().strip("\"'")


def _get_llm_config_from_env() -> LLMConfig:
    """Get LLM configuration from environment variables."""
    binding = _strip_value(os.getenv("LLM_BINDING")) or "openai"
    model = _strip_value(os.getenv("LLM_MODEL"))
    api_key = _strip_value(os.getenv("LLM_API_KEY"))
    base_url = _strip_value(os.getenv("LLM_HOST"))
    api_version = _strip_value(os.getenv("LLM_API_VERSION"))

    # Validate required configuration
    if not model:
        raise LLMConfigError(
            "LLM_MODEL not set, please configure it in .env file or add a configuration in Settings"
        )
    if not base_url:
        raise LLMConfigError(
            "LLM_HOST not set, please configure it in .env file or add a configuration in Settings"
        )

    return LLMConfig(
        binding=binding,
        model=model,
        api_key=api_key or "",
        base_url=base_url,
        api_version=api_version,
    )


def get_llm_config() -> LLMConfig:
    """
    Load LLM configuration.

    Priority:
    1. Active configuration from unified config service
    2. Environment variables (.env)

    Returns:
        LLMConfig: Configuration dataclass

    Raises:
        LLMConfigError: If required configuration is missing
    """
    global _LLM_CONFIG_CACHE

    if _LLM_CONFIG_CACHE is not None:
        return _LLM_CONFIG_CACHE

    # 1. Try to get active config from unified config service
    try:
        from src.services.config import get_active_llm_config

        config = get_active_llm_config()
        if config:
            _LLM_CONFIG_CACHE = LLMConfig(
                binding=config.get("provider") or "openai",
                model=config["model"],
                api_key=config.get("api_key", ""),
                base_url=config.get("base_url"),
                api_version=config.get("api_version"),
            )
            return _LLM_CONFIG_CACHE

    except ImportError:
        # Unified config service not yet available, fall back to env
        pass
    except Exception as e:
        logger.warning("Failed to load from unified config: %s", e)

    # 2. Fallback to environment variables
    _LLM_CONFIG_CACHE = _get_llm_config_from_env()
    return _LLM_CONFIG_CACHE


async def get_llm_config_async() -> LLMConfig:
    """
    Async wrapper for get_llm_config.

    Useful for consistency in async contexts, though the underlying load is synchronous.

    Returns:
        LLMConfig: Configuration dataclass
    """
    return get_llm_config()


def clear_llm_config_cache() -> None:
    """Clear cached LLM configuration."""
    global _LLM_CONFIG_CACHE

    _LLM_CONFIG_CACHE = None


def reload_config() -> LLMConfig:
    """Reload and return the LLM configuration."""
    clear_llm_config_cache()
    return get_llm_config()


def uses_max_completion_tokens(model: str) -> bool:
    """
    Check if the model uses max_completion_tokens instead of max_tokens.

    Newer OpenAI models (o1, o3, gpt-4o, gpt-5.x, etc.) require max_completion_tokens
    while older models use max_tokens.

    Args:
        model: The model name

    Returns:
        True if the model requires max_completion_tokens, False otherwise
    """
    model_lower = model.lower()

    # Models that require max_completion_tokens:
    # - o1, o3 series (reasoning models)
    # - gpt-4o series
    # - gpt-5.x and later
    patterns = [
        r"^o[13]",  # o1, o3 models
        r"^gpt-4o",  # gpt-4o models
        r"^gpt-[5-9]",  # gpt-5.x and later
        r"^gpt-\d{2,}",  # gpt-10+ (future proofing)
    ]

    for pattern in patterns:
        if re.match(pattern, model_lower):
            return True

    return False


def get_token_limit_kwargs(model: str, max_tokens: int) -> dict[str, int]:
    """
    Get the appropriate token limit parameter for the model.

    Args:
        model: The model name
        max_tokens: The desired token limit

    Returns:
        Dictionary with either {"max_tokens": value} or {"max_completion_tokens": value}
    """
    if uses_max_completion_tokens(model):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


__all__ = [
    "LLMConfig",
    "get_llm_config",
    "get_llm_config_async",
    "clear_llm_config_cache",
    "reload_config",
    "uses_max_completion_tokens",
    "get_token_limit_kwargs",
]
