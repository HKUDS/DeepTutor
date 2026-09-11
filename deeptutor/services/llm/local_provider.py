"""Model discovery for local OpenAI-compatible servers (Ollama, LM Studio, vLLM, llama.cpp).

Chat traffic goes through :mod:`deeptutor.services.llm.factory` and the
``provider_core`` classes; this module only lists what a local server serves.
``complete`` / ``stream`` remain as deprecated shims for out-of-tree callers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
import logging
from typing import Any
import warnings

import aiohttp

from .utils import build_auth_headers, collect_model_names

logger = logging.getLogger(__name__)


async def fetch_models(
    base_url: str,
    api_key: str | None = None,
) -> list[str]:
    """
    Fetch available models from local LLM server.

    Supports:
    - Ollama (/api/tags)
    - OpenAI-compatible (/models)

    Args:
        base_url: Base URL for the local server
        api_key: API key (optional)

    Returns:
        List of available model names
    """
    base_url = base_url.rstrip("/")

    # Build headers using unified utility
    headers = build_auth_headers(api_key)
    # Remove Content-Type for GET request
    headers.pop("Content-Type", None)

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Try Ollama /api/tags first
        is_ollama = ":11434" in base_url or "ollama" in base_url.lower()
        if is_ollama:
            try:
                ollama_url = base_url.replace("/v1", "") + "/api/tags"
                async with session.get(ollama_url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "models" in data:
                            return collect_model_names(data["models"])
            except Exception as exc:
                logger.debug(
                    "Failed to fetch Ollama models from %s: %s",
                    base_url,
                    exc,
                )

        # Try OpenAI-compatible /models
        try:
            models_url = f"{base_url}/models"
            async with session.get(models_url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    # Handle different response formats
                    if "data" in data and isinstance(data["data"], list):
                        return collect_model_names(data["data"])
                    elif "models" in data and isinstance(data["models"], list):
                        return collect_model_names(data["models"])
                    elif isinstance(data, list):
                        return collect_model_names(data)
        except Exception as e:
            logger.error("Error fetching models from %s: %s", base_url, e)

        return []


def _warn_deprecated(name: str) -> None:
    warnings.warn(
        f"deeptutor.services.llm.local_provider.{name} is deprecated; "
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
