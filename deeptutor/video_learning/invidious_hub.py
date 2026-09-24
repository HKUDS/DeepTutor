"""Public Invidious discovery feeds for Immersive Watching."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from deeptutor.video_learning.service import (
    VIDEO_ID_RE,
    TimedMediaError,
    load_video_learning_settings,
)

HUB_TABS = ("Popular", "Trending")
DEFAULT_TAB = "Popular"
MAX_FEED_ITEMS = 48
FEED_TIMEOUT_SECONDS = 12.0
TAB_ENDPOINTS = {
    "Popular": "/api/v1/popular",
    "Trending": "/api/v1/trending",
}


def normalize_hub_tab(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_TAB
    for tab in HUB_TABS:
        if raw.lower() == tab.lower():
            return tab
    raise TimedMediaError("Invidious hub tab must be Popular or Trending.")


def youtube_watch_url(video_id: str) -> str:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise TimedMediaError("Unsupported or invalid YouTube video.")
    return f"https://youtu.be/{video_id}"


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _thumbnail_url(item: dict[str, Any], video_id: str, public_base: str) -> str:
    thumbnails = item.get("videoThumbnails") or item.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumb in thumbnails:
            if not isinstance(thumb, dict):
                continue
            raw = str(thumb.get("url") or "").strip()
            if raw.startswith(("http://", "https://")):
                parsed = urlparse(raw)
                public = urlparse(public_base)
                same_public_origin = (
                    parsed.scheme in {"http", "https"}
                    and parsed.netloc.lower() == public.netloc.lower()
                )
                if same_public_origin:
                    return raw
            if raw.startswith("/") and public_base:
                return urljoin(f"{public_base}/", raw.lstrip("/"))
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _normalize_item(item: Any, public_base: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    video_id = str(item.get("videoId") or item.get("video_id") or "").strip()
    if not VIDEO_ID_RE.fullmatch(video_id):
        return None
    title = " ".join(str(item.get("title") or video_id).split()) or video_id
    return {
        "video_id": video_id,
        "title": title[:240],
        "author": " ".join(str(item.get("author") or item.get("authorName") or "").split())[:160],
        "author_id": str(item.get("authorId") or "").strip()[:64],
        "duration_seconds": _safe_int(item.get("lengthSeconds") or item.get("duration")),
        "thumbnail_url": _thumbnail_url(item, video_id, public_base),
        "view_count": _safe_int(item.get("viewCount")),
        "published_text": str(item.get("publishedText") or "").strip()[:80],
        "url": youtube_watch_url(video_id),
    }


async def get_public_feed(tab: str = "") -> dict[str, Any]:
    settings = load_video_learning_settings()
    api_base = str(settings["invidious"]["api_base_url"] or "").rstrip("/")
    public_base = str(settings["invidious"]["public_base_url"] or api_base).rstrip("/")
    if not api_base:
        raise TimedMediaError("Configure the Invidious API base URL before browsing videos.")

    current_tab = normalize_hub_tab(tab)
    endpoint = TAB_ENDPOINTS[current_tab]
    items: list[dict[str, Any]] = []
    reason = ""
    try:
        async with httpx.AsyncClient(
            timeout=FEED_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await client.get(f"{api_base}{endpoint}")
        if response.status_code != 200:
            reason = "unavailable"
        else:
            payload = response.json()
            rows = payload if isinstance(payload, list) else []
            for row in rows:
                normalized = _normalize_item(row, public_base)
                if normalized:
                    items.append(normalized)
                if len(items) >= MAX_FEED_ITEMS:
                    break
    except (httpx.HTTPError, ValueError, TypeError):
        reason = "unavailable"

    return {
        "current_tab": current_tab,
        "tabs": list(HUB_TABS),
        "items": items,
        "reason": reason,
        "invidious_public_base_url": public_base,
    }


__all__ = [
    "DEFAULT_TAB",
    "HUB_TABS",
    "MAX_FEED_ITEMS",
    "get_public_feed",
    "normalize_hub_tab",
    "youtube_watch_url",
]
