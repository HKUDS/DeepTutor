# -*- coding: utf-8 -*-
"""
LLM Factory - Central Hub for LLM Calls
=======================================
This module serves as the central hub for all LLM calls in DeepTutor.
It provides a unified interface for agents to call LLMs, routing requests
to the appropriate provider (cloud or local) based on URL detection.

Compatibility:
    This factory preserves legacy behaviors from the pre-provider refactor,
    including BaseAgent.call_llm()/stream_llm() signatures and retry semantics.
    The adapter layer remains until all legacy entry points migrate to direct
    provider calls. Once all agents and tools depend on provider modules
    directly, this wrapper can be removed.

Architecture:
    Agents (ChatAgent, GuideAgent, etc.)
              ↓
         BaseAgent.call_llm() / stream_llm()
              ↓
         LLM Factory (this module)
              ↓
    ┌─────────┴─────────┐
    ↓                   ↓
CloudProvider      LocalProvider
(cloud_provider)   (local_provider)
              ↓                   ↓
OpenAI/DeepSeek/etc    LM Studio/Ollama/etc

Routing:
- Automatically routes to local_provider for local URLs (localhost, 127.0.0.1, etc.)
- Routes to cloud_provider for all other URLs

Retry Mechanism:
- Automatic retry with exponential backoff for transient errors
- Configurable max_retries, retry_delay, and exponential_backoff
- Only retries on retriable errors (timeout, rate limit, server errors)
"""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from typing import TYPE_CHECKING, TypedDict

import tenacity

from src.config.settings import settings
from src.logging.logger import Logger, get_logger

from . import local_provider
from .config import LLMConfig, get_llm_config
from .exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .utils import is_local_llm_server

if TYPE_CHECKING:
    from .providers.base_provider import BaseLLMProvider

# Initialize logger
logger: Logger = get_logger("LLMFactory")

# Default retry configuration (bound to settings)
DEFAULT_MAX_RETRIES = settings.retry.max_retries
DEFAULT_RETRY_DELAY = settings.retry.base_delay
DEFAULT_EXPONENTIAL_BACKOFF = settings.retry.exponential_backoff

CallKwargs = dict[str, object]


def _is_retriable_error(error: BaseException) -> bool:
    """
    Check if an error is retriable.

    Retriable errors:
    - Timeout errors
    - Rate limit errors (429)
    - Server errors (5xx)
    - Network/connection errors

    Non-retriable errors:
    - CancelledError / KeyboardInterrupt (must propagate immediately)
    - Authentication errors (401)
    - Bad request (400)
    - Not found (404)
    - Client errors (4xx except 429)
    """
    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, GeneratorExit)):
        return False

    from aiohttp import ClientError

    if isinstance(error, (asyncio.TimeoutError, ClientError)):
        return True
    if isinstance(error, LLMTimeoutError):
        return True
    if isinstance(error, LLMRateLimitError):
        return True
    if isinstance(error, LLMAuthenticationError):
        return False  # Don't retry auth errors

    if isinstance(error, LLMAPIError):
        status_code = error.status_code
        if status_code:
            # Retry on server errors (5xx) and rate limits (429)
            if status_code >= 500 or status_code == 429:
                return True
            # Don't retry on client errors (4xx except 429)
            if 400 <= status_code < 500:
                return False

        # When status_code is None (e.g. connection drop), retry.
        return True

    # For other exceptions (network errors, etc.), retry
    return True


def _should_use_local(base_url: str | None) -> bool:
    """
    Determine if we should use the local provider based on URL.

    Args:
        base_url: The base URL to check

    Returns:
        True if local provider should be used (localhost, 127.0.0.1, etc.)
    """
    return is_local_llm_server(base_url) if base_url else False


