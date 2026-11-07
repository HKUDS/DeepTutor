# -*- coding: utf-8 -*-
"""
LLM Utilities
=============

Shared helpers for URL handling, response parsing, and content cleanup.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import ipaddress
import os
import re
from urllib.parse import urlparse

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

LOCAL_PORTS = [
    ":1234",
    ":11434",
    ":8000",
    ":8080",
    ":5000",
    ":3000",
    ":8001",
    ":5001",
]

LOCAL_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # nosec B104
]

V1_SUFFIX_PORTS = {
    ":11434",
    ":1234",
    ":8000",
    ":8001",
    ":8080",
}


def is_local_llm_server(base_url: str, allow_private: bool | None = None) -> bool:
    """
    Determine whether a URL points to a local LLM server.

    Args:
        base_url: URL to inspect.
        allow_private: Optional override to treat private IPs as local.

    Returns:
        True when the URL looks local.
    """
    if not base_url:
        return False

    if allow_private is None:
        env_value = os.environ.get("LLM_TREAT_PRIVATE_AS_LOCAL")
        if env_value is not None:
            allow_private = env_value.strip().lower() in ("1", "true", "yes")

    base_url_lower = base_url.lower()
    if any(domain in base_url_lower for domain in CLOUD_DOMAINS):
        return False

    parsed = urlparse(base_url)
    hostname = parsed.hostname or parsed.netloc
    if not hostname:
        hostname = base_url

    hostname_lower = hostname.lower()
    if any(host in hostname_lower for host in LOCAL_HOSTS):
        return True

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback:
            return True
        if allow_private and ip.is_private:
            return True
    except ValueError:
        pass

    return any(port in base_url_lower for port in LOCAL_PORTS)


def _needs_v1_suffix(base_url: str) -> bool:
    """Return True when base_url should receive a /v1 suffix."""
    return any(port in base_url for port in V1_SUFFIX_PORTS) and not base_url.endswith("/v1")


def sanitize_url(base_url: str, model: str = "") -> str:
    """
    Sanitize a base URL, normalizing scheme and removing known endpoints.

    Args:
        base_url: Base URL.
        model: Unused (kept for API compatibility).

    Returns:
        Sanitized base URL.
    """
    if not base_url:
        return ""

    if not re.match(r"^[a-zA-Z]+://", base_url):
        base_url = f"http://{base_url}"

    url = base_url.rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "http://" + url

    for suffix in [
        "/chat/completions",
        "/completions",
        "/messages",
        "/embeddings",
    ]:
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")

    if _needs_v1_suffix(url):
        url = url.rstrip("/") + "/v1"

    return url


def clean_thinking_tags(
    content: str,
    binding: str | None = None,
    model: str | None = None,
) -> str:
    """Remove <think> tags from model output."""
    if not content:
        return ""

    pattern = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(pattern, "", content)
    return cleaned.strip()


def build_chat_url(
    base_url: str,
    api_version: str | None = None,
    binding: str | None = None,
) -> str:
    """Build a chat-completions endpoint URL."""
    base_url = base_url.rstrip("/")
    binding_lower = (binding or "openai").lower()

    if binding_lower in {"anthropic", "claude"}:
        url = f"{base_url}/messages"
    elif binding_lower == "cohere":
        url = f"{base_url}/chat"
    else:
        url = f"{base_url}/chat/completions"

    if api_version:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}api-version={api_version}"

    return url


def build_completion_url(
    base_url: str,
    api_version: str | None = None,
    binding: str | None = None,
) -> str:
    """Build a legacy completions endpoint URL."""
    if not base_url:
        return base_url

    url = base_url.rstrip("/")
    binding_lower = (binding or "").lower()
    if binding_lower in {"anthropic", "claude"}:
        raise ValueError("Anthropic does not support /completions endpoint")

    if not url.endswith("/completions"):
        url += "/completions"

    if api_version:
        separator = "&" if "?" in url else "?"
        url += f"{separator}api-version={api_version}"

    return url


def extract_response_content(message: object) -> str:
    """Extract textual content from response payloads."""
    if message is None:
        return ""

    if isinstance(message, str):
        return message

    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, Mapping) and "text" in part:
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
            return "".join(parts)
        if content is not None:
            return str(content)
        if "text" in message:
            return str(message["text"])

    return str(message)


def _normalize_model_name(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, Mapping):
        for key in ("id", "name", "model"):
            value = entry.get(key)
            if isinstance(value, str):
                return value
    return None


def collect_model_names(entries: Sequence[object]) -> list[str]:
    """Collect model names from provider payloads."""
    names: list[str] = []
    for entry in entries:
        name = _normalize_model_name(entry)
        if name:
            names.append(name)
    return names


def build_auth_headers(api_key: str | None, binding: str | None = None) -> dict[str, str]:
    """Build auth headers for provider requests."""
    headers = {"Content-Type": "application/json"}

    if not api_key:
        return headers

    binding_lower = (binding or "").lower()
    if binding_lower in {"anthropic", "claude"}:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif binding_lower in {"azure_openai", "azure"}:
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


__all__ = [
    "sanitize_url",
    "is_local_llm_server",
    "build_chat_url",
    "build_completion_url",
    "build_auth_headers",
    "collect_model_names",
    "clean_thinking_tags",
    "extract_response_content",
    "CLOUD_DOMAINS",
    "LOCAL_PORTS",
    "LOCAL_HOSTS",
    "V1_SUFFIX_PORTS",
]
