"""The personal-WeChat QR login exchange, with no channel attached.

The protocol itself already worked — :class:`WeixinChannel` has run it since the
channel landed — but it only ever ran from ``start()``, and the code it produces
was printed to the server's stdout. On any real deployment that is a supervisord
log file the person configuring the partner cannot see, so the channel's own
advice ("scan the QR code to authenticate") had nowhere to be followed (#951).

Lifting the exchange out of the channel is what lets the web app run it too:
same three calls, same status vocabulary, one implementation. Everything here is
stateless — the caller owns the HTTP client and whatever it does with the token.

The exchange is: ask for a code, then poll it until WeChat says what happened.
``interpret_status`` is the whole decision, in one testable place, because the
raw payload has five outcomes and two of them (an expiry that should be retried,
a redirect that changes the host you must poll next) are easy to mistake for
failure.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import os
from typing import Any, Literal

import httpx

ILINK_APP_ID = "bot"

# Personal-WeChat bots are ``bot_type=3`` in the iLink API.
BOT_TYPE_PERSONAL = "3"

QR_ENDPOINT = "ilink/bot/get_bot_qrcode"
QR_STATUS_ENDPOINT = "ilink/bot/get_qrcode_status"

QrStatus = Literal["waiting", "scanned", "confirmed", "expired", "error", "unknown"]


@dataclass(frozen=True, slots=True)
class QrCode:
    """A freshly issued login code: the id to poll, and what to render."""

    qrcode_id: str
    #: What the phone must scan. The API calls it ``qrcode_img_content``; it
    #: falls back to the id itself, which is what the channel has always drawn.
    scan_payload: str


@dataclass(frozen=True, slots=True)
class QrOutcome:
    """What one poll of a login code means.

    ``base_url`` (on confirmation) and ``poll_base_url`` (on redirect) are
    separate on purpose: WeChat can move a *pending* login to another host
    mid-flight, and can also hand back a different host to use for the session
    once it succeeds. Collapsing them loses one or the other.
    """

    status: QrStatus
    token: str = ""
    base_url: str = ""
    poll_base_url: str = ""
    bot_id: str = ""
    user_id: str = ""


def _random_wechat_uin() -> str:
    """``X-WECHAT-UIN``: random uint32 → decimal string → base64, per request."""
    uint32 = int.from_bytes(os.urandom(4), "big")
    return base64.b64encode(str(uint32).encode()).decode()


def qr_headers(*, client_version: int, route_tag: str = "") -> dict[str, str]:
    """Headers for the unauthenticated half of the exchange.

    No ``Authorization``: obtaining the token is the point of these calls.
    """
    headers = {
        "X-WECHAT-UIN": _random_wechat_uin(),
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(client_version),
    }
    if route_tag.strip():
        headers["SKRouteTag"] = route_tag.strip()
    return headers


def normalize_host(value: str) -> str:
    """A redirect host as an absolute base URL (WeChat may omit the scheme)."""
    host = str(value or "").strip()
    if not host:
        return ""
    if host.startswith(("http://", "https://")):
        return host
    return f"https://{host}"


def interpret_status(payload: Any) -> QrOutcome:
    """Read one ``get_qrcode_status`` body.

    Two non-obvious outcomes, kept apart because callers must act differently:

    * a confirmation carrying no token is ``error`` — the login is over and
      failed. Trusting ``status`` alone would store an empty token and fail
      later, far from the cause.
    * a status this function does not recognise is ``unknown``, which means
      "keep polling". A future status string must not end a working login.
    """
    if not isinstance(payload, dict):
        return QrOutcome(status="unknown")

    status = str(payload.get("status") or "")
    if status == "confirmed":
        token = str(payload.get("bot_token") or "")
        if not token:
            return QrOutcome(status="error")
        return QrOutcome(
            status="confirmed",
            token=token,
            base_url=str(payload.get("baseurl") or ""),
            bot_id=str(payload.get("ilink_bot_id") or ""),
            user_id=str(payload.get("ilink_user_id") or ""),
        )
    if status == "scaned_but_redirect":
        # Scanned, but the login moved hosts: keep waiting, poll elsewhere.
        return QrOutcome(
            status="scanned",
            poll_base_url=normalize_host(str(payload.get("redirect_host") or "")),
        )
    if status == "expired":
        return QrOutcome(status="expired")
    if status == "wait":
        return QrOutcome(status="waiting")
    return QrOutcome(status="unknown")


async def fetch_qr_code(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    client_version: int,
    route_tag: str = "",
) -> QrCode:
    """Ask WeChat for a login code to display."""
    response = await client.get(
        f"{base_url.rstrip('/')}/{QR_ENDPOINT}",
        params={"bot_type": BOT_TYPE_PERSONAL},
        headers=qr_headers(client_version=client_version, route_tag=route_tag),
    )
    response.raise_for_status()
    data = response.json()
    qrcode_id = str((data or {}).get("qrcode") or "") if isinstance(data, dict) else ""
    if not qrcode_id:
        raise RuntimeError(f"WeChat did not return a QR code: {data}")
    content = str(data.get("qrcode_img_content") or "")
    return QrCode(qrcode_id=qrcode_id, scan_payload=content or qrcode_id)


async def poll_qr_code(
    client: httpx.AsyncClient,
    base_url: str,
    qrcode_id: str,
    *,
    client_version: int,
    route_tag: str = "",
) -> QrOutcome:
    """Poll a login code once and say what it means."""
    response = await client.get(
        f"{base_url.rstrip('/')}/{QR_STATUS_ENDPOINT}",
        params={"qrcode": qrcode_id},
        headers=qr_headers(client_version=client_version, route_tag=route_tag),
    )
    response.raise_for_status()
    return interpret_status(response.json())


def is_retryable_poll_error(err: Exception) -> bool:
    """Transport hiccups and 5xx are worth another poll; 4xx are not."""
    if isinstance(err, httpx.TimeoutException | httpx.TransportError):
        return True
    if isinstance(err, httpx.HTTPStatusError):
        status_code = err.response.status_code if err.response is not None else 0
        return status_code >= 500
    return False


__all__ = [
    "BOT_TYPE_PERSONAL",
    "ILINK_APP_ID",
    "QrCode",
    "QrOutcome",
    "QrStatus",
    "fetch_qr_code",
    "interpret_status",
    "is_retryable_poll_error",
    "normalize_host",
    "poll_qr_code",
    "qr_headers",
]