async def complete(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_version: str | None = None,
    binding: str | None = None,
    messages: list[dict[str, str]] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    exponential_backoff: bool = DEFAULT_EXPONENTIAL_BACKOFF,
    **kwargs: object,
) -> str:
    """
    Unified LLM completion function with automatic retry.

    Routes to cloud_provider or local_provider based on configuration.
    Includes automatic retry with exponential backoff for transient errors.

    Args:
        prompt: The user prompt
        system_prompt: System prompt for context
        model: Model name (optional, uses effective config if not provided)
        api_key: API key (optional)
        base_url: Base URL for the API (optional)
        api_version: API version for Azure OpenAI (optional)
        binding: Provider binding type (optional)
        messages: Pre-built messages array (optional)
        max_retries: Maximum number of retry attempts (default: 5)
        retry_delay: Initial delay between retries in seconds (default: 2.0)
        exponential_backoff: Whether to use exponential backoff (default: True)
        **kwargs: Additional parameters (temperature, max_tokens, etc.)

    Returns:
        str: The LLM response
    """
    # Get config if parameters not provided
    if not model or not base_url:
        config = get_llm_config()
        model = model or config.model
        api_key = api_key if api_key is not None else config.api_key
        base_url = base_url or config.base_url
        api_version = api_version or config.api_version
        binding = binding or config.binding or "openai"

    # Determine which provider to use
    use_local = _should_use_local(base_url)

    def _is_retriable_llm_api_error(exc: BaseException) -> bool:
        """Delegate retriable checks to shared helper."""
        return _is_retriable_error(exc)

    def _log_retry_warning(retry_state: tenacity.RetryCallState) -> None:
        """Log retry warnings with safe handling for missing exceptions."""
        outcome = retry_state.outcome
        exception = outcome.exception() if outcome else None
        error_message = str(exception) if exception else "unknown error"
        if not error_message.strip():
            error_message = f"{type(exception).__name__} (no message)"
        logger.warning(
            "LLM call failed (attempt %s/%s), retrying in %.1fs... Error: %s"
            % (
                retry_state.attempt_number,
                max_retries + 1,
                retry_state.upcoming_sleep,
                error_message,
            )
        )

    wait_strategy = (
        tenacity.wait_exponential(
            multiplier=retry_delay,
            min=retry_delay,
            max=120,
        )
        if exponential_backoff
        else tenacity.wait_fixed(retry_delay)
    )

    total_attempts = max_retries + 1

    @tenacity.retry(
        retry=(
            tenacity.retry_if_exception_type(LLMRateLimitError)
            | tenacity.retry_if_exception_type(LLMTimeoutError)
            | tenacity.retry_if_exception(_is_retriable_llm_api_error)
        ),
        wait=wait_strategy,
        stop=tenacity.stop_after_attempt(total_attempts),
        before_sleep=_log_retry_warning,
    )
    async def _do_complete(
        *,
        prompt_value: str,
        system_prompt_value: str,
        model_value: str,
        api_key_value: str | None,
        base_url_value: str | None,
        api_version_value: str | None,
        binding_value: str | None,
        extra_kwargs: CallKwargs,
        messages_value: list[dict[str, str]] | None,
    ) -> str:
        try:
            if use_local:
                return await local_provider.complete(
                    prompt=prompt_value,
                    system_prompt=system_prompt_value,
                    model=model_value,
                    api_key=api_key_value,
                    base_url=base_url_value,
                    messages=messages_value,
                    **extra_kwargs,
                )
            from . import cloud_provider

            return await cloud_provider.complete(
                prompt=prompt_value,
                system_prompt=system_prompt_value,
                model=model_value,
                api_key=api_key_value,
                base_url=base_url_value,
                api_version=api_version_value,
                binding=binding_value or "openai",
                messages=messages_value,
                **extra_kwargs,
            )
        except Exception as exc:
            from .error_mapping import map_error

            if use_local:
                provider_name = "local"
            else:
                provider_name = binding_value if isinstance(binding_value, str) else "unknown"
            mapped_error = map_error(exc, provider=provider_name)
            raise mapped_error from exc

    extra_kwargs: CallKwargs = dict(kwargs)
    extra_kwargs.pop("messages", None)

    if use_local:
        return await _do_complete(
            prompt_value=prompt,
            system_prompt_value=system_prompt,
            model_value=model,
            api_key_value=api_key,
            base_url_value=base_url,
            api_version_value=None,
            binding_value=None,
            extra_kwargs=extra_kwargs,
            messages_value=messages,
        )

    return await _do_complete(
        prompt_value=prompt,
        system_prompt_value=system_prompt,
        model_value=model,
        api_key_value=api_key,
        base_url_value=base_url,
        api_version_value=api_version,
        binding_value=binding or "openai",
        extra_kwargs=extra_kwargs,
        messages_value=messages,
    )


