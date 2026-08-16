"""DuckDuckGo search provider (zero config)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("duckduckgo")
class DuckDuckGoProvider(BaseSearchProvider):
    """DuckDuckGo provider using `ddgs`."""

    description = "DuckDuckGo search (no API key required)"
    API_KEY_ENV_VARS = ()

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 20,
        **kwargs: Any,
    ) -> WebSearchResponse:
        from ddgs import DDGS

        count = max(1, min(int(max_results), 10))
        ddgs = DDGS(proxy=self.proxy, timeout=timeout)
        rows = list(ddgs.text(query, max_results=count) or [])
        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("title", ""))
            url = str(row.get("href", ""))
            snippet = str(row.get("body", ""))
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source="DuckDuckGo",
                )
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    source="DuckDuckGo",
                )
            )
        return WebSearchResponse(
            query=query,
            answer="",
            provider="duckduckgo",
            timestamp=datetime.now().isoformat(),
            model="duckduckgo",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )
