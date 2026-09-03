"""Secure per-owner Invidious account connections.

Invidious token authorization is deliberately small: DeepTutor sends the learner
to the instance's consent page, receives a signed token through a one-time
callback, verifies it by reading preferences, and stores only that token in the
owner-private secrets tree. No password or browser cookie is handled here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from deeptutor.multi_user.paths import owner_secrets_dir
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
_SECRETS_SUBDIR = ("private", "video-learning-invidious")
_MAX_TOKEN_BYTES = 8192


@dataclass(frozen=True, slots=True)
class _PendingFlow:
    owner_id: str
    api_base_url: str
    callback_url: str
    expires_at: float


def _asset_dir(owner_id: str) -> Path:
    path = owner_secrets_dir(owner_id)
    for part in _SECRETS_SUBDIR:
        path = path / part
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, stat.S_IRWXU)
    return path


def _store_path(owner_id: str) -> Path:
    return _asset_dir(owner_id) / "account.json"


def _pending_dir(owner_id: str) -> Path:
    path = _asset_dir(owner_id) / "pending"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


def _flow_path(owner_id: str, state: str) -> Path:
    # State never becomes a path segment. Besides avoiding traversal hazards,
    # hashing keeps a filesystem backup from disclosing a still-live callback
    # state to someone who can list filenames but not read owner-private files.
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return _pending_dir(owner_id) / f"{digest}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _pending_flow(path: Path) -> _PendingFlow | None:
    payload = _read_json(path)
    owner_id = payload.get("owner_id")
    api_base_url = payload.get("api_base_url")
    callback_url = payload.get("callback_url")
    expires_at = payload.get("expires_at")
    if (
        not isinstance(owner_id, str)
        or not owner_id
        or not isinstance(api_base_url, str)
        or not api_base_url
        or not isinstance(callback_url, str)
        or not callback_url
        or not isinstance(expires_at, (int, float))
    ):
        return None
    return _PendingFlow(
        owner_id=owner_id,
        api_base_url=api_base_url,
        callback_url=callback_url,
        expires_at=float(expires_at),
    )


def _purge_expired(owner_id: str, now: float | None = None) -> None:
    current = time.time() if now is None else now
    for path in _pending_dir(owner_id).glob("*.json"):
        flow = _pending_flow(path)
        if flow is None or flow.owner_id != owner_id or flow.expires_at <= current:
            path.unlink(missing_ok=True)


def _consume_pending_flow(owner_id: str, state: str) -> _PendingFlow | None:
    if not state:
        return None
    source = _flow_path(owner_id, state)
    claim = source.with_name(f".{source.name}.{secrets.token_hex(8)}.claim")
    try:
        # Same-filesystem rename is the one-time claim. It works across Uvicorn
        # workers and across restarts, unlike a process-local dictionary.
        source.rename(claim)
    except FileNotFoundError:
        return None
    try:
        flow = _pending_flow(claim)
    finally:
        claim.unlink(missing_ok=True)
    if flow is None or flow.owner_id != owner_id or flow.expires_at <= time.time():
        return None
    return flow


def _read(owner_id: str) -> dict[str, Any]:
    return _read_json(_store_path(owner_id))


def _write(owner_id: str, payload: dict[str, Any]) -> None:
    _write_private_json(_store_path(owner_id), payload)


def _forget(owner_id: str) -> None:
    _store_path(owner_id).unlink(missing_ok=True)


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

    _purge_expired(owner_id)
    state = secrets.token_urlsafe(32)
    separator = "&" if parsed_redirect.query else "?"
    callback_url = f"{redirect_uri}{separator}{urlencode({'state': state})}"
    authorize_url = f"{base}/authorize_token?{urlencode({'scopes': ','.join(ACCOUNT_SCOPES), 'callback_url': callback_url})}"

    # Starting again replaces the prior pending consent for this owner and
    # instance. The browser can then follow only the most recent redirect.
    for path in _pending_dir(owner_id).glob("*.json"):
        flow = _pending_flow(path)
        if flow is None or flow.owner_id != owner_id or flow.api_base_url == base:
            path.unlink(missing_ok=True)
    _write_private_json(
        _flow_path(owner_id, state),
        {
            "version": 1,
            "owner_id": owner_id,
            "api_base_url": base,
            "callback_url": callback_url,
            "expires_at": time.time() + FLOW_TIMEOUT_S,
        },
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


def _bearer_token(token: dict[str, Any]) -> str:
    return json.dumps(token, ensure_ascii=False, separators=(",", ":"))


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


async def _request_preferences(*, api_base_url: str, token: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        try:
            response = await client.get(
                f"{api_base_url}/api/v1/auth/preferences",
                headers={"Authorization": f"Bearer {_bearer_token(token)}"},
            )
        except httpx.HTTPError as exc:
            raise TimedMediaError("Invidious account verification request failed.") from exc
    if response.status_code != 200:
        raise TimedMediaError(
            f"Invidious account verification failed with HTTP {response.status_code}."
        )
    try:
        preferences = response.json()
    except ValueError as exc:
        raise TimedMediaError("Invidious returned invalid account preferences.") from exc
    if not isinstance(preferences, dict):
        raise TimedMediaError("Invidious returned invalid account preferences.")
    return preferences


async def complete_invidious_account_authorization(
    *, owner_id: str, state: str, token: str
) -> dict[str, Any]:
    _purge_expired(owner_id)
    flow = _consume_pending_flow(owner_id, state)
    if flow is None:
        raise TimedMediaError("Invidious account callback is unknown, expired, or already used.")

    parsed_token = _parse_token(token)
    await _request_preferences(api_base_url=flow.api_base_url, token=parsed_token)

    _write(
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
    payload = _read(owner_id)
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


async def _revoke_token(*, api_base_url: str, token: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.post(
            f"{api_base_url}/api/v1/auth/tokens/unregister",
            headers={"Authorization": f"Bearer {_bearer_token(token)}"},
            json={"session": token["session"]},
        )
    if response.status_code < 200 or response.status_code >= 300:
        raise TimedMediaError(
            f"Invidious account disconnection failed with HTTP {response.status_code}."
        )


async def disconnect_invidious_account(*, owner_id: str) -> dict[str, Any]:
    payload = _read(owner_id)
    token = payload.get("token")
    base = payload.get("api_base_url")
    if not _stored_token_is_usable(token) or not isinstance(base, str) or not base:
        _forget(owner_id)
        return {"connected": False}

    try:
        await _revoke_token(api_base_url=base, token=token)
    except httpx.HTTPError as exc:
        raise TimedMediaError(
            "Invidious account disconnection request failed. The saved connection was kept so it can be retried."
        ) from exc
    except TimedMediaError:
        # Do not delete first: if the instance is temporarily unavailable, doing
        # so would leave a valid token registered upstream with no local revoke.
        raise

    _forget(owner_id)
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