async def stream(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    api_version: str | None = None,
    binding: str | None = None,
    messages: list[dict[str, str]] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    exponential_backoff: bool = DEFAULT_EXPONENTIAL_BACKOFF,
    **kwargs: object,
) -> AsyncGenerator[str, None]:
    """Stream LLM responses with retry handling."""
    if not model or not base_url:
        config = get_llm_config()
        model = model or config.model
        api_key = api_key if api_key is not None else config.api_key
        base_url = base_url or config.base_url
        api_version = api_version or config.api_version
        binding = binding or config.binding or "openai"

    use_local = _should_use_local(base_url)
    extra_kwargs: CallKwargs = dict(kwargs)
    extra_kwargs.pop("messages", None)

    total_attempts = max_retries + 1
    last_exception: Exception | None = None
    delay = retry_delay
    has_yielded = False
    max_delay = 120

    for attempt in range(total_attempts):
        try:
            if use_local:
                async for chunk in local_provider.stream(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    messages=messages,
                    **extra_kwargs,
                ):
                    has_yielded = True
                    yield chunk
            else:
                from . import cloud_provider

                async for chunk in cloud_provider.stream(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    api_version=api_version,
                    binding=binding or "openai",
                    messages=messages,
                    **extra_kwargs,
                ):
                    has_yielded = True
                    yield chunk
            return
        except Exception as exc:
            last_exception = exc
            if has_yielded:
                raise
            if attempt >= max_retries or not _is_retriable_error(exc):
                raise

            if exponential_backoff:
                current_delay = min(delay * (2**attempt), max_delay)
            else:
                current_delay = delay

            if isinstance(exc, LLMRateLimitError) and exc.retry_after:
                current_delay = max(current_delay, exc.retry_after)

            logger.warning(
                "LLM streaming failed (attempt %s/%s), retrying in %.1fs... Error: %s"
                % (attempt + 1, total_attempts, current_delay, exc)
            )
            await asyncio.sleep(current_delay)

    if last_exception:
        raise last_exception


async def fetch_models(
    binding: str,
    base_url: str,
    api_key: str | None = None,
) -> list[str]:
    """
    Fetch available models from the provider.

    Routes to cloud_provider or local_provider based on URL.

    Args:
        binding: Provider type (openai, ollama, etc.)
        base_url: API endpoint URL
        api_key: API key (optional for local providers)

    Returns:
        List of available model names
    """
    if is_local_llm_server(base_url):
        return await local_provider.fetch_models(base_url, api_key)
    else:
        from . import cloud_provider

        return await cloud_provider.fetch_models(base_url, api_key, binding)


class ApiProviderPreset(TypedDict, total=False):
    """Typed representation of API provider presets."""

    name: str
    base_url: str
    requires_key: bool
    models: list[str]
    binding: str


class LocalProviderPreset(TypedDict, total=False):
    """Typed representation of local provider presets."""

    name: str
    base_url: str
    requires_key: bool
    default_key: str


ProviderPreset = ApiProviderPreset | LocalProviderPreset
ProviderPresetMap = Mapping[str, ProviderPreset]
ProviderPresetBundle = Mapping[str, ProviderPresetMap]


# API Provider Presets
API_PROVIDER_PRESETS: dict[str, ApiProviderPreset] = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "requires_key": True,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "requires_key": True,
        "binding": "anthropic",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "requires_key": True,
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "requires_key": True,
        "models": [],
    },
}

# Local Provider Presets
LOCAL_PROVIDER_PRESETS: dict[str, LocalProviderPreset] = {
    "ollama": {
        "name": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "requires_key": False,
        "default_key": "ollama",
    },
    "lm_studio": {
        "name": "LM Studio",
        "base_url": "http://localhost:1234/v1",
        "requires_key": False,
        "default_key": "lm-studio",
    },
    "vllm": {
        "name": "vLLM",
        "base_url": "http://localhost:8000/v1",
        "requires_key": False,
        "default_key": "vllm",
    },
    "llama_cpp": {
        "name": "llama.cpp",
        "base_url": "http://localhost:8080/v1",
        "requires_key": False,
        "default_key": "llama-cpp",
    },
}


def get_provider_presets() -> ProviderPresetBundle:
    """
    Get all provider presets for frontend display.
    """
    return {
        "api": API_PROVIDER_PRESETS,
        "local": LOCAL_PROVIDER_PRESETS,
    }


__all__ = [
    "complete",
    "stream",
    "fetch_models",
    "get_provider_presets",
    "API_PROVIDER_PRESETS",
    "LOCAL_PROVIDER_PRESETS",
    # Retry configuration defaults
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_EXPONENTIAL_BACKOFF",
    "LLMFactory",
]


class LLMFactory:
    """Compatibility factory for legacy agent integrations."""

    @staticmethod
    def get_provider(config: "LLMConfig") -> "BaseLLMProvider":
        """Return a provider instance for the supplied config."""
        from .providers.routing import RoutingProvider

        return RoutingProvider(config)
