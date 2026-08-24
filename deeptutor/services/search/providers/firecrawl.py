"""Firecrawl search provider.

API: https://api.firecrawl.dev/v2/search

Firecrawl searches and scrapes in one call: with ``scrapeOptions`` it returns
each hit's page body as markdown, so results carry real content rather than a
SERP blurb. That makes it the expensive-but-rich option next to plain SERP
providers, and it is why scraping is opt-in per call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

# Narrow the corpus; `research` and `pdf` are the useful ones for study material.
_CATEGORIES = ("github", "research", "pdf", "developer")


@register_provider("firecrawl")
class FirecrawlProvider(BaseSearchProvider):
    """Firecrawl search provider."""

    description = "Search with full-page markdown extraction"
    BASE_URL = "https://api.firecrawl.dev/v2/search"
    API_KEY_ENV_VARS = ("FIRECRAWL_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        scrape: bool = False,
        categories: list[str] | None = None,
        tbs: str | None = None,
        timeout: int = 60,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search Firecrawl.

        Args:
            query: Search query (max 500 chars, enforced by the API).
            max_results: Result cap (1-100 per source).
            scrape: Fetch each result's body as markdown. Off by default -- it
                bills per page scraped and multiplies latency, so the caller
                opts in when full text is actually wanted.
            categories: Restrict the corpus; any of ``github``, ``research``,
                ``pdf``, ``developer``.
            tbs: Time filter in Google syntax (e.g. ``qdr:w`` for the past week).
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        for category in categories or []:
            if category not in _CATEGORIES:
                raise ValueError(
                    f"Firecrawl category must be one of {list(_CATEGORIES)}, got {category!r}."
                )
        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        payload: dict[str, Any] = {
            "query": query,
            "limit": max(1, min(int(max_results), 100)),
            "sources": [{"type": "web"}],
            # The API's own timeout is milliseconds and bounded at 300s; keep it
            # just under the transport timeout so it fails on their side first.
            "timeout": max(1000, min(int(timeout) * 1000 - 1000, 300000)),
        }
        if categories:
            payload["categories"] = list(categories)
        if tbs:
            payload["tbs"] = tbs
        if scrape:
            payload["scrapeOptions"] = {"formats": [{"type": "markdown"}], "onlyMainContent": True}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.post(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Firecrawl API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        if not data.get("success", True):
            raise Exception(f"Firecrawl API error: {data.get('error') or data}")
        rows = (data.get("data") or {}).get("web") or []

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("title", "") or "")
            url = str(row.get("url", "") or "")
            snippet = str(row.get("description", "") or "")
            content = str(row.get("markdown", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="Firecrawl",
                    content=content,
                )
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    source="Firecrawl",
                    content=content,
                )
            )

        return WebSearchResponse(
            query=query,
            answer="",
            provider="firecrawl",
            timestamp=datetime.now().isoformat(),
            model="firecrawl-search",
            citations=citations,
            search_results=search_results,
            usage={"credits_used": data.get("creditsUsed", 0)},
            metadata={"finish_reason": "stop"},
        )
