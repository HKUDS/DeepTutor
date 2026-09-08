"""Zotero Web API v3 search tool for reference lookup in a user's library."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ZOTERO_API_BASE = "https://api.zotero.org"
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
DEFAULT_TIMEOUT_S = 15.0


class ZoteroSearchTool:
    """Query a Zotero user or group library via the Web API v3."""

    async def search(
        self,
        query: str,
        user_id: str,
        api_key: str = "",
        max_results: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        limit = min(max(int(max_results), 1), MAX_LIMIT)
        headers = {"Zotero-API-Version": "3"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = f"{ZOTERO_API_BASE}/users/{user_id}/items"
        params: dict[str, str | int] = {
            "q": query,
            "limit": limit,
            "format": "json",
            "itemType": "-attachment",  # exclude child attachments
        }
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            items = resp.json()
        return [self._normalize(item) for item in items if isinstance(item, dict)]

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        data = item.get("data", {})
        creators = data.get("creators", [])
        authors = [
            f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
            for c in creators
            if isinstance(c, dict)
        ]
        return {
            "title": data.get("title", "Untitled"),
            "item_type": data.get("itemType", ""),
            "authors": authors,
            "year": data.get("date", ""),
            "doi": data.get("DOI", ""),
            "url": data.get("url", ""),
            "abstract": data.get("abstractNote", ""),
            "zotero_key": data.get("key", ""),
            "zotero_url": item.get("links", {}).get("alternate", {}).get("href", ""),
        }


__all__ = ["ZoteroSearchTool"]
