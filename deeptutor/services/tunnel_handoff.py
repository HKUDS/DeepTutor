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
    redirect_path: str = "/"
    viewer_session_id: str = ""
    controller_secret: str = ""
    used: bool = False


@dataclass
class _Pairing:
    payload: TokenPayload
    expires_at: float
    redirect_path: str = "/"
    viewer_session_id: str = ""
    controller_secret: str = ""


@dataclass(frozen=True)
class ViewerHandoff:
    redirect_path: str
    viewer_session_id: str
    controller_secret: str


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


def _valid_video_handoff(
    redirect_path: str,
    viewer_session_id: str,
    controller_secret: str,
) -> bool:
    if not viewer_session_id and not controller_secret:
        return redirect_path == "/"
    if not viewer_session_id or not controller_secret:
        return False
    expected = f"/video-learning?viewer_session={viewer_session_id}"
    return (
        redirect_path == expected
        and all(character.isalnum() or character in "-_." for character in viewer_session_id)
        and len(viewer_session_id) <= 128
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


def create_ticket(
    payload: TokenPayload,
    now: float | None = None,
    *,
    redirect_path: str = "/",
    viewer_session_id: str = "",
    controller_secret: str = "",
) -> tuple[str, TunnelState]:
    """Create a single-use ticket and return (plaintext code, target tunnel)."""
    if not _valid_video_handoff(redirect_path, viewer_session_id, controller_secret):
        raise ValueError("Invalid viewer handoff payload")
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
            redirect_path=redirect_path,
            viewer_session_id=viewer_session_id,
            controller_secret=controller_secret,
        )
    return code, state


def create_pairing(
    payload: TokenPayload,
    now: float | None = None,
    *,
    redirect_path: str = "/",
    viewer_session_id: str = "",
    controller_secret: str = "",
) -> tuple[str, int]:
    """Create a one-time phone pairing capability without exposing a login code."""
    if not _valid_video_handoff(redirect_path, viewer_session_id, controller_secret):
        raise ValueError("Invalid viewer handoff payload")
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
            redirect_path=redirect_path,
            viewer_session_id=viewer_session_id,
            controller_secret=controller_secret,
        )
    return pairing_id, _PAIRING_TTL_SECONDS


def exchange_pairing_details(
    pairing_id: str,
    now: float | None = None,
) -> tuple[TokenPayload, ViewerHandoff] | None:
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
        return pairing.payload, ViewerHandoff(
            redirect_path=pairing.redirect_path,
            viewer_session_id=pairing.viewer_session_id,
            controller_secret=pairing.controller_secret,
        )


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
) -> tuple[TokenPayload, ViewerHandoff] | None:
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
        return ticket.payload, ViewerHandoff(
            redirect_path=ticket.redirect_path,
            viewer_session_id=ticket.viewer_session_id,
            controller_secret=ticket.controller_secret,
        )


def clear_tickets() -> None:
    """Test helper; production state naturally expires in 60 seconds."""
    with _tickets_lock:
        _tickets.clear()


def clear_pairings() -> None:
    """Test helper; production pairings naturally expire."""
    with _pairings_lock:
        _pairings.clear()
