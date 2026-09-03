"""Model discovery for hosted OpenAI-compatible and Anthropic endpoints.

Chat traffic goes through :mod:`deeptutor.services.llm.factory` and the
``provider_core`` classes; this module only lists what an endpoint serves.
``complete`` / ``stream`` remain as deprecated shims for out-of-tree callers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
import logging
import threading
from typing import Any, cast
import warnings

import aiohttp

from deeptutor.services.config import load_system_settings
from deeptutor.services.provider_registry import effective_backend, find_by_name

from .utils import build_auth_headers, collect_model_names

logger = logging.getLogger(__name__)

# Thread-safe lock for SSL-warning state
_ssl_warning_lock = threading.Lock()
# Use lowercase to avoid constant redefinition warning
_ssl_warning_logged = False


def _get_aiohttp_connector() -> aiohttp.TCPConnector | None:
    """
    Build an optional aiohttp connector with SSL verification disabled.

    Returns:
        A TCPConnector with SSL verification disabled when DISABLE_SSL_VERIFY
        is truthy; otherwise None to use aiohttp defaults.
    """
    global _ssl_warning_logged

    # Thread-safe check and one-time warning emission
    disable_flag = bool(load_system_settings()["disable_ssl_verify"])
    if not disable_flag:
        return None

    # Emit warning once across threads
    with _ssl_warning_lock:
        if not _ssl_warning_logged:
            logger.warning(
                "SSL verification is disabled via DISABLE_SSL_VERIFY. This is unsafe and must "
                "not be used in production environments."
            )
            _ssl_warning_logged = True
    return aiohttp.TCPConnector(ssl=False)


def _auth_binding(binding: str, api_format: str) -> str:
    """The header style ``/models`` needs: Anthropic Messages endpoints take
    ``x-api-key`` whatever vendor name the profile carries."""
    if effective_backend(find_by_name(binding), api_format) == "anthropic":
        return "anthropic"
    return binding


async def fetch_models(
    base_url: str,
    api_key: str | None = None,
    binding: str = "openai",
    api_format: str = "auto",
) -> list[str]:
    """
    Fetch available models from cloud provider.

    Args:
        base_url: API endpoint URL
        api_key: API key
        binding: Provider type (openai, anthropic)
        api_format: The profile's API format; decides the auth header style

    Returns:
        List of available model names
    """
    binding = binding.lower()
    base_url = base_url.rstrip("/")

    # Build headers using unified utility
    headers = build_auth_headers(api_key, _auth_binding(binding, api_format))
    # Remove Content-Type for GET request
    headers.pop("Content-Type", None)

    timeout = aiohttp.ClientTimeout(total=30)
    connector = _get_aiohttp_connector()
    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector, trust_env=True
    ) as session:
        try:
            url = f"{base_url}/models"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    if isinstance(payload, Mapping):
                        mapping = cast(Mapping[str, object], payload)
                        items = mapping.get("data")
                        if isinstance(items, list):
                            return collect_model_names(cast(list[object], items))
                    elif isinstance(payload, list):
                        return collect_model_names(cast(list[object], payload))
            return []
        except Exception as e:
            logger.error("Error fetching models from %s: %s", base_url, e)
            return []


def _warn_deprecated(name: str) -> None:
    warnings.warn(
        f"deeptutor.services.llm.cloud_provider.{name} is deprecated; "
        "use deeptutor.services.llm.complete / stream",
        DeprecationWarning,
        stacklevel=3,
    )


async def complete(prompt: str, **kwargs: Any) -> str:
    """Deprecated: forwards to :func:`deeptutor.services.llm.factory.complete`."""
    _warn_deprecated("complete")
    from . import factory

    return await factory.complete(prompt, **kwargs)


async def stream(prompt: str, **kwargs: Any) -> AsyncGenerator[str, None]:
    """Deprecated: forwards to :func:`deeptutor.services.llm.factory.stream`."""
    _warn_deprecated("stream")
    from . import factory

    async for chunk in factory.stream(prompt, **kwargs):
        yield chunk


__all__ = [
    "complete",
    "stream",
    "fetch_models",
]
