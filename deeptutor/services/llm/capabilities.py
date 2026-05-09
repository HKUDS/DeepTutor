"""
Provider Capabilities
=====================

Centralized configuration for LLM provider capabilities.
This replaces scattered hardcoded checks throughout the codebase.

Usage:
    from deeptutor.services.llm.capabilities import get_capability, supports_response_format

    # Check if a provider supports response_format
    if supports_response_format(binding, model):
        kwargs["response_format"] = {"type": "json_object"}

    # Generic capability check
    if get_capability(binding, "streaming", default=True):
        # use streaming
"""

# Provider capabilities configuration
# Keys are binding names (lowercase), values are capability dictionaries
PROVIDER_CAPABILITIES: dict[str, dict[str, object]] = {
    # OpenAI and OpenAI-compatible providers
    "openai": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "system_in_messages": True,  # System prompt goes in messages array
        "newer_models_use_max_completion_tokens": True,
    },
    "azure_openai": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "system_in_messages": True,
        "newer_models_use_max_completion_tokens": True,
        "requires_api_version": True,
    },
    # Anthropic
    "anthropic": {
        "supports_response_format": False,  # Anthropic uses different format
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "vision_url_supported": False,  # Our adapter only emits base64 image source
        "system_in_messages": False,  # System is a separate parameter
        "has_thinking_tags": False,
    },
    "claude": {  # Alias for anthropic
        "supports_response_format": False,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "vision_url_supported": False,
        "system_in_messages": False,
        "has_thinking_tags": False,
    },
    # DeepSeek
    "deepseek": {
        "supports_response_format": False,  # DeepSeek doesn't support strict JSON schema yet
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": False,
        "system_in_messages": True,
        "has_thinking_tags": True,  # DeepSeek reasoner has thinking tags
    },
    # OpenRouter (aggregator, generally OpenAI-compatible)
    "openrouter": {
        "supports_response_format": True,  # Depends on underlying model
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,  # Depends on underlying model
        "system_in_messages": True,
    },
    # Groq (fast inference)
    "groq": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "system_in_messages": True,
    },
    # Together AI
    "together": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "system_in_messages": True,
    },
    "together_ai": {  # Alias
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "system_in_messages": True,
    },
    # Mistral
    "mistral": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
        "system_in_messages": True,
    },
    # Moonshot / Kimi — vision is per-model (see MODEL_OVERRIDES below).
    # Per the official docs the image input must be base64-encoded inline; URL
    # form is rejected. We therefore force the multimodal layer to resolve any
    # url-only attachment to bytes before sending.
    "moonshot": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": False,
        "vision_url_supported": False,
        "system_in_messages": True,
    },
    # Local providers (generally OpenAI-compatible)
    "ollama": {
        "supports_response_format": True,  # Ollama supports JSON mode
        "supports_streaming": True,
        "supports_tools": False,  # Limited tool support
        "supports_vision": False,  # Depends on model; set True via model overrides
        "system_in_messages": True,
    },
    "lm_studio": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "system_in_messages": True,
    },
    "vllm": {
        "supports_response_format": True,
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "system_in_messages": True,
    },
    "llama_cpp": {
        "supports_response_format": True,  # llama.cpp server supports JSON grammar
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
        "system_in_messages": True,
    },
}

# Default capabilities for unknown providers (assume OpenAI-compatible)
DEFAULT_CAPABILITIES: dict[str, object] = {
    "supports_response_format": True,
    "supports_streaming": True,
    "supports_tools": False,
    "supports_vision": False,
    "vision_url_supported": True,  # Most OpenAI-compat providers accept image_url URLs
    "system_in_messages": True,
    "has_thinking_tags": False,
    "forced_temperature": None,  # None means no forced value, use requested temperature
}

# Model-specific overrides
# Format: {model_pattern: {capability: value}}
# Patterns are matched with case-insensitive startswith
MODEL_OVERRIDES: dict[str, dict[str, object]] = {
    "deepseek": {
        "supports_response_format": False,
        "has_thinking_tags": True,
        "supports_vision": False,
    },
    "deepseek-reasoner": {
        "supports_response_format": False,
        "has_thinking_tags": True,
        "supports_vision": False,
    },
    "qwen": {
        "has_thinking_tags": True,
        "supports_vision": True,
    },
    "qwq": {
        "has_thinking_tags": True,
    },
    "minimax": {
        "supports_response_format": False,
    },
    # NOTE: supports_response_format and system_in_messages are binding-level
    # capabilities, NOT model-level. When using OpenRouter or other OpenAI-compatible
    # proxies (binding="openai"), they handle response_format translation and expect
    # system prompts in messages. The native Anthropic limitations are already
    # handled by PROVIDER_CAPABILITIES["anthropic"] / ["claude"] above.
    # Only model-intrinsic capabilities (like has_thinking_tags) belong here.
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
    # Vision-capable model families
    "gpt-4o": {"supports_vision": True},
    "gpt-4-turbo": {"supports_vision": True},
    "gpt-4-vision": {"supports_vision": True},
    "claude-3": {"supports_vision": True},
    "claude-4": {"supports_vision": True},
    "gemini": {"supports_vision": True},
    "gemma": {"supports_vision": False, "supports_response_format": False},
    "llava": {"supports_vision": True},
    "bakllava": {"supports_vision": True},
    "moondream": {"supports_vision": True},
    "minicpm-v": {"supports_vision": True},
    "gpt-3.5": {"supports_vision": False},
    # Moonshot / Kimi vision models
    # https://platform.kimi.com/docs/guide/use-kimi-vision-model
    "moonshot-v1-8k-vision": {"supports_vision": True},
    "moonshot-v1-32k-vision": {"supports_vision": True},
    "moonshot-v1-128k-vision": {"supports_vision": True},
    "kimi-k2.5": {"supports_vision": True},
    "kimi-k2.6": {"supports_vision": True},
}


