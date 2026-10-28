"""Provider admission for native execution, before any turn effects begin."""

from __future__ import annotations

import os
from typing import Any

from deeptutor.services.provider_registry import effective_backend, find_by_name


def compatibility_reason(config: Any) -> str:
    from deeptutor.services.provider_registry import wire_api_for_provider

    spec = find_by_name(config.binding)
    if config.provider_mode != "standard":
        return "managed provider authentication"
    if effective_backend(spec, config.api_format) != "openai_compat":
        return "native provider wire format"
    if wire_api_for_provider(config.wire_api, spec) == "responses":
        return "Responses API"
    if isinstance(config.api_key, list) and len(config.api_key) > 1:
        return "API key pool"
    if (
        "azure" in str(config.binding).lower()
        or ".openai.azure.com" in str(config.effective_url)
        or (config.binding == "openai" and config.api_version)
    ):
        return "Azure deployment authentication"
    # The lean Node transport deliberately has no proxy/custom-CA machinery.
    # Select compatibility before effects instead of silently ignoring settings.
    if any(
        os.getenv(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        )
    ):
        return "custom proxy or certificate configuration"
    from deeptutor.services.config import load_system_settings

    if load_system_settings()["disable_ssl_verify"]:
        return "custom TLS configuration"
    return ""


def provider_config(config: Any, completion: dict[str, Any]) -> dict[str, Any]:
    from deeptutor.services.llm.capabilities import supports_streaming

    reason = compatibility_reason(config)
    if reason:
        raise ValueError(f"Provider requires compatibility execution: {reason}")
    endpoint = str(config.effective_url or config.base_url or "").rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    completion = dict(completion)
    completion.update(completion.pop("extra_body", {}) or {})
    return {
        "endpoint": endpoint,
        "apiKey": config.get_api_key(),
        "headers": dict(config.extra_headers or {}),
        "model": config.model,
        "format": "chat_completions",
        "completion": completion,
        "stream": supports_streaming(config.binding, config.model),
        "maxConcurrency": config.max_concurrency,
        "requestsPerMinute": config.requests_per_minute,
    }
