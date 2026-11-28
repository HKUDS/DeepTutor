"""Bowmark web search provider."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from urllib.parse import urlsplit

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("bowmark")
class BowmarkProvider(BaseSearchProvider):
    """Authenticated Bowmark web search results.

    Bowmark exposes typed functions for live web data behind a single run
    endpoint; this provider calls its web search function and maps the
    returned rows into the standard search response.
    """

    description = "Bowmark typed functions for live web data"
    BASE_URL = "https://api.bowmark.ai/v1"
    API_KEY_ENV_VARS = ("BOWMARK_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search the web through Bowmark's search.web function."""
        if not self.api_key:
            raise ValueError("Bowmark requires an API key in Settings > Catalog > Search.")
        root = str(kwargs.get("base_url") or self.BASE_URL).rstrip("/")
        count = max(1, min(int(max_results), 20))
        args = json.dumps({"query": query, "limit": count})
        headers = {
            "authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "deeptutor bowmark-integration/hkuds-deeptutor",
        }

        request_kwargs: dict[str, Any] = {
            "headers": headers,
            "json": {"script": f"return await bowmark.search.web({args})"},
        }
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}

        response = requests.post(f"{root}/run", timeout=timeout, **request_kwargs)
        if response.status_code != 200:
            raise Exception(f"Bowmark API error: {response.status_code} - {response.text}")
        body = response.json()
        if not body.get("ok"):
            raise Exception(f"Bowmark API error: {body.get('error', 'unknown error')}")

        result = body.get("result")
        rows = result.get("results") if isinstance(result, dict) else None
        rows = [row for row in rows or [] if isinstance(row, dict) and _has_web_url(row)]
        rows = rows[:count]

        search_results = [_parse_row(row) for row in rows]
        citations = [
            Citation(
                id=idx,
                reference=f"[{idx}]",
                url=item.url,
                title=item.title,
                snippet=item.snippet,
                date=item.date,
                source=item.source,
            )
            for idx, item in enumerate(search_results, 1)
        ]

        return WebSearchResponse(
            query=query,
            answer="",
            provider="bowmark",
            timestamp=datetime.now().isoformat(),
            model="bowmark-web-search",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )


def _has_web_url(row: dict[str, Any]) -> bool:
    return str(row.get("url", "") or "").startswith(("http://", "https://"))


def _parse_row(row: dict[str, Any]) -> SearchResult:
    url = str(row.get("url", "") or "")
    host = urlsplit(url).hostname
    return SearchResult(
        title=str(row.get("title", "") or ""),
        url=url,
        snippet=str(row.get("snippet", "") or ""),
        date=str(row.get("published", "") or ""),
        source=host or "Bowmark",
    )
