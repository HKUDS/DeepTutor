"""HTTP client helpers for OpenAI-compatible SDK providers."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import httpx

from deeptutor.services.llm.exceptions import LLMConfigError

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
_warning_lock = threading.Lock()
_warning_logged = False


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY


def disable_ssl_verify_enabled() -> bool:
    """Return whether outbound TLS verification should be disabled."""
    if not _env_truthy("DISABLE_SSL_VERIFY"):
        return False
    if os.getenv("ENVIRONMENT", "").strip().lower() in {"prod", "production"}:
        raise LLMConfigError("DISABLE_SSL_VERIFY is not allowed in production")
    global _warning_logged
    with _warning_lock:
        if not _warning_logged:
            logger.warning(
                "SSL verification is disabled via DISABLE_SSL_VERIFY. This is unsafe "
                "and must not be used in production environments."
            )
            _warning_logged = True
    return True


def build_openai_http_client(**kwargs: Any) -> httpx.AsyncClient | None:
    """Build a custom SDK httpx client when DISABLE_SSL_VERIFY is enabled."""
    if not disable_ssl_verify_enabled():
        return None
    return httpx.AsyncClient(verify=False, **kwargs)  # nosec B501


def openai_client_kwargs(**httpx_kwargs: Any) -> dict[str, httpx.AsyncClient]:
    """Return kwargs to pass into ``AsyncOpenAI`` for custom HTTP behavior."""
    client = build_openai_http_client(**httpx_kwargs)
    return {"http_client": client} if client is not None else {}


__all__ = [
    "build_openai_http_client",
    "disable_ssl_verify_enabled",
    "openai_client_kwargs",
]
