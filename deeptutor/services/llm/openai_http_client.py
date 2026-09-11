"""HTTP client helpers for OpenAI-compatible SDK providers."""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING, Any
import uuid

import httpx

from deeptutor.services.config import load_system_settings
from deeptutor.services.llm.exceptions import LLMConfigError

if TYPE_CHECKING:
    from deeptutor.services.provider_registry import ProviderSpec

logger = logging.getLogger(__name__)

# OpenRouter attributes traffic to an app by these headers; sent whenever the
# endpoint is theirs, whatever binding the profile was typed under.
OPENROUTER_ATTRIBUTION_HEADERS: dict[str, str] = {
    "HTTP-Referer": "https://github.com/HKUDS/DeepTutor",
    "X-OpenRouter-Title": "DeepTutor",
}

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


def _uses_openrouter(spec: "ProviderSpec | None", api_base: str | None) -> bool:
    if spec is not None and spec.name == "openrouter":
        return True
    return bool(api_base and "openrouter" in api_base.lower())


def openai_sdk_client_kwargs(
    *,
    api_key: str | None,
    base_url: str | None,
    extra_headers: dict[str, str] | None = None,
    spec: "ProviderSpec | None" = None,
    disable_ssl_verify: bool | None = None,
    sdk_max_retries: int | None = None,
    session_affinity: bool = True,
) -> dict[str, Any]:
    """Constructor kwargs for ``AsyncOpenAI`` / ``AsyncAzureOpenAI``.

    The one place that decides what every OpenAI-SDK client DeepTutor builds
    looks like on the wire: default headers (session affinity, OpenRouter
    attribution, the profile's extra headers), the SDK retry budget, and the
    TLS-verification bypass. ``disable_ssl_verify=None`` reads the system
    setting; callers that already hold the flag pass it through.
    """
    sanitize_invalid_ssl_env()
    headers: dict[str, str] = {}
    if session_affinity:
        headers["x-session-affinity"] = uuid.uuid4().hex
    if _uses_openrouter(spec, base_url):
        headers.update(OPENROUTER_ATTRIBUTION_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "base_url": base_url,
        "default_headers": headers or None,
    }
    if sdk_max_retries is not None:
        kwargs["max_retries"] = sdk_max_retries
    if disable_ssl_verify is None:
        http_client = build_openai_http_client()
    elif disable_ssl_verify:
        http_client = httpx.AsyncClient(verify=False)  # nosec B501
    else:
        http_client = None
    if http_client is not None:
        kwargs["http_client"] = http_client
    return kwargs


__all__ = [
    "OPENROUTER_ATTRIBUTION_HEADERS",
    "build_openai_http_client",
    "disable_ssl_verify_enabled",
    "openai_client_kwargs",
    "openai_sdk_client_kwargs",
    "sanitize_invalid_ssl_env",
]
