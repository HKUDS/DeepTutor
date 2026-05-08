"""
PocketBase client singleton.

Only initialised when POCKETBASE_URL is present in the environment.
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
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_POCKETBASE_URL: str = os.getenv("POCKETBASE_URL", "").rstrip("/")
_ADMIN_EMAIL: str = os.getenv("POCKETBASE_ADMIN_EMAIL", "")
_ADMIN_PASSWORD: str = os.getenv("POCKETBASE_ADMIN_PASSWORD", "")

_client = None
_client_initialised = False

# Token validation cache: token -> (payload_dict, expires_at)
_TOKEN_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_TOKEN_CACHE_TTL: float = 60.0  # seconds


def is_pocketbase_enabled() -> bool:
    """Return True when POCKETBASE_URL is configured."""
    return bool(_POCKETBASE_URL)


def get_pb_client():
    """
    Return an admin-authenticated PocketBase SDK client (cached singleton).

    Raises RuntimeError if POCKETBASE_URL is not set.
    Raises on authentication failure.
    """
    global _client, _client_initialised

    if not is_pocketbase_enabled():
        raise RuntimeError("PocketBase is not configured. Set POCKETBASE_URL in .env to enable it.")

    if _client_initialised:
        return _client

    try:
        from pocketbase import PocketBase  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "The 'pocketbase' package is not installed. Run: pip install pocketbase"
        ) from exc

    pb = PocketBase(_POCKETBASE_URL)

    if _ADMIN_EMAIL and _ADMIN_PASSWORD:
        try:
            pb.admins.auth_with_password(_ADMIN_EMAIL, _ADMIN_PASSWORD)
            logger.info(f"PocketBase admin authenticated at {_POCKETBASE_URL}")
        except Exception as exc:
            logger.error(
                f"PocketBase admin authentication failed: {exc}. "
                "Check POCKETBASE_ADMIN_EMAIL and POCKETBASE_ADMIN_PASSWORD."
            )
            raise
    else:
        logger.warning(
            "POCKETBASE_ADMIN_EMAIL / POCKETBASE_ADMIN_PASSWORD not set. "
            "The backend will connect to PocketBase without admin privileges. "
            "Collection management (scripts/pb_setup.py) will not work."
        )

    _client = pb
    _client_initialised = True
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
    if not is_pocketbase_enabled():
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

        pb = PocketBase(_POCKETBASE_URL)
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
    if not is_pocketbase_enabled():
        return False

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_POCKETBASE_URL}/api/health")
            if resp.status_code == 200:
                logger.info(f"PocketBase health check passed at {_POCKETBASE_URL}")
                return True
            logger.warning(
                f"PocketBase health check returned HTTP {resp.status_code} at {_POCKETBASE_URL}. "
                "Sessions will fail until PocketBase is healthy."
            )
            return False
    except Exception as exc:
        logger.warning(
            f"PocketBase is unreachable at {_POCKETBASE_URL} ({exc}). "
            "Sessions and auth will fall back to SQLite until PocketBase is available. "
            "Check that the pocketbase container is running and POCKETBASE_URL is correct."
        )
        return False
