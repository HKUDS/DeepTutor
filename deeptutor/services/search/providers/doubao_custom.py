"""Doubao Search Custom (豆包搜索 Custom版) provider.

API: https://open.feedcoopapi.com/search_api/web_search

This is the standalone SERP endpoint from the Volcengine "联网搜索 / 融合信息
搜索" console (API-Key access mode), distinct from the Ark Responses-API
``doubao`` provider which runs search as a built-in tool on a Doubao model.
The Custom API takes a plain query and returns SERP rows (optionally with
page content / AI summary), so consolidation supplies the answer — unlike the
Ark ``doubao`` provider this one reports ``supports_answer=False``.

Documentation: https://docs.volcengine.com/docs/87772/2272953
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

# "web_summary" was closed to new signups 2026-06-23; "web" is the safe default.
_SEARCH_TYPES = ("web", "web_summary")


@register_provider("doubao_custom")
class DoubaoCustomProvider(BaseSearchProvider):
    """Doubao Search Custom (豆包搜索 Custom版) SERP provider."""

    description = "Doubao Search Custom API (豆包搜索 Custom版)"
    BASE_URL = "https://open.feedcoopapi.com/search_api/web_search"
    API_KEY_ENV_VARS = ("DOUBAO_SEARCH_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_type: str = "web",
        need_summary: bool = True,
        need_content: bool = True,
        time_range: str = "",
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search Doubao Search Custom.

        Args:
            query: Search query.
            max_results: Result cap. The API accepts 1-50 (default 10).
            search_type: ``web`` (SERP rows) or ``web_summary`` (AI-summarized
                single passage; no longer open to new signups).
            need_summary: Ask for the per-result ``Summary`` extract (500-1000
                chars), the recommended field for LLM consumption.
            need_content: Ask for the full page ``Content`` body.
            time_range: Optional ISO time window (e.g. ``2026-01-01..2026-08-01``).
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        if search_type not in _SEARCH_TYPES:
            raise ValueError(
                f"Doubao Search search_type must be one of {list(_SEARCH_TYPES)}, got {search_type!r}."
            )

        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        payload = {
            "Query": query,
            "SearchType": search_type,
            "Count": max(1, min(int(max_results), 50)),
            "Filter": {
                "NeedContent": bool(need_content),
                "NeedUrl": True,
                "Sites": "",
                "BlockHosts": "",
                "AuthInfoLevel": 0,
            },
            "NeedSummary": bool(need_summary),
            "TimeRange": time_range or "",
            "QueryControl": {"QueryRewrite": False},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.post(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Doubao Search API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        result = data.get("Result") or {}
        if not isinstance(result, dict):
            raise Exception(f"Doubao Search API error: unexpected payload {str(data)[:300]}")

        rows = result.get("WebResults") or []
        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("Title", "") or "")
            url = str(row.get("Url", "") or "")
            snippet = str(row.get("Snippet", "") or "")
            content = str(row.get("Summary", "") or row.get("Content", "") or "")
            site_name = str(row.get("SiteName", "") or "")
            date = str(row.get("PublishTime", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    date=date,
                    source=site_name or "Doubao Search",
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
                    date=date,
                    source=site_name or "Doubao Search",
                    content=content,
                    website=site_name,
                )
            )

        return WebSearchResponse(
            query=query,
            answer="",
            provider="doubao_custom",
            timestamp=datetime.now().isoformat(),
            model=f"doubao-search-{search_type}",
            citations=citations,
            search_results=search_results,
            metadata={"result_count": result.get("ResultCount", len(rows))},
        )
