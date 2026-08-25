"""Invidious account authorization, home feeds and watch history synchronization.

All credentials are owner-private under ``data/system/user-secrets/<owner_id>``
and never exposed in settings, API responses or logs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from deeptutor.multi_user.paths import owner_secrets_dir
from deeptutor.services.config import runtime_settings
from deeptutor.video_learning.service import (
    TimedMediaError,
    _validate_instance_url,
)

logger = logging.getLogger(__name__)

INVIDIOUS_AUTH_SCOPES = (
    "GET:preferences,GET:feed,GET:playlists,GET:history,POST:history/*,POST:tokens/unregister"
)
STATE_EXPIRY_SECONDS = 600  # 10 minutes


class InvidiousTokenStore:
    """Owner-scoped storage for Invidious authentication tokens."""

    @staticmethod
    def _dir(owner_id: str) -> Path:
        base = owner_secrets_dir(owner_id) / "private" / "invidious"
        base.mkdir(parents=True, exist_ok=True)
        os.chmod(base, stat.S_IRWXU)
        return base

    @staticmethod
    def _path(owner_id: str) -> Path:
        return InvidiousTokenStore._dir(owner_id) / "token.json"

    @classmethod
    def get_token(cls, owner_id: str) -> str | None:
        path = cls._path(owner_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                token = str(data.get("token") or "").strip()
                return token or None
        except (OSError, json.JSONDecodeError):
            logger.warning("Unreadable Invidious token file for owner %s", owner_id)
        return None

    @classmethod
    def set_token(cls, owner_id: str, token: str) -> None:
        token = token.strip()
        if not token:
            cls.delete_token(owner_id)
            return
        path = cls._path(owner_id)
        tmp = path.with_name(f"{path.name}.tmp")
        payload = {
            "token": token,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def delete_token(cls, owner_id: str) -> None:
        cls._path(owner_id).unlink(missing_ok=True)

    @classmethod
    def has_token(cls, owner_id: str) -> bool:
        return cls.get_token(owner_id) is not None


class AuthStateStore:
    """Thread-safe single-use state tokens with 10-minute expiry."""

    _lock = asyncio.Lock()
    _states: dict[str, dict[str, Any]] = {}

    @classmethod
    async def create_state(cls, owner_id: str, ttl_seconds: int = STATE_EXPIRY_SECONDS) -> str:
        state = secrets.token_urlsafe(32)
        now = time.time()
        async with cls._lock:
            cls._prune(now)
            cls._states[state] = {
                "owner_id": owner_id,
                "expires_at": now + ttl_seconds,
            }
        return state

    @classmethod
    async def validate_and_consume_state(cls, state: str) -> str | None:
        if not state:
            return None
        now = time.time()
        async with cls._lock:
            cls._prune(now)
            entry = cls._states.pop(state, None)
            if entry and entry["expires_at"] >= now:
                return str(entry["owner_id"])
        return None

    @classmethod
    def _prune(cls, now: float) -> None:
        expired = [k for k, v in cls._states.items() if v["expires_at"] < now]
        for k in expired:
            cls._states.pop(k, None)


def get_invidious_base_url() -> str:
    """Backend-reachable Invidious URL."""
    url = str(runtime_settings.load_integrations_settings().get("invidious_base_url") or "").strip()
    return _validate_instance_url(url) if url else ""


def get_invidious_public_base_url() -> str:
    """Browser/iPad-reachable Invidious URL for OAuth & external viewing."""
    settings = runtime_settings.load_integrations_settings()
    public_url = str(settings.get("invidious_public_base_url") or "").strip()
    if public_url:
        return _validate_instance_url(public_url)
    return get_invidious_base_url()


def get_callback_base_url(override: str | None = None) -> str:
    if override and override.strip():
        parsed = urlparse(override.strip().rstrip("/"))
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    system = runtime_settings.load_system_settings()
    base = str(system.get("next_public_api_base_external") or system.get("public_api_base") or "").strip()
    if not base:
        return ""
    parsed = urlparse(base.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


async def get_authorization_url(owner_id: str, external_api_base: str | None = None) -> str:
    public_base = get_invidious_public_base_url()
    if not public_base:
        raise TimedMediaError("Invidious instance is not configured in settings.")
    callback_base = get_callback_base_url(external_api_base)
    if not callback_base:
        raise TimedMediaError(
            "External public API base is not configured (system.next_public_api_base_external)."
        )
    state = await AuthStateStore.create_state(owner_id)
    callback_url = urljoin(callback_base.rstrip("/") + "/", "api/v1/video-learning/invidious/callback") + f"?state={state}"
    return (
        f"{public_base}/authorize_token"
        f"?scopes={quote(INVIDIOUS_AUTH_SCOPES, safe='')}"
        f"&callback_url={quote(callback_url, safe=':/?&=')}"
    )


async def disconnect_account(owner_id: str) -> bool:
    token = InvidiousTokenStore.get_token(owner_id)
    base_url = get_invidious_base_url()
    if token and base_url:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Authorization": f"Bearer {token}"}
                await client.post(f"{base_url}/api/v1/auth/tokens/unregister", headers=headers)
        except Exception as exc:
            logger.warning("Failed to unregister Invidious token upstream: %s", exc)
    InvidiousTokenStore.delete_token(owner_id)
    return True


async def get_user_preferences(owner_id: str) -> dict[str, Any] | None:
    token = InvidiousTokenStore.get_token(owner_id)
    base_url = get_invidious_base_url()
    if not token or not base_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(f"{base_url}/api/v1/auth/preferences", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, dict) else None
            if resp.status_code in {401, 403}:
                InvidiousTokenStore.delete_token(owner_id)
    except Exception as exc:
        logger.warning("Failed to fetch Invidious user preferences: %s", exc)
    return None


async def get_user_history_ids(owner_id: str) -> set[str]:
    token = InvidiousTokenStore.get_token(owner_id)
    base_url = get_invidious_base_url()
    if not token or not base_url:
        return set()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(f"{base_url}/api/v1/auth/history", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return {
                        str(row.get("videoId") or row.get("video_id") or "")
                        for row in data
                        if isinstance(row, dict) and (row.get("videoId") or row.get("video_id"))
                    }
            elif resp.status_code in {401, 403}:
                InvidiousTokenStore.delete_token(owner_id)
    except Exception as exc:
        logger.warning("Failed to fetch Invidious user history: %s", exc)
    return set()


async def sync_watch_history(owner_id: str, video_id: str) -> tuple[bool, str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        return False, "invalid_video_id"
    token = InvidiousTokenStore.get_token(owner_id)
    base_url = get_invidious_base_url()
    if not token or not base_url:
        return False, "unauthenticated"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.post(f"{base_url}/api/v1/auth/history/{video_id}", headers=headers)
            if resp.status_code in {200, 204}:
                return True, "synced"
            if resp.status_code == 409:
                return False, "history_disabled"
            if resp.status_code in {401, 403}:
                InvidiousTokenStore.delete_token(owner_id)
                return False, "auth_expired"
            return False, f"http_{resp.status_code}"
    except Exception as exc:
        logger.warning("Failed to sync watch history to Invidious for %s: %s", video_id, exc)
        return False, "network_error"


def _normalize_thumbnail(thumbnails: Any, video_id: str, public_base: str) -> str:
    if isinstance(thumbnails, list) and thumbnails:
        for thumb in thumbnails:
            if isinstance(thumb, dict) and thumb.get("url"):
                raw = str(thumb["url"]).strip()
                if raw.startswith(("http://", "https://")):
                    return raw
                if raw.startswith("/"):
                    return f"{public_base}{raw}" if public_base else raw
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""


def _normalize_feed_item(item: dict[str, Any], history_ids: set[str], public_base: str) -> dict[str, Any] | None:
    video_id = str(item.get("videoId") or item.get("video_id") or "").strip()
    if not video_id:
        return None
    title = str(item.get("title") or video_id).strip()
    author = str(item.get("author") or item.get("authorName") or "").strip()
    author_id = str(item.get("authorId") or "").strip()
    duration = 0
    try:
        duration = int(float(item.get("lengthSeconds") or item.get("duration") or 0))
    except (TypeError, ValueError):
        pass
    views = 0
    try:
        views = int(item.get("viewCount") or 0)
    except (TypeError, ValueError):
        pass
    published = str(item.get("publishedText") or "").strip()
    thumb = _normalize_thumbnail(item.get("videoThumbnails") or item.get("thumbnails"), video_id, public_base)
    return {
        "video_id": video_id,
        "title": title,
        "author": author,
        "author_id": author_id,
        "duration_seconds": duration,
        "thumbnail_url": thumb,
        "view_count": views,
        "published_text": published,
        "watched": video_id in history_ids,
    }


async def get_invidious_home_feed(owner_id: str, tab: str = "") -> dict[str, Any]:
    base_url = get_invidious_base_url()
    public_base = get_invidious_public_base_url()
    if not base_url:
        raise TimedMediaError("Invidious instance is not configured.")

    token = InvidiousTokenStore.get_token(owner_id)
    connected = bool(token)
    prefs: dict[str, Any] | None = None
    history_ids: set[str] = set()

    if connected:
        prefs = await get_user_preferences(owner_id)
        if prefs is not None:
            history_ids = await get_user_history_ids(owner_id)
        else:
            connected = False

    default_home = str((prefs or {}).get("default_home") or "Popular").strip()
    if default_home not in {"Popular", "Trending", "Subscriptions", "Playlists"}:
        default_home = "Popular"

    available_tabs = ["Popular", "Trending"]
    if connected:
        available_tabs = ["Popular", "Trending", "Subscriptions", "Playlists", "History"]

    current_tab = (tab or (default_home if default_home in available_tabs else "Popular")).strip()
    if current_tab not in available_tabs:
        current_tab = available_tabs[0]

    raw_items: list[Any] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            if current_tab == "Subscriptions" and connected:
                resp = await client.get(f"{base_url}/api/v1/auth/feed", headers=headers)
                if resp.status_code == 200:
                    raw_items = resp.json()
            elif current_tab == "Trending":
                resp = await client.get(f"{base_url}/api/v1/trending")
                if resp.status_code == 200:
                    raw_items = resp.json()
            elif current_tab == "Playlists" and connected:
                resp = await client.get(f"{base_url}/api/v1/auth/playlists", headers=headers)
                if resp.status_code == 200:
                    raw_items = resp.json()
            elif current_tab == "History" and connected:
                resp = await client.get(f"{base_url}/api/v1/auth/history", headers=headers)
                if resp.status_code == 200:
                    raw_items = resp.json()
            else:
                resp = await client.get(f"{base_url}/api/v1/popular")
                if resp.status_code == 200:
                    raw_items = resp.json()
        except Exception as exc:
            logger.warning("Failed to fetch Invidious feed for tab %s: %s", current_tab, exc)

    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            if isinstance(raw, dict):
                normalized = _normalize_feed_item(raw, history_ids, public_base)
                if normalized:
                    items.append(normalized)

    return {
        "connected": connected,
        "default_home": default_home,
        "current_tab": current_tab,
        "tabs": available_tabs,
        "items": items,
        "invidious_public_base_url": public_base,
    }


__all__ = [
    "AuthStateStore",
    "InvidiousTokenStore",
    "disconnect_account",
    "get_authorization_url",
    "get_callback_base_url",
    "get_invidious_base_url",
    "get_invidious_home_feed",
    "get_invidious_public_base_url",
    "get_user_history_ids",
    "get_user_preferences",
    "sync_watch_history",
]
