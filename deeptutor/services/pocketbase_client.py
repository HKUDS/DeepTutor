"""
PocketBase client singleton.

Only initialised when integrations.pocketbase_url is configured.
All other code checks ``is_pocketbase_enabled()`` before calling
``get_pb_client()`` to avoid import-time failures when PocketBase is
not configured.

Token validation uses PocketBase's auth-refresh endpoint rather than
local JWT decoding (PocketBase does not expose a static JWT secret).
Results are cached in memory for 60 seconds so only the first request
per token per minute incurs a network call (~5–10 ms); all subsequent
requests within the TTL are resolved in < 1 ms from the local cache.

Usage:
    from deeptutor.services.pocketbase_client import get_pb_client, is_pocketbase_enabled

    if is_pocketbase_enabled():
        pb = get_pb_client()
        result = pb.collection("sessions").get_list(1, 50)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from deeptutor.services.config import load_integrations_settings

logger = logging.getLogger(__name__)

_client = None
_client_initialised = False
_client_key = ""

# Token validation cache: token -> (payload_dict, expires_at)
_TOKEN_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_TOKEN_CACHE_TTL: float = 60.0  # seconds


def is_pocketbase_enabled() -> bool:
    """Return True when integrations.pocketbase_url is configured."""
    return bool(_pocketbase_settings()["url"])


def _pocketbase_settings() -> dict[str, str]:
    settings = load_integrations_settings()
    return {
        "url": str(settings["pocketbase_url"]).rstrip("/"),
        "admin_email": str(settings["pocketbase_admin_email"]),
        "admin_password": str(settings["pocketbase_admin_password"]),
    }


def get_pb_client():
    """
    Return an admin-authenticated PocketBase SDK client (cached singleton).

    Raises RuntimeError if integrations.pocketbase_url is not set.
    Raises on authentication failure.
    """
    global _client, _client_initialised, _client_key

    settings = _pocketbase_settings()
    pocketbase_url = settings["url"]
    admin_email = settings["admin_email"]
    admin_password = settings["admin_password"]

    if not pocketbase_url:
        raise RuntimeError(
            "PocketBase is not configured. Set integrations.pocketbase_url to enable it."
        )

    cache_key = f"{pocketbase_url}|{admin_email}"
    if _client_initialised and _client_key == cache_key:
        return _client

    try:
        from pocketbase import PocketBase  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "The 'pocketbase' package is not installed. Run: pip install pocketbase"
        ) from exc

    pb = PocketBase(pocketbase_url)

    if admin_email and admin_password:
        try:
            pb.admins.auth_with_password(admin_email, admin_password)
            logger.info(f"PocketBase admin authenticated at {pocketbase_url}")
        except Exception as exc:
            logger.error(
                f"PocketBase admin authentication failed: {exc}. "
                "Check integrations.pocketbase_admin_email and integrations.pocketbase_admin_password."
            )
            raise
    else:
        logger.warning(
            "PocketBase admin email/password not set in integrations.json. "
            "The backend will connect to PocketBase without admin privileges. "
            "Collection management (scripts/pb_setup.py) will not work."
        )

    _client = pb
    _client_initialised = True
    _client_key = cache_key
    return _client


def validate_pb_token(token: str) -> dict[str, Any] | None:
    """
    Validate a PocketBase user token and return the user payload dict.

    Uses PocketBase's /api/collections/users/auth-refresh endpoint.
    Results are cached for ``_TOKEN_CACHE_TTL`` seconds so only the
    first call per token per minute makes a network round-trip.

    Returns a dict with at least ``username`` and ``role`` keys, or
    None if the token is invalid / expired.
    """
    settings = _pocketbase_settings()
    pocketbase_url = settings["url"]
    if not pocketbase_url:
        return None

    now = time.monotonic()

    # Cache hit
    cached = _TOKEN_CACHE.get(token)
    if cached is not None:
        payload, expires_at = cached
        if now < expires_at:
            return payload
        del _TOKEN_CACHE[token]

    # Cache miss — call PocketBase
    try:
        from pocketbase import PocketBase  # type: ignore[import]

        pb = PocketBase(pocketbase_url)
        # Inject the user token so auth_refresh validates it
        pb.auth_store.save(token, None)
        result = pb.collection("users").auth_refresh()

        record = result.record
        username = (
            getattr(record, "email", None)
            or getattr(record, "name", None)
            or getattr(record, "username", None)
            or getattr(record, "id", "unknown")
        )
        role = str(getattr(record, "role", "user") or "user")

        payload = {"username": str(username), "role": role}
        _TOKEN_CACHE[token] = (payload, now + _TOKEN_CACHE_TTL)
        return payload

    except Exception as exc:
        logger.debug(f"PocketBase token validation failed: {exc}")
        return None


async def ping_pocketbase() -> bool:
    """
    Async health check called during FastAPI lifespan startup.

    Returns True if PocketBase is reachable, False otherwise.
    Logs a clear warning (not an exception) so the server still starts
    when PocketBase is configured but temporarily unavailable.
    """
    settings = _pocketbase_settings()
    pocketbase_url = settings["url"]
    if not pocketbase_url:
        return False

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{pocketbase_url}/api/health")
            if resp.status_code == 200:
                logger.info(f"PocketBase health check passed at {pocketbase_url}")
                return True
            logger.warning(
                f"PocketBase health check returned HTTP {resp.status_code} at {pocketbase_url}. "
                "Sessions will fail until PocketBase is healthy."
            )
            return False
    except Exception as exc:
        logger.warning(
            f"PocketBase is unreachable at {pocketbase_url} ({exc}). "
            "Sessions and auth will fall back to SQLite until PocketBase is available. "
            "Check that the pocketbase container is running and integrations.pocketbase_url is correct."
        )
        return False
