# -*- coding: utf-8 -*-
"""
Provider Capabilities
=====================

Centralized configuration for LLM provider capabilities.
This replaces scattered hardcoded checks throughout the codebase.

Usage:
    from src.services.llm.capabilities import get_capability, supports_response_format

    # Check if a provider supports response_format
    if supports_response_format(binding, model):
        kwargs["response_format"] = {"type": "json_object"}

    # Generic capability check
    if get_capability(binding, "streaming", default=True):
        # use streaming
"""

from typing import Any, Optional

# Provider capabilities configuration
# Keys are binding names (lowercase), values are capability dictionaries
PROVIDER_CAPABILITIES: dict[str, dict[str, Any]] = {
    # OpenAI and OpenAI-compatible providers
    "openai": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,  # System prompt goes in messages array
        "newer_models_use_max_completion_tokens": True,
    },
    "azure_openai": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
        "newer_models_use_max_completion_tokens": True,
        "requires_api_version": True,
    },
    # Anthropic
    "anthropic": {
        "supports_response_format": False,  # Anthropic uses different format
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": False,  # System is a separate parameter
        "has_thinking_tags": False,
    },
    "claude": {  # Alias for anthropic
        "supports_response_format": False,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": False,
        "has_thinking_tags": False,
    },
    # DeepSeek
    "deepseek": {
        "supports_response_format": False,  # DeepSeek doesn't support strict JSON schema yet
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
        "has_thinking_tags": True,  # DeepSeek reasoner has thinking tags
    },
    # OpenRouter (aggregator, generally OpenAI-compatible)
    "openrouter": {
        "supports_response_format": True,  # Depends on underlying model
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
    },
    # Groq (fast inference)
    "groq": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
    },
    # Together AI
    "together": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
    },
    "together_ai": {  # Alias
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
    },
    # Mistral
    "mistral": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "system_in_messages": True,
    },
    # Local providers (generally OpenAI-compatible)
    "ollama": {
        "supports_response_format": True,  # Ollama supports JSON mode
        "supports_streaming": True,
        "supports_tools": False,  # Limited tool support
        "system_in_messages": True,
    },
    "lm_studio": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": False,
        "system_in_messages": True,
    },
    "vllm": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": False,
        "system_in_messages": True,
    },
    "llama_cpp": {
        "supports_response_format": True,  # llama.cpp server supports JSON grammar
        "supports_streaming": True,
        "supports_tools": False,
        "system_in_messages": True,
    },
}

# Default capabilities for unknown providers (assume OpenAI-compatible)
DEFAULT_CAPABILITIES: dict[str, Any] = {
    "supports_response_format": True,
    "supports_streaming": True,
    "supports_tools": False,
    "system_in_messages": True,
    "has_thinking_tags": False,
    "forced_temperature": None,  # None means no forced value, use requested temperature
}

# Model-specific overrides
# Format: {model_pattern: {capability: value}}
# Patterns are matched with case-insensitive startswith
MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    "deepseek": {
        "supports_response_format": False,
        "has_thinking_tags": True,
    },
    "deepseek-reasoner": {
        "supports_response_format": False,
        "has_thinking_tags": True,
    },
    "qwen": {
        # Qwen models may have thinking tags
        "has_thinking_tags": True,
    },
    "qwq": {
        # QwQ is Qwen's reasoning model with thinking tags
        "has_thinking_tags": True,
    },
    # Claude models through OpenRouter or other providers
    "claude": {
        "supports_response_format": False,
        "system_in_messages": False,
    },
    # Anthropic models
    "anthropic/": {
        "supports_response_format": False,
        "system_in_messages": False,
    },
    # Reasoning models - only support temperature=1.0
    # See: https://github.com/HKUDS/DeepTutor/issues/141
    "gpt-5": {
        "forced_temperature": 1.0,
    },
    "o1": {
        "forced_temperature": 1.0,
    },
    "o3": {
        "forced_temperature": 1.0,
    },
}


def get_capability(
    binding: str,
    capability: str,
    model: Optional[str] = None,
    default: Any = None,
) -> Any:
    """
    Get a capability value for a provider/model combination.

    Checks in order:
    1. Model-specific overrides (matched by prefix)
    2. Provider/binding capabilities
    3. Default capabilities for unknown providers
    4. Explicit default value

    Args:
        binding: Provider binding name (e.g., "openai", "anthropic", "deepseek")
        capability: Capability name (e.g., "supports_response_format")
        model: Optional model name for model-specific overrides
        default: Default value if capability is not defined

    Returns:
        Capability value or default
    """
    binding_lower = (binding or "openai").lower()

    # 1. Check model-specific overrides first
    if model:
        model_lower = model.lower()
        # Sort by pattern length descending to match most specific first
        for pattern, overrides in sorted(MODEL_OVERRIDES.items(), key=lambda x: -len(x[0])):
            if model_lower.startswith(pattern):
                if capability in overrides:
                    return overrides[capability]

    # 2. Check provider capabilities
    provider_caps = PROVIDER_CAPABILITIES.get(binding_lower, {})
    if capability in provider_caps:
        return provider_caps[capability]

    # 3. Check default capabilities for unknown providers
    if capability in DEFAULT_CAPABILITIES:
        return DEFAULT_CAPABILITIES[capability]

    # 4. Return explicit default
    return default


def supports_response_format(binding: str, model: Optional[str] = None) -> bool:
    """
    Check if the provider/model supports response_format parameter.

    This is a convenience function for the most common capability check.

    Args:
        binding: Provider binding name
        model: Optional model name for model-specific overrides

    Returns:
        True if response_format is supported
    """
    return get_capability(binding, "supports_response_format", model, default=True)


def supports_streaming(binding: str, model: Optional[str] = None) -> bool:
    """
    Check if the provider/model supports streaming responses.

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if streaming is supported
    """
    return get_capability(binding, "supports_streaming", model, default=True)


def system_in_messages(binding: str, model: Optional[str] = None) -> bool:
    """
    Check if system prompt should be in messages array (OpenAI style)
    or as a separate parameter (Anthropic style).

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if system prompt goes in messages array
    """
    return get_capability(binding, "system_in_messages", model, default=True)


def has_thinking_tags(binding: str, model: Optional[str] = None) -> bool:
    """
    Check if the model output may contain thinking tags (<think>...</think>).

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if thinking tags should be filtered
    """
    return get_capability(binding, "has_thinking_tags", model, default=False)


def supports_tools(binding: str, model: Optional[str] = None) -> bool:
    """
    Check if the provider/model supports function calling / tools.

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if tools/function calling is supported
    """
    return get_capability(binding, "supports_tools", model, default=False)


def requires_api_version(binding: str, model: Optional[str] = None) -> bool:
    """
    Check if the provider requires an API version parameter (e.g., Azure OpenAI).

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if api_version is required
    """
    return get_capability(binding, "requires_api_version", model, default=False)


def get_effective_temperature(
    binding: str,
    model: Optional[str] = None,
    requested_temp: float = 0.7,
) -> float:
    """
    Get the effective temperature value for a model.

    Some models (e.g., o1, o3, gpt-5) only support a fixed temperature value (1.0).
    This function returns the forced temperature if defined, otherwise the requested value.

    Args:
        binding: Provider binding name
        model: Optional model name for model-specific overrides
        requested_temp: The temperature value requested by the caller (default: 0.7)

    Returns:
        The effective temperature to use for the API call
    """
    forced_temp = get_capability(binding, "forced_temperature", model)
    if forced_temp is not None:
        return forced_temp
    return requested_temp


__all__ = [
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
    "get_effective_temperature",]
