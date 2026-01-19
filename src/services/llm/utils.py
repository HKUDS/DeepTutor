# -*- coding: utf-8 -*-
"""
LLM Utilities
=============

Utility functions for LLM service:
- URL handling for local and cloud servers
- Response content extraction
- Thinking tags cleaning
"""

import re
from typing import Any, Optional

# Known cloud provider domains (should never be treated as local)
CLOUD_DOMAINS = [
    ".openai.com",
    ".anthropic.com",
    ".deepseek.com",
    ".openrouter.ai",
    ".azure.com",
    ".googleapis.com",
    ".cohere.ai",
    ".mistral.ai",
    ".together.ai",
    ".fireworks.ai",
    ".groq.com",
    ".perplexity.ai",
]

# Common local server ports
LOCAL_PORTS = [
    ":1234",  # LM Studio
    ":11434",  # Ollama
    ":8000",  # vLLM
    ":8080",  # llama.cpp
    ":5000",  # Common dev port
    ":3000",  # Common dev port
    ":8001",  # Alternative vLLM
    ":5001",  # Alternative dev port
]

# Local hostname indicators
LOCAL_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]

# Ports that need /v1 suffix for OpenAI compatibility
V1_SUFFIX_PORTS = {
    ":11434",  # Ollama
    ":1234",  # LM Studio
    ":8000",  # vLLM
    ":8001",  # Alternative vLLM
    ":8080",  # llama.cpp
}


def is_local_llm_server(base_url: str) -> bool:
    """
    Check if the given URL points to a local LLM server.

    Detects local servers by:
    1. Checking for local hostnames (localhost, 127.0.0.1, 0.0.0.0)
    2. Checking for common local LLM server ports
    3. Excluding known cloud provider domains

    Args:
        base_url: The base URL to check

    Returns:
        True if the URL appears to be a local LLM server
    """
    if not base_url:
        return False

    base_url_lower = base_url.lower()

    # First, exclude known cloud providers
    for domain in CLOUD_DOMAINS:
        if domain in base_url_lower:
            return False

    # Check for local hostname indicators
    for host in LOCAL_HOSTS:
        if host in base_url_lower:
            return True

    # Check for common local server ports
    for port in LOCAL_PORTS:
        if port in base_url_lower:
            return True

    return False


def _needs_v1_suffix(url: str) -> bool:
    """
    Check if the URL needs /v1 suffix for OpenAI compatibility.

    Most local LLM servers (Ollama, LM Studio, vLLM, llama.cpp) expose
    OpenAI-compatible endpoints at /v1.

    Args:
        url: The URL to check

    Returns:
        True if /v1 should be appended
    """
    if not url:
        return False

    url_lower = url.lower()

    # Skip if already has /v1
    if url_lower.endswith("/v1"):
        return False

    # Only add /v1 for local servers with known ports that need it
    if not is_local_llm_server(url):
        return False

    # Check if URL contains any port that needs /v1 suffix
    # Also check for "ollama" in URL (but not ollama.com cloud service)
    is_ollama = "ollama" in url_lower and "ollama.com" not in url_lower
    if is_ollama:
        return True

    return any(port in url_lower for port in V1_SUFFIX_PORTS)


def sanitize_url(base_url: str, model: str = "") -> str:
    """
    Sanitize base URL for OpenAI-compatible APIs, with special handling for local LLM servers.

    Handles:
    - Ollama (port 11434)
    - LM Studio (port 1234)
    - vLLM (port 8000)
    - llama.cpp (port 8080)
    - Other localhost OpenAI-compatible servers

    Args:
        base_url: The base URL to sanitize
        model: Optional model name (unused, kept for API compatibility)

    Returns:
        Sanitized URL string
    """
    if not base_url:
        return base_url

    url = base_url.rstrip("/")

    # Ensure URL has a protocol (default to http for local servers)
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url

    # Standard OpenAI client library is strict about URLs:
    # - No trailing slashes
    # - No /chat/completions or /completions/messages/embeddings suffixes
    #   (it adds these automatically)
    for suffix in ["/chat/completions", "/completions", "/messages", "/embeddings"]:
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            url = url.rstrip("/")

    # For local LLM servers, ensure /v1 is present for OpenAI compatibility
    if _needs_v1_suffix(url):
        url = url.rstrip("/") + "/v1"

    return url


def clean_thinking_tags(
    content: str,
    binding: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """
    Remove thinking tags from model output.

    Some reasoning models (DeepSeek, Qwen, etc.) include <think>...</think> blocks
    that should be stripped from the final response.

    Args:
        content: Raw model output
        binding: Provider binding name (optional, for capability check)
        model: Model name (optional, for capability check)

    Returns:
        Cleaned content without thinking tags
    """
    if not content:
        return content

    # Check if model produces thinking tags (if binding/model provided)
    if binding:
        # Lazy import to avoid circular dependency
        from .capabilities import has_thinking_tags

        if not has_thinking_tags(binding, model):
            return content

    # Remove <think>...</think> blocks
    if "<think>" in content:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)

    return content.strip()


def build_chat_url(
    base_url: str,
    api_version: Optional[str] = None,
    binding: Optional[str] = None,
) -> str:
    """
    Build the full chat completions endpoint URL.

    Handles:
    - Adding /chat/completions suffix for OpenAI-compatible endpoints
    - Adding /messages suffix for Anthropic endpoints
    - Adding api-version query parameter for Azure OpenAI

    Args:
        base_url: Base URL (should be sanitized first)
        api_version: API version for Azure OpenAI (optional)
        binding: Provider binding name (optional, for Anthropic detection)

    Returns:
        Full endpoint URL
    """
    if not base_url:
        return base_url

    url = base_url.rstrip("/")

    # Anthropic uses /messages endpoint
    binding_lower = (binding or "").lower()
    if binding_lower in ["anthropic", "claude"]:
        if not url.endswith("/messages"):
            url += "/messages"
    else:
        # OpenAI-compatible endpoints use /chat/completions
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"

    # Add api-version for Azure OpenAI
    if api_version:
        separator = "&" if "?" in url else "?"
        url += f"{separator}api-version={api_version}"

    return url


def extract_response_content(message: dict[str, Any]) -> str:
    """
    Extract content from LLM response message.

    Handles different response formats from various models:
    - Standard content field
    - Reasoning models that use reasoning_content, reasoning, or thought fields

    Args:
        message: Message dict from LLM response (e.g., choices[0].message)

    Returns:
        Extracted content string
    """
    if not message:
        return ""

    content = message.get("content", "")

    # Handle reasoning models that return content in different fields
    if not content:
        content = (
            message.get("reasoning_content")
            or message.get("reasoning")
            or message.get("thought")
            or ""
        )

    return content


def build_auth_headers(
    api_key: Optional[str],
    binding: Optional[str] = None,
) -> dict[str, str]:
    """
    Build authentication headers for LLM API requests.

    Args:
        api_key: API key
        binding: Provider binding name (for provider-specific headers)

    Returns:
        Headers dict
    """
    headers = {"Content-Type": "application/json"}

    if not api_key:
        return headers

    binding_lower = (binding or "").lower()

    if binding_lower in ["anthropic", "claude"]:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif binding_lower == "azure_openai":
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


__all__ = [
    # URL utilities
    "sanitize_url",
    "is_local_llm_server",
    "build_chat_url",
    "build_auth_headers",
    # Content utilities
    "clean_thinking_tags",
    "extract_response_content",
    # Constants
    "CLOUD_DOMAINS",
    "LOCAL_PORTS",
    "LOCAL_HOSTS",
    "V1_SUFFIX_PORTS",
]
