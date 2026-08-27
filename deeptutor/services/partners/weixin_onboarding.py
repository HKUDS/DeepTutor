"""Run the personal-WeChat QR login from the web app instead of the terminal.

Configuring a WeChat partner used to mean starting it and then finding the QR
code the channel printed to stdout — which on a container deployment is a
supervisord log the admin has no access to, so the channel's own "scan the QR
code to authenticate" was un-followable (#951).

This drives the same exchange (:mod:`deeptutor.partners.channels.weixin_qr`) on
behalf of a browser: start an attempt, poll it, and on success write the bot
token straight into the partner's channel config.

Two properties this owes the caller:

* **The token never leaves the server.** A status reply says *whether* the login
  succeeded, never what it produced. It is written to the partner config, which
  is already where channel secrets live and is already masked on read.
* **Attempts expire.** Sessions are in-process and short-lived, so a browser tab
  left open overnight cannot hold a pending login, and a restarted backend
  simply has none — the admin starts a new scan, which is what they would do
  anyway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import secrets
import threading
import time
from typing import Any

import httpx

from deeptutor.partners.channels.weixin_qr import (
    QrOutcome,
    fetch_qr_code,
    is_retryable_poll_error,
    poll_qr_code,
)

logger = logging.getLogger(__name__)

CHANNEL = "weixin"

#: WeChat's own codes expire in well under this; the ceiling exists so an
#: abandoned tab cannot pin a session forever.
_SESSION_TTL_SECONDS = 10 * 60
#: A code that expired mid-scan is re-issued this many times before the attempt
#: is declared over, mirroring the channel's own MAX_QR_REFRESH_COUNT.
_MAX_REFRESHES = 3

_DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"


@dataclass
class _Attempt:
    partner_id: str
    qrcode_id: str
    scan_payload: str
    poll_base_url: str
    route_tag: str
    client_version: int
    created_at: float
    status: str = "waiting"
    error: str = ""
    refreshes: int = 0
    #: Set once, on success. Never rendered into a response.
    token: str = field(default="", repr=False)


_attempts: dict[str, _Attempt] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _prune(now: float) -> None:
    stale = [key for key, a in _attempts.items() if now - a.created_at > _SESSION_TTL_SECONDS]
    for key in stale:
        _attempts.pop(key, None)


def _client_version() -> int:
    from deeptutor.partners.channels.weixin import ILINK_APP_CLIENT_VERSION

    return ILINK_APP_CLIENT_VERSION


def _channel_config(partner_id: str) -> dict[str, Any]:
    from deeptutor.services.partners.manager import get_partner_manager

    config = get_partner_manager().load_config(partner_id)
    channels = getattr(config, "channels", None) if config else None
    entry = (channels or {}).get(CHANNEL) if isinstance(channels, dict) else None
    return entry if isinstance(entry, dict) else {}


def render_qr_svg(payload: str) -> str:
    """The code as an inline SVG, or ``""`` when it cannot be drawn here.

    SVG rather than PNG so no imaging library is pulled in, and server-side
    rather than in the browser so the web bundle needs no QR dependency at all.
    ``qrcode`` ships with the ``partners`` extra — the same extra this channel
    needs — but a deployment missing it should still get a usable page, so the
    caller also receives the raw payload to fall back on.
    """
    if not payload:
        return ""
    try:
        import io

        import qrcode
        import qrcode.image.svg

        image = qrcode.make(
            payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2
        )
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception:
        logger.debug("qrcode unavailable; returning the raw scan payload", exc_info=True)
        return ""


def _public(attempt: _Attempt, session_id: str) -> dict[str, Any]:
    """The wire view — deliberately without the token."""
    return {
        "session_id": session_id,
        "status": attempt.status,
        "error": attempt.error,
        "expires_in": max(0, int(_SESSION_TTL_SECONDS - (_now() - attempt.created_at))),
        # Carried on every reply because an expired code is silently replaced:
        # the browser must redraw, and polling is the only time it hears about it.
        "scan_payload": attempt.scan_payload,
    }


async def start_login(partner_id: str) -> dict[str, Any]:
    """Issue a QR code for this partner and return what the browser must draw."""
    entry = _channel_config(partner_id)
    base_url = str(entry.get("base_url") or "") or _DEFAULT_BASE_URL
    route_tag = str(entry.get("route_tag") or "")
    client_version = _client_version()

    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=15)) as client:
        code = await fetch_qr_code(
            client, base_url, client_version=client_version, route_tag=route_tag
        )

    session_id = secrets.token_urlsafe(16)
    attempt = _Attempt(
        partner_id=partner_id,
        qrcode_id=code.qrcode_id,
        scan_payload=code.scan_payload,
        poll_base_url=base_url,
        route_tag=route_tag,
        client_version=client_version,
        created_at=_now(),
    )
    with _lock:
        _prune(_now())
        _attempts[session_id] = attempt
    return {
        **_public(attempt, session_id),
        "scan_payload": code.scan_payload,
        "qr_svg": render_qr_svg(code.scan_payload),
    }


async def poll_login(partner_id: str, session_id: str) -> dict[str, Any]:
    """Advance one attempt and report its state.

    Terminal states stay put: once an attempt is confirmed or dead, polling it
    again returns the same answer rather than re-running the exchange.
    """
    with _lock:
        _prune(_now())
        attempt = _attempts.get(session_id)
    if attempt is None or attempt.partner_id != partner_id:
        return {"session_id": session_id, "status": "expired", "error": "", "expires_in": 0}
    if attempt.status in {"confirmed", "expired", "error"}:
        return _public(attempt, session_id)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=15)) as client:
            outcome = await poll_qr_code(
                client,
                attempt.poll_base_url,
                attempt.qrcode_id,
                client_version=attempt.client_version,
                route_tag=attempt.route_tag,
            )
    except Exception as exc:
        if is_retryable_poll_error(exc):
            # Not a verdict — the browser polls again in a moment.
            return _public(attempt, session_id)
        logger.warning("weixin QR poll failed for %s: %s", partner_id, exc, exc_info=True)
        attempt.status = "error"
        attempt.error = str(exc)
        return _public(attempt, session_id)

    previous = attempt.scan_payload
    await _apply_outcome(attempt, outcome)
    reply = _public(attempt, session_id)
    if attempt.scan_payload != previous:
        reply["qr_svg"] = render_qr_svg(attempt.scan_payload)
    return reply


async def _apply_outcome(attempt: _Attempt, outcome: QrOutcome) -> None:
    if outcome.status == "scanned":
        attempt.status = "scanned"
        if outcome.poll_base_url:
            attempt.poll_base_url = outcome.poll_base_url
        return
    if outcome.status in {"waiting", "unknown"}:
        # `unknown` is a status this build does not recognise, not a failure:
        # keep the attempt alive so a new WeChat status string cannot end a
        # login that is actually still in progress.
        attempt.status = "waiting"
        return
    if outcome.status == "expired":
        attempt.refreshes += 1
        if attempt.refreshes > _MAX_REFRESHES:
            attempt.status = "expired"
            return
        await _reissue(attempt)
        return
    if outcome.status == "confirmed":
        attempt.token = outcome.token
        try:
            _persist_token(attempt.partner_id, outcome)
        except Exception as exc:
            logger.warning(
                "weixin login succeeded but the token could not be saved for %s: %s",
                attempt.partner_id,
                exc,
                exc_info=True,
            )
            attempt.status = "error"
            attempt.error = "The login succeeded but the token could not be saved."
            return
        attempt.status = "confirmed"
        return
    # `error` — WeChat confirmed the scan but handed back no token.
    attempt.status = "error"
    attempt.error = "WeChat confirmed the scan but returned no bot token."


async def _reissue(attempt: _Attempt) -> None:
    """Swap in a fresh code so a slow scan is not a dead end."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=15)) as client:
            code = await fetch_qr_code(
                client,
                attempt.poll_base_url,
                client_version=attempt.client_version,
                route_tag=attempt.route_tag,
            )
    except Exception as exc:
        logger.warning("weixin QR re-issue failed: %s", exc, exc_info=True)
        attempt.status = "expired"
        return
    attempt.qrcode_id = code.qrcode_id
    attempt.scan_payload = code.scan_payload
    attempt.status = "waiting"


def current_scan_payload(partner_id: str, session_id: str) -> str:
    """What to draw right now — it changes when an expired code is re-issued."""
    with _lock:
        attempt = _attempts.get(session_id)
    if attempt is None or attempt.partner_id != partner_id:
        return ""
    return attempt.scan_payload


def _persist_token(partner_id: str, outcome: QrOutcome) -> None:
    """Write the bot token into the partner's ``weixin`` channel config."""
    from deeptutor.services.partners.manager import get_partner_manager

    manager = get_partner_manager()
    existing = manager.load_config(partner_id)
    channels = dict(getattr(existing, "channels", None) or {})
    entry = dict(channels.get(CHANNEL) or {})
    entry["token"] = outcome.token
    if outcome.base_url:
        entry["base_url"] = outcome.base_url
    entry.setdefault("enabled", True)
    channels[CHANNEL] = entry
    # merge_config overlays and returns; save_config is what writes it down.
    merged = manager.merge_config(partner_id, {"channels": channels})
    manager.save_config(partner_id, merged)


def forget(session_id: str) -> None:
    with _lock:
        _attempts.pop(session_id, None)


__all__ = [
    "CHANNEL",
    "current_scan_payload",
    "forget",
    "poll_login",
    "start_login",
]
