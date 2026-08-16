"""Brave search provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("brave")
class BraveProvider(BaseSearchProvider):
    """Brave web search provider."""

    description = "Brave web search API"
    BASE_URL = "https://api.search.brave.com/res/v1/web/search"
    API_KEY_ENV_VARS = ("BRAVE_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 20,
        **kwargs: Any,
    ) -> WebSearchResponse:
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": max(1, min(int(max_results), 10))}
        request_kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.get(self.BASE_URL, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Brave API error: {resp.status_code} - {resp.text}")
        payload = resp.json()
        rows = payload.get("web", {}).get("results", [])
        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("title", ""))
            url = str(row.get("url", ""))
            snippet = str(row.get("description", ""))
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="Brave",
                    date=str(row.get("age", "")),
                )
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    source="Brave",
                )
            )
        return WebSearchResponse(
            query=query,
            answer="",
            provider="brave",
            timestamp=datetime.now().isoformat(),
            model="brave-search",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )
