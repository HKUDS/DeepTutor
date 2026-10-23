"""Opt-in request screening with fastapi-guard.

Disabled by default. When ``system.json`` -> ``security_guard.enabled`` is false
(or ``DEEPTUTOR_GUARD_ENABLED`` is unset), nothing here imports ``guard`` and the
middleware stack is unchanged. See ``docs-for-user/SECURITY_GUARD.md``.

The guard runs inside the application, in front of the routers. It screens HTTP
requests by client address (rate limit, IP allow/deny lists, ban list) and scans
the URL path, query string and headers for attack patterns. It does not read
request bodies (prompts, documents and chat are free text), does not touch
WebSocket handshakes, and does not use Redis, CORS or security headers.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from deeptutor.services.config import load_system_settings

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "security_guard is enabled but the 'fastapi-guard' package is not installed. "
    "Install it with `pip install 'deeptutor[guard]'` (Docker: set "
    "DEEPTUTOR_EXTRAS=guard), or disable it with security_guard.enabled=false in "
    "system.json / DEEPTUTOR_GUARD_ENABLED=false."
)


def load_guard_settings() -> dict[str, Any]:
    """Effective ``security_guard`` settings (file plus deployment overrides)."""
    return dict(load_system_settings()["security_guard"])


def build_security_config(settings: dict[str, Any]) -> Any:
    """Translate DeepTutor settings into a ``guard.SecurityConfig``."""
    try:
        from guard import SecurityConfig
    except ImportError as exc:
        raise RuntimeError(INSTALL_HINT) from exc
    from guard_core.handlers.suspatterns_handler import ALL_DETECTION_CATEGORIES

    return SecurityConfig(
        rate_limit=settings["rate_limit"],
        rate_limit_window=settings["rate_limit_window"],
        trusted_proxies=tuple(settings["trusted_proxies"]),
        exempt_ips=tuple(settings["exempt_ips"]),
        whitelist=tuple(settings["whitelist"]) or None,
        blacklist=tuple(settings["blacklist"]),
        # Process-local state: each uvicorn worker keeps its own counters.
        enable_redis=False,
        # DeepTutor sets CORS itself (CORSMiddleware) and owns its response headers.
        enable_cors=False,
        security_headers={"enabled": False},
        # Prompts, documents and chat messages are free text, not attack input.
        detection_scan_body=False,
        # Browsers send the page URL as Referer; guard-core 4.4.0 flags localhost and
        # LAN addresses in it as ssrf (400), so that category stays off.
        enabled_detection_categories=ALL_DETECTION_CATEGORIES - {"ssrf"},
        enable_agent=False,
    )


def install_security_guard(app: FastAPI, settings: dict[str, Any] | None = None) -> bool:
    """Add the guard middleware to ``app`` when enabled; return whether it was added.

    Call this before ``CORSMiddleware`` is added: Starlette puts the last-added
    middleware outermost, so CORS stays outside the guard and 429/403 responses
    still carry CORS headers.
    """
    settings = load_guard_settings() if settings is None else settings
    if not settings["enabled"]:
        return False

    config = build_security_config(settings)
    from guard import PureASGISecurityMiddleware

    app.add_middleware(PureASGISecurityMiddleware, config=config)
    logger.info(
        "Security guard enabled: rate_limit=%s/%ss trusted_proxies=%s exempt_ips=%s whitelist=%s blacklist=%s",
        settings["rate_limit"],
        settings["rate_limit_window"],
        settings["trusted_proxies"],
        settings["exempt_ips"],
        len(settings["whitelist"]),
        len(settings["blacklist"]),
    )
    return True
