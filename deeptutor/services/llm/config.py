"""
LLM Configuration
=================

Configuration management for LLM services.
Loads from data/user/settings/model_catalog.json.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
import logging
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, TypedDict

from deeptutor.services.config import resolve_llm_runtime_config
from deeptutor.services.provider_registry import canonical_provider_name, find_by_name

from .exceptions import LLMConfigError

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
    provider_mode: str
    api_version: str | None
    extra_headers: dict[str, str]
    reasoning_effort: str | None
    context_window: int | None
    max_tokens: int
    temperature: float
    max_concurrency: int
    requests_per_minute: int
    traffic_controller: "TrafficController" | None


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _is_openai_compatible_binding(binding: str | None) -> bool:
    canonical = canonical_provider_name(binding) or (binding or "").strip().lower()
    spec = find_by_name(canonical)
    if not spec or spec.is_oauth:
        return False
    return spec.backend in {"openai_compat", "azure_openai"}


def _set_openai_env_vars(api_key: str | None, base_url: str | None, *, source: str) -> None:
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        logger.debug("Set OPENAI_API_KEY env var (%s)", source)

    if base_url:
        from .utils import sanitize_url

        clean_url = sanitize_url(base_url)
        os.environ["OPENAI_BASE_URL"] = clean_url
        logger.debug("Set OPENAI_BASE_URL env var to %s (%s)", clean_url, source)


def _setup_openai_env_vars_early() -> None:
    """
    Set OPENAI_* environment variables early for OpenAI-compatible SDKs.

    Some SDK helpers read credentials/endpoints from process environment.
    This is called at module import time so downstream calls have consistent
    environment regardless of entrypoint.
    """
    try:
        resolved = resolve_llm_runtime_config()
    except Exception:
        return
    if _is_openai_compatible_binding(resolved.binding):
        _set_openai_env_vars(resolved.api_key, resolved.effective_url, source="early init")


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
    provider_mode: str = "standard"
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    reasoning_effort: str | None = None
    context_window: int | None = None
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
_SCOPED_LLM_CONFIG: ContextVar[LLMConfig | None] = ContextVar(
    "deeptutor_scoped_llm_config",
    default=None,
)


def set_scoped_llm_config(config: LLMConfig | None) -> Token[LLMConfig | None]:
    """Set the LLM config for the current async context."""
    return _SCOPED_LLM_CONFIG.set(config)


def reset_scoped_llm_config(token: Token[LLMConfig | None]) -> None:
    """Reset a scoped LLM config token returned by ``set_scoped_llm_config``."""
    _SCOPED_LLM_CONFIG.reset(token)


def initialize_environment() -> None:
    """
    Explicitly initialize environment variables for compatibility.

    This should be called during application startup to keep OPENAI_* env vars
    aligned with current config values.
    """
    resolved = resolve_llm_runtime_config()
    if _is_openai_compatible_binding(resolved.binding):
        _set_openai_env_vars(
            resolved.api_key,
            resolved.effective_url,
            source="initialize_environment",
        )


def _get_llm_config_from_resolver() -> LLMConfig:
    """Resolve LLM config from the TutorBot-style runtime adapter."""
    resolved = resolve_llm_runtime_config()
    if not resolved.model:
        raise LLMConfigError(
            "No active LLM model is configured. Please set it in Settings > Catalog."
        )
    if not resolved.effective_url and resolved.provider_mode != "oauth":
        raise LLMConfigError(
            "No effective LLM endpoint resolved. Please configure base_url or provider defaults."
        )
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        reasoning_effort=resolved.reasoning_effort,
        context_window=resolved.context_window,
    )


def get_llm_config() -> LLMConfig:
    """
    Load LLM configuration.

    Returns:
        LLMConfig: Configuration dataclass

    Raises:
        LLMConfigError: If required configuration is missing
    """
    global _LLM_CONFIG_CACHE

    scoped = _SCOPED_LLM_CONFIG.get()
    if scoped is not None:
        return scoped

    if _LLM_CONFIG_CACHE is not None:
        return _LLM_CONFIG_CACHE

    _LLM_CONFIG_CACHE = _get_llm_config_from_resolver()
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
        r"^o\d",  # o1, o3, o4-mini, o4, and future o-series models
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
