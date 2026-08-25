"""Single-use session handoff to the current Cloudflare Quick Tunnel."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

from deeptutor.services.auth import TokenPayload

_TICKET_TTL_SECONDS = 60
_PAIRING_TTL_SECONDS = 120
_TUNNEL_SUFFIX = ".trycloudflare.com"
_tickets: dict[str, "_Ticket"] = {}
_tickets_lock = threading.Lock()
_pairings: dict[str, "_Pairing"] = {}
_pairings_lock = threading.Lock()


@dataclass(frozen=True)
class TunnelState:
    url: str
    host: str


@dataclass
class _Ticket:
    code_digest: str
    payload: TokenPayload
    target_host: str
    expires_at: float
    used: bool = False


@dataclass
class _Pairing:
    payload: TokenPayload
    expires_at: float


def _tunnel_file() -> Path:
    from deeptutor.multi_user.paths import SYSTEM_ROOT

    return SYSTEM_ROOT / "auth" / "deeptutor_tunnel.json"


def _valid_tunnel_host(host: str | None) -> bool:
    return bool(
        host
        and host.endswith(_TUNNEL_SUFFIX)
        and len(host) > len(_TUNNEL_SUFFIX)
        and host == host.lower()
        and all(part and part.isalnum() for part in host[: -len(_TUNNEL_SUFFIX)].split("-"))
    )


def load_tunnel_state() -> TunnelState | None:
    """Load the operator-written current tunnel URL without accepting overrides."""
    try:
        payload = json.loads(_tunnel_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None

    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or not _valid_tunnel_host(parsed.hostname)
    ):
        return None
    return TunnelState(url=url.rstrip("/"), host=parsed.hostname)


def _prune(now: float) -> None:
    expired = [key for key, ticket in _tickets.items() if ticket.expires_at <= now]
    for key in expired:
        _tickets.pop(key, None)


def create_ticket(payload: TokenPayload, now: float | None = None) -> tuple[str, TunnelState]:
    """Create a single-use ticket and return (plaintext code, target tunnel)."""
    state = load_tunnel_state()
    if state is None:
        raise ValueError("No active DeepTutor tunnel is configured")

    current = time.time() if now is None else now
    code = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    with _tickets_lock:
        _prune(current)
        _tickets[digest] = _Ticket(
            code_digest=digest,
            payload=payload,
            target_host=state.host,
            expires_at=current + _TICKET_TTL_SECONDS,
        )
    return code, state


def create_pairing(payload: TokenPayload, now: float | None = None) -> tuple[str, int]:
    """Create a one-time phone pairing capability without exposing a login code."""
    current = time.time() if now is None else now
    pairing_id = secrets.token_urlsafe(32)
    digest = hashlib.sha256(pairing_id.encode("utf-8")).hexdigest()
    with _pairings_lock:
        expired = [key for key, pairing in _pairings.items() if pairing.expires_at <= current]
        for key in expired:
            _pairings.pop(key, None)
        _pairings[digest] = _Pairing(
            payload=payload,
            expires_at=current + _PAIRING_TTL_SECONDS,
        )
    return pairing_id, _PAIRING_TTL_SECONDS


def exchange_pairing(pairing_id: str, now: float | None = None) -> TokenPayload | None:
    """Atomically exchange a pairing capability for its authenticated payload."""
    if not pairing_id:
        return None
    digest = hashlib.sha256(pairing_id.encode("utf-8")).hexdigest()
    current = time.time() if now is None else now
    with _pairings_lock:
        pairing = _pairings.get(digest)
        if pairing is None or pairing.expires_at <= current:
            _pairings.pop(digest, None)
            return None
        _pairings.pop(digest, None)
        return pairing.payload


def consume_ticket(
    code: str,
    target_host: str | None,
    now: float | None = None,
) -> TokenPayload | None:
    """Atomically consume a ticket for exactly its intended tunnel host."""
    if not code or not target_host:
        return None
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    current = time.time() if now is None else now
    with _tickets_lock:
        _prune(current)
        ticket = _tickets.get(digest)
        if (
            ticket is None
            or ticket.used
            or ticket.expires_at <= current
            or not hmac.compare_digest(ticket.target_host, target_host)
        ):
            if ticket is not None:
                _tickets.pop(digest, None)
            return None
        ticket.used = True
        _tickets.pop(digest, None)
        return ticket.payload


def clear_tickets() -> None:
    """Test helper; production state naturally expires in 60 seconds."""
    with _tickets_lock:
        _tickets.clear()


def clear_pairings() -> None:
    """Test helper; production pairings naturally expire."""
    with _pairings_lock:
        _pairings.clear()