def get_capability(
    binding: str,
    capability: str,
    model: str | None = None,
    default: object = None,
) -> object:
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


# Runtime cache for response_format incompatibilities discovered at request time.
# Keyed by (binding_lower, model_lower). Populated when a provider rejects a
# request with response_format={"type": "json_object"} (commonly LM Studio /
# Ollama serving Gemma/Qwen-style models that only accept "json_schema" or "text").
# Once a pair is recorded here, subsequent calls skip response_format entirely
# instead of paying the cost of a failed request + retry.
_RUNTIME_DISABLED_RESPONSE_FORMAT: set[tuple[str, str]] = set()


def disable_response_format_at_runtime(binding: str | None, model: str | None) -> None:
    """Mark a (binding, model) pair as not supporting ``response_format``.

    Subsequent calls to :func:`supports_response_format` for the same pair
    will return ``False`` without re-checking the static configuration. This
    is useful when a provider unexpectedly rejects ``response_format`` at
    runtime (e.g. LM Studio + ``gemma-4-e2b`` returning
    ``"'response_format.type' must be 'json_schema' or 'text'"``).
    """
    if not binding or not model:
        return
    _RUNTIME_DISABLED_RESPONSE_FORMAT.add((binding.lower(), model.lower()))


def is_response_format_disabled_at_runtime(binding: str | None, model: str | None) -> bool:
    """Return True if (binding, model) was disabled via :func:`disable_response_format_at_runtime`."""
    if not binding or not model:
        return False
    return (binding.lower(), model.lower()) in _RUNTIME_DISABLED_RESPONSE_FORMAT


def supports_response_format(binding: str, model: str | None = None) -> bool:
    """
    Check if the provider/model supports response_format parameter.

    This is a convenience function for the most common capability check.
    A runtime override (set via :func:`disable_response_format_at_runtime`)
    always wins over static capability configuration.

    Args:
        binding: Provider binding name
        model: Optional model name for model-specific overrides

    Returns:
        True if response_format is supported
    """
    if is_response_format_disabled_at_runtime(binding, model):
        return False
    value = get_capability(binding, "supports_response_format", model, default=True)
    return bool(value)


def supports_streaming(binding: str, model: str | None = None) -> bool:
    """
    Check if the provider/model supports streaming responses.

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if streaming is supported
    """
    value = get_capability(binding, "supports_streaming", model, default=True)
    return bool(value)


def system_in_messages(binding: str, model: str | None = None) -> bool:
    """
    Check if system prompt should be in messages array (OpenAI style)
    or as a separate parameter (Anthropic style).

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if system prompt goes in messages array
    """
    value = get_capability(binding, "system_in_messages", model, default=True)
    return bool(value)


def has_thinking_tags(binding: str, model: str | None = None) -> bool:
    """
    Check if the model output may contain thinking tags (<think>...</think>).

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if thinking tags should be filtered
    """
    value = get_capability(binding, "has_thinking_tags", model, default=False)
    return bool(value)


def supports_tools(binding: str, model: str | None = None) -> bool:
    """
    Check if the provider/model supports function calling / tools.

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if tools/function calling is supported
    """
    value = get_capability(binding, "supports_tools", model, default=False)
    return bool(value)


def supports_vision(binding: str, model: str | None = None) -> bool:
    """
    Check if the provider/model supports multimodal (image) input.

    Args:
        binding: Provider binding name
        model: Optional model name for model-specific overrides

    Returns:
        True if the model can accept image content in messages
    """
    value = get_capability(binding, "supports_vision", model, default=False)
    return bool(value)


def supports_vision_url(binding: str, model: str | None = None) -> bool:
    """Whether the provider accepts remote URL image references.

    Some providers (Moonshot, our Anthropic adapter) only accept inline
    base64-encoded image bytes. The multimodal layer consults this flag to
    decide whether url-only attachments need to be resolved to bytes before
    being forwarded.
    """
    value = get_capability(binding, "vision_url_supported", model, default=True)
    return bool(value)


def requires_api_version(binding: str, model: str | None = None) -> bool:
    """
    Check if the provider requires an API version parameter (e.g., Azure OpenAI).

    Args:
        binding: Provider binding name
        model: Optional model name

    Returns:
        True if api_version is required
    """
    value = get_capability(binding, "requires_api_version", model, default=False)
    return bool(value)


def get_effective_temperature(
    binding: str,
    model: str | None = None,
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
    if isinstance(forced_temp, (int, float)):
        return float(forced_temp)
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
    "supports_vision",
    "requires_api_version",
    "get_effective_temperature",
    "disable_response_format_at_runtime",
    "is_response_format_disabled_at_runtime",
]
