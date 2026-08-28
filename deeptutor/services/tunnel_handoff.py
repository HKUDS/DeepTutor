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

TICKET_TTL_SECONDS = 180
PAIRING_TTL_SECONDS = 300
_TUNNEL_SUFFIX = ".trycloudflare.com"
_FORBIDDEN_COOKIE_NAMES = frozenset({"dt_token"})
_tickets: dict[str, "_Ticket"] = {}
_tickets_lock = threading.Lock()
_pairings: dict[str, "_Pairing"] = {}
_pairings_lock = threading.Lock()


@dataclass(frozen=True)
class TunnelState:
    url: str
    host: str


@dataclass(frozen=True)
class HandoffCookie:
    name: str
    value: str
    path: str = "/"
    max_age: int = 0


@dataclass(frozen=True)
class SessionHandoff:
    redirect_path: str = "/"
    cookies: tuple[HandoffCookie, ...] = ()
    clear_cookie_names: tuple[str, ...] = ()


@dataclass
class _Ticket:
    code_digest: str
    payload: TokenPayload
    target_host: str
    expires_at: float
    handoff: SessionHandoff = SessionHandoff()
    used: bool = False


@dataclass
class _Pairing:
    payload: TokenPayload
    expires_at: float
    handoff: SessionHandoff = SessionHandoff()


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


def _valid_redirect_path(redirect_path: str) -> bool:
    if (
        not redirect_path.startswith("/")
        or redirect_path.startswith("//")
        or redirect_path.startswith(r"/\\")
        or "\\" in redirect_path
    ):
        return False
    if len(redirect_path) > 2048 or any(
        ord(character) < 0x21 or ord(character) > 0x7E for character in redirect_path
    ):
        return False
    lower = redirect_path.lower()
    if "%5c" in lower:
        return False
    parsed = urlsplit(redirect_path)
    return not parsed.scheme and not parsed.netloc and not parsed.fragment


def _valid_cookie_name(name: str) -> bool:
    forbidden = {'(', ')', '<', '>', '@', ',', ';', ':', '"', '/', '[', ']', '?', '=', '{', '}', '\\'}
    return (
        0 < len(name) <= 128
        and name.lower() not in _FORBIDDEN_COOKIE_NAMES
        and all(0x21 <= ord(character) <= 0x7E for character in name)
        and not any(character in forbidden for character in name)
    )


def _valid_cookie_value(value: str) -> bool:
    forbidden = {';', '"', '\\'}
    return (
        0 < len(value) <= 1024
        and all(0x21 <= ord(character) <= 0x7E for character in value)
        and not any(character in forbidden for character in value)
    )


def _valid_cookie_path(path: str) -> bool:
    forbidden = {';', ',', '"', '?', '#', '\\'}
    return (
        path.startswith('/')
        and len(path) <= 512
        and all(0x21 <= ord(character) <= 0x7E for character in path)
        and not any(character in forbidden for character in path)
    )


def _valid_handoff(handoff: SessionHandoff) -> bool:
    if not _valid_redirect_path(handoff.redirect_path):
        return False
    if len(handoff.cookies) > 8 or len(handoff.clear_cookie_names) > 8:
        return False
    if any(not _valid_cookie_name(name) for name in handoff.clear_cookie_names):
        return False
    cookie_names: set[str] = set()
    for cookie in handoff.cookies:
        if not _valid_cookie_name(cookie.name):
            return False
        if cookie.name in cookie_names:
            return False
        cookie_names.add(cookie.name)
        if not _valid_cookie_value(cookie.value):
            return False
        if not _valid_cookie_path(cookie.path):
            return False
        if not (0 < cookie.max_age <= 30 * 24 * 60 * 60):
            return False
    if cookie_names.intersection(set(handoff.clear_cookie_names)):
        return False
    return True


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


def create_ticket(
    payload: TokenPayload,
    now: float | None = None,
    *,
    handoff: SessionHandoff | None = None,
) -> tuple[str, TunnelState]:
    """Create a single-use ticket and return (plaintext code, target tunnel)."""
    ticket_handoff = SessionHandoff() if handoff is None else handoff
    if not _valid_handoff(ticket_handoff):
        raise ValueError("Invalid session handoff payload")
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
            expires_at=current + TICKET_TTL_SECONDS,
            handoff=ticket_handoff,
        )
    return code, state


def create_pairing(
    payload: TokenPayload,
    now: float | None = None,
    *,
    handoff: SessionHandoff | None = None,
) -> tuple[str, int]:
    """Create a one-time phone pairing capability without exposing a login code."""
    pairing_handoff = SessionHandoff() if handoff is None else handoff
    if not _valid_handoff(pairing_handoff):
        raise ValueError("Invalid session handoff payload")
    current = time.time() if now is None else now
    pairing_id = secrets.token_urlsafe(32)
    digest = hashlib.sha256(pairing_id.encode("utf-8")).hexdigest()
    with _pairings_lock:
        expired = [key for key, pairing in _pairings.items() if pairing.expires_at <= current]
        for key in expired:
            _pairings.pop(key, None)
        _pairings[digest] = _Pairing(
            payload=payload,
            expires_at=current + PAIRING_TTL_SECONDS,
            handoff=pairing_handoff,
        )
    return pairing_id, PAIRING_TTL_SECONDS


def exchange_pairing_details(
    pairing_id: str,
    now: float | None = None,
) -> tuple[TokenPayload, SessionHandoff] | None:
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
        return pairing.payload, pairing.handoff


def exchange_pairing(pairing_id: str, now: float | None = None) -> TokenPayload | None:
    exchanged = exchange_pairing_details(pairing_id, now)
    return exchanged[0] if exchanged else None


def consume_ticket(
    code: str,
    target_host: str | None,
    now: float | None = None,
) -> TokenPayload | None:
    consumed = consume_ticket_details(code, target_host, now)
    return consumed[0] if consumed else None


def consume_ticket_details(
    code: str,
    target_host: str | None,
    now: float | None = None,
) -> tuple[TokenPayload, SessionHandoff] | None:
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
        return ticket.payload, ticket.handoff


def clear_tickets() -> None:
    """Test helper; production state naturally expires after the ticket TTL."""
    with _tickets_lock:
        _tickets.clear()


def clear_pairings() -> None:
    """Test helper; production pairings naturally expire."""
    with _pairings_lock:
        _pairings.clear()
