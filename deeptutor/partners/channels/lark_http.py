"""Keep-alive HTTP transport for the lark-oapi *sync* client.

``lark_oapi.core.http.transport.Transport.execute`` issues every synchronous
call through the module-level ``requests.request()``, which builds a fresh
``Session`` — and therefore a fresh DNS lookup, TCP connection and TLS
handshake — for every single API call. Measured from a host outside the Feishu
region, that is ~2.0s per call:

    card.create        3.2s (first call also fetches a tenant token)
    card_element.content 2.0s
    …average           2.03s

The channel pays that serially per outbound message, so a streaming card's
first frame (create + send + first text) took ~6s and every later update ~2s,
which is what made Feishu trail the reply (see the partner outbound lane).

Reusing one session per worker thread keeps the connection warm and drops the
average to ~0.68s (≈0.55s once warm) — measured on the same host:

    card.create        1.65s → 0.55s
    card_element.content 2.0s  → 0.55s

Only the sync transport is touched; the SDK's async transport uses httpx and
the WebSocket client keeps its own long-lived connection.
"""

from __future__ import annotations

import threading
from typing import Any

import requests

_SESSIONS = threading.local()
_INSTALLED = False
_LOCK = threading.Lock()


def _session() -> requests.Session:
    """One keep-alive session per thread (urllib3 pools are per session)."""
    session = getattr(_SESSIONS, "session", None)
    if session is None:
        session = requests.Session()
        _SESSIONS.session = session
    return session


class _KeepAliveRequests:
    """Drop-in stand-in for the ``requests`` module used by the SDK transport."""

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        return _session().request(method, url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        # Exceptions, codes, … stay reachable for callers that poke the module.
        return getattr(requests, name)


def install_keep_alive() -> bool:
    """Route lark-oapi's sync HTTP calls through reusable connections.

    Idempotent; returns False when the SDK (or the expected internals) are
    unavailable, in which case the SDK keeps its per-call behaviour.
    """
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        try:
            import lark_oapi.core.http.transport as transport
        except Exception:
            return False
        if not isinstance(getattr(transport, "requests", None), _KeepAliveRequests):
            transport.requests = _KeepAliveRequests()
        _INSTALLED = True
        return True


__all__ = ["install_keep_alive"]
