"""HTTP client helpers for OpenAI-compatible SDK providers."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import httpx

from deeptutor.services.config import load_system_settings
from deeptutor.services.llm.exceptions import LLMConfigError

logger = logging.getLogger(__name__)

_warning_lock = threading.Lock()
_warning_logged = False


def disable_ssl_verify_enabled() -> bool:
    """Return whether outbound TLS verification should be disabled."""
    if not load_system_settings()["disable_ssl_verify"]:
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


_sanitized_lock = threading.Lock()
_sanitized_warned: set[str] = set()

# httpx passes these OpenSSL paths to ssl.create_default_context, which raises
# FileNotFoundError when a path has gone stale after a conda env is cloned or
# moved without ca-certificates.
_SSL_CA_ENV_PATHS: tuple[tuple[str, str], ...] = (
    ("SSL_CERT_FILE", "file"),
    ("SSL_CERT_DIR", "directory"),
)


def sanitize_invalid_ssl_env() -> list[str]:
    """Remove CA-bundle env vars that point at non-existent paths.

    Returns the names of removed variables. The operation is idempotent and
    thread-safe, and each stale variable is warned about at most once.
    """
    removed: list[str] = []
    warnings: list[tuple[str, str]] = []
    with _sanitized_lock:
        for name, kind in _SSL_CA_ENV_PATHS:
            value = os.environ.get(name)
            if not value:
                continue
            path_exists = os.path.isfile(value) if kind == "file" else os.path.isdir(value)
            if path_exists:
                continue
            os.environ.pop(name, None)
            removed.append(name)
            if name not in _sanitized_warned:
                _sanitized_warned.add(name)
                warnings.append((name, kind))
    for name, kind in warnings:
        _warn_stale_ca_var(name, kind=kind)
    return removed


def _warn_stale_ca_var(name: str, *, kind: str) -> None:
    logger.warning(
        "%s points to a missing %s; clearing it so TLS falls back to the "
        "default CA bundle. If this is a conda environment, reinstalling "
        "ca-certificates regenerates the bundle.",
        name,
        kind,
    )


def build_openai_http_client(**kwargs: Any) -> httpx.AsyncClient | None:
    """Build a custom SDK httpx client when DISABLE_SSL_VERIFY is enabled."""
    sanitize_invalid_ssl_env()
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
    "sanitize_invalid_ssl_env",
]
