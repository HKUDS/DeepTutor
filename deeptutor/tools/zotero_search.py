"""Zotero Web API v3 lookup for a user's public or authorized library."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ZOTERO_API_BASE = "https://api.zotero.org"
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
REQUEST_TIMEOUT_S = httpx.Timeout(15.0, connect=5.0)
_LIBRARY_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

ClientFactory = Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]


class ZoteroSearchError(Exception):
    """A normalized failure that can be presented without exposing secrets."""

    def __init__(self, code: str, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ZoteroSearchClient:
    """Query top-level Zotero items and return normalized reference metadata."""

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT_S,
                follow_redirects=True,
            )
        )

    async def search(
        self,
        *,
        query: str,
        user_id: str,
        api_key: str = "",
        max_results: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        user_id = str(user_id or "").strip()
        if not query:
            raise ValueError("Zotero query must be a non-empty string.")
        if not _LIBRARY_ID_RE.fullmatch(user_id):
            raise ValueError("Zotero user ID must be a non-empty URL-safe identifier.")

        try:
            limit = min(max(int(max_results), 1), MAX_LIMIT)
        except (TypeError, ValueError) as exc:
            raise ValueError("Zotero max_results must be an integer.") from exc

        headers = {"Zotero-API-Version": "3"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        params = {
            "format": "json",
            "itemType": "-attachment",
            "limit": limit,
            "q": query,
            "qmode": "titleCreatorYear",
        }
        url = f"{ZOTERO_API_BASE}/users/{user_id}/items/top"

        try:
            async with self._client_factory() as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise ZoteroSearchError("invalid_api_key", status) from exc
            if status == 404:
                raise ZoteroSearchError("library_not_found", status) from exc
            if status == 429:
                raise ZoteroSearchError("rate_limited", status) from exc
            raise ZoteroSearchError("request_failed", status) from exc
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.info("Zotero search request failed: %s", exc.__class__.__name__)
            raise ZoteroSearchError("network_unavailable") from exc
        except ValueError as exc:
            raise ZoteroSearchError("invalid_response") from exc

        if not isinstance(payload, list):
            raise ZoteroSearchError("invalid_response")
        return [
            self._normalize(item)
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("data"), dict)
        ]

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        data = item["data"]
        authors: list[str] = []
        for creator in data.get("creators") or []:
            if not isinstance(creator, dict):
                continue
            name = str(creator.get("name") or "").strip()
            if not name:
                first = str(creator.get("firstName") or "").strip()
                last = str(creator.get("lastName") or "").strip()
                name = f"{first} {last}".strip()
            if name:
                authors.append(name)

        date = str(data.get("date") or "").strip()
        year_match = re.match(r"\d{4}", date)
        links = item.get("links") if isinstance(item.get("links"), dict) else {}
        alternate = links.get("alternate") if isinstance(links.get("alternate"), dict) else {}
        return {
            "title": str(data.get("title") or "Untitled").strip() or "Untitled",
            "item_type": str(data.get("itemType") or "").strip(),
            "authors": authors,
            "year": year_match.group(0) if year_match else date,
            "doi": str(data.get("DOI") or "").strip(),
            "url": str(data.get("url") or "").strip(),
            "abstract": str(data.get("abstractNote") or "").strip(),
            "zotero_key": str(data.get("key") or "").strip(),
            "zotero_url": str(alternate.get("href") or "").strip(),
        }


__all__ = ["ClientFactory", "ZoteroSearchClient", "ZoteroSearchError"]
