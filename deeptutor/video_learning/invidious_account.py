"""Secure per-owner Invidious account connections.

Invidious token authorization is deliberately small: DeepTutor sends the learner
to the instance's consent page, receives a signed token through a one-time
callback, verifies it by reading preferences, and stores only that token in the
owner-private secrets tree. No password or browser cookie is handled here.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import deeptutor.video_learning.invidious_account_client as _client
import deeptutor.video_learning.invidious_account_storage as _storage
from deeptutor.video_learning.service import (
    TimedMediaError,
    load_video_learning_settings,
    normalize_video_learning_settings,
)

CALLBACK_PATH = "/api/video-learning/invidious/account/callback"
FLOW_TIMEOUT_S = 600.0
PUBLIC_URL_ENV = "DEEPTUTOR_PUBLIC_URL"
DEFAULT_PUBLIC_URL = "http://localhost:3782"
ACCOUNT_SCOPES = ("GET:preferences", "POST:tokens/unregister")
_MAX_TOKEN_BYTES = 8192

# Explicit call seams let the workflow tests substitute transport behavior
# without making filesystem persistence part of the same mock boundary.
_request_preferences = _client.request_preferences
_revoke_token = _client.revoke_token


def _configured_public_url() -> str:
    configured = os.environ.get(PUBLIC_URL_ENV, "").strip().rstrip("/")
    if configured:
        # Reuse the provider-origin rules rather than accepting an arbitrary
        # redirect target from an environment typo.
        normalized = normalize_video_learning_settings(
            {
                "version": 1,
                "default_provider": "youtube",
                "invidious": {"api_base_url": "", "public_base_url": configured},
            }
        )
        return normalized["invidious"]["public_base_url"]
    # Request Host and X-Forwarded-* headers are attacker-controlled unless a
    # deployment has explicitly configured and constrained trusted proxies.
    # Remote deployments therefore opt into their canonical external origin;
    # local installs retain the shipped frontend URL.
    return DEFAULT_PUBLIC_URL


def invidious_redirect_uri() -> str:
    return f"{_configured_public_url()}{CALLBACK_PATH}"


def begin_invidious_account_authorization(*, owner_id: str, redirect_uri: str) -> str:
    settings = load_video_learning_settings()
    base = settings["invidious"]["api_base_url"]
    if not base:
        raise TimedMediaError("Configure the Invidious API base URL before connecting an account.")

    parsed_redirect = urlparse(redirect_uri)
    try:
        parsed_redirect.port
    except ValueError as exc:
        raise TimedMediaError("Invidious callback URL contains an invalid port.") from exc
    if (
        parsed_redirect.scheme not in {"http", "https"}
        or not parsed_redirect.hostname
        or parsed_redirect.username
        or parsed_redirect.password
        or parsed_redirect.fragment
    ):
        raise TimedMediaError("Invidious callback URL must be a plain HTTP(S) URL.")

    _storage.purge_expired(owner_id)
    state = secrets.token_urlsafe(32)
    separator = "&" if parsed_redirect.query else "?"
    callback_url = f"{redirect_uri}{separator}{urlencode({'state': state})}"
    authorize_url = f"{base}/authorize_token?{urlencode({'scopes': ','.join(ACCOUNT_SCOPES), 'callback_url': callback_url})}"

    _storage.replace_pending_flow(
        state=state,
        flow=_storage.PendingFlow(
            owner_id=owner_id,
            api_base_url=base,
            callback_url=callback_url,
            expires_at=time.time() + FLOW_TIMEOUT_S,
        ),
    )
    return authorize_url


def _parse_token(raw_token: str) -> dict[str, Any]:
    if not raw_token or len(raw_token.encode("utf-8")) > _MAX_TOKEN_BYTES:
        raise TimedMediaError("Invidious returned an invalid account token.")
    try:
        token = json.loads(raw_token)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise TimedMediaError("Invidious returned an invalid account token.") from exc
    if not isinstance(token, dict):
        raise TimedMediaError("Invidious returned an invalid account token.")

    session = token.get("session")
    scopes = token.get("scopes")
    signature = token.get("signature")
    if (
        not isinstance(session, str)
        or not session
        or not isinstance(signature, str)
        or not signature
        or not isinstance(scopes, list)
        or any(not isinstance(scope, str) for scope in scopes)
    ):
        raise TimedMediaError("Invidious returned an incomplete account token.")
    if not _scopes_include_required(scopes):
        raise TimedMediaError("Invidious account token is missing a required scope.")
    expire = token.get("expire")
    if expire is not None and (not isinstance(expire, int) or expire <= 0):
        raise TimedMediaError("Invidious returned an invalid token expiration.")
    return token


def _scopes_include_required(scopes: Any) -> bool:
    if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
        return False
    return set(ACCOUNT_SCOPES).issubset(set(scopes))


def _stored_token_is_usable(token: Any) -> bool:
    if not isinstance(token, dict):
        return False
    session = token.get("session")
    signature = token.get("signature")
    expire = token.get("expire")
    if not isinstance(session, str) or not session:
        return False
    if not isinstance(signature, str) or not signature:
        return False
    if expire is not None and (not isinstance(expire, int) or expire <= 0):
        return False
    return not (isinstance(expire, int) and expire <= datetime.now(timezone.utc).timestamp())


async def complete_invidious_account_authorization(
    *, owner_id: str, state: str, token: str
) -> dict[str, Any]:
    _storage.purge_expired(owner_id)
    flow = _storage.consume_pending_flow(owner_id, state)
    if flow is None:
        raise TimedMediaError("Invidious account callback is unknown, expired, or already used.")

    parsed_token = _parse_token(token)
    await _request_preferences(api_base_url=flow.api_base_url, token=parsed_token)

    _storage.write_account(
        owner_id,
        {
            "version": 1,
            "api_base_url": flow.api_base_url,
            "scopes": list(ACCOUNT_SCOPES),
            "connected_at": datetime.now(timezone.utc).isoformat(),
            "token": parsed_token,
        },
    )
    return invidious_account_status(owner_id)


def invidious_account_status(owner_id: str) -> dict[str, Any]:
    payload = _storage.read_account(owner_id)
    token = payload.get("token")
    base = payload.get("api_base_url")
    scopes = payload.get("scopes")
    connected_at = payload.get("connected_at")
    if not _stored_token_is_usable(token) or not isinstance(base, str) or not base:
        return {"connected": False}
    if not _scopes_include_required(scopes):
        return {"connected": False}
    if not isinstance(connected_at, str) or not connected_at:
        return {"connected": False}
    return {
        "connected": True,
        "api_base_url": base,
        "scopes": [str(scope) for scope in scopes],
        "connected_at": connected_at,
    }


async def disconnect_invidious_account(*, owner_id: str) -> dict[str, Any]:
    payload = _storage.read_account(owner_id)
    token = payload.get("token")
    base = payload.get("api_base_url")
    if not _stored_token_is_usable(token) or not isinstance(base, str) or not base:
        _storage.forget_account(owner_id)
        return {"connected": False}

    try:
        await _revoke_token(api_base_url=base, token=token)
    except _client.InvidiousTransportError as exc:
        raise TimedMediaError(
            "Invidious account disconnection request failed. The saved connection was kept so it can be retried."
        ) from exc
    except TimedMediaError:
        # Do not delete first: if the instance is temporarily unavailable, doing
        # so would leave a valid token registered upstream with no local revoke.
        raise

    _storage.forget_account(owner_id)
    return {"connected": False}


__all__ = [
    "ACCOUNT_SCOPES",
    "CALLBACK_PATH",
    "FLOW_TIMEOUT_S",
    "begin_invidious_account_authorization",
    "complete_invidious_account_authorization",
    "disconnect_invidious_account",
    "invidious_account_status",
    "invidious_redirect_uri",
]
