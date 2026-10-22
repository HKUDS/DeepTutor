"""You.com web search provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("you")
class YouComProvider(BaseSearchProvider):
    """You.com web rows with a keyless free tier and an optional keyed API."""

    description = "You.com web search results"
    FREE_BASE_URL = "https://api.you.com/v1/agents"
    KEYED_BASE_URL = "https://ydc-index.io/v1"
    BASE_URL = FREE_BASE_URL
    API_KEY_ENV_VARS = ("YDC_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search You.com and return its web rows as citations."""
        root = str(
            kwargs.get("base_url") or (self.KEYED_BASE_URL if self.api_key else self.FREE_BASE_URL)
        ).rstrip("/")
        params = {"query": query, "count": max(1, min(int(max_results), 100))}
        headers = {
            "Accept": "application/json",
            "User-Agent": "deeptutor youdotcom-integration/hkuds-deeptutor",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        request_kwargs: dict[str, Any] = {"params": params, "headers": headers}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}

        response = requests.get(f"{root}/search", timeout=timeout, **request_kwargs)
        if response.status_code != 200:
            raise Exception(f"You.com API error: {response.status_code} - {response.text}")
        payload = response.json()
        results = payload.get("results")
        rows = results.get("web") if isinstance(results, dict) else None
        rows = [row for row in rows or [] if isinstance(row, dict)][: params["count"]]

        search_results = [_parse_row(row) for row in rows]
        citations = [
            Citation(
                id=idx,
                reference=f"[{idx}]",
                url=result.url,
                title=result.title,
                snippet=result.snippet,
                date=result.date,
                source=result.source,
            )
            for idx, result in enumerate(search_results, 1)
        ]
        metadata = {"finish_reason": "stop"}
        response_metadata = payload.get("metadata")
        if isinstance(response_metadata, dict):
            for key in ("search_uuid", "latency"):
                if key in response_metadata:
                    metadata[key] = response_metadata[key]

        return WebSearchResponse(
            query=query,
            answer="",
            provider="you",
            timestamp=datetime.now().isoformat(),
            model="you-web-search",
            citations=citations,
            search_results=search_results,
            metadata=metadata,
        )


def _parse_row(row: dict[str, Any]) -> SearchResult:
    url = str(row.get("url", ""))
    snippets = row.get("snippets")
    snippet = (
        "\n".join(str(item) for item in snippets if str(item))
        if isinstance(snippets, list)
        else str(row.get("description", "") or "")
    )
    host = urlsplit(url).hostname if url.startswith(("http://", "https://")) else ""
    return SearchResult(
        title=str(row.get("title", "") or ""),
        url=url,
        snippet=snippet,
        date=str(row.get("page_age", "") or ""),
        source=host or "You.com",
    )
