"""Zhipu (智谱 GLM) web search provider.

API: https://open.bigmodel.cn/api/paas/v4/web_search

This is Zhipu's standalone search endpoint, not the ``web_search`` tool bolted
onto chat completions -- it returns ranked rows and never a model-written
answer, so consolidation supplies the answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

# Four back-ends with different quality/price points; `search_std` is cheapest.
_ENGINES = ("search_std", "search_pro", "search_pro_sogou", "search_pro_quark")
_RECENCY = ("noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear")
# The API rejects longer queries outright rather than truncating them.
_QUERY_LIMIT = 70


@register_provider("zhipu")
class ZhipuProvider(BaseSearchProvider):
    """Zhipu GLM web search provider."""

    description = "Zhipu GLM web search (智谱)"
    BASE_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
    API_KEY_ENV_VARS = ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_engine: str = "search_std",
        content_size: str = "medium",
        search_recency_filter: str = "noLimit",
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search Zhipu.

        Args:
            query: Search query. Truncated to 70 chars, which the API enforces.
            max_results: Result cap (1-50).
            search_engine: One of ``search_std``, ``search_pro``,
                ``search_pro_sogou``, ``search_pro_quark``.
            content_size: ``medium`` or ``high`` -- how much body text each row
                carries.
            search_recency_filter: Time window; one of ``noLimit``/``oneDay``/
                ``oneWeek``/``oneMonth``/``oneYear``.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url`` and
                ``search_domain_filter``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        if search_engine not in _ENGINES:
            raise ValueError(
                f"Zhipu search_engine must be one of {list(_ENGINES)}, got {search_engine!r}."
            )
        if search_recency_filter not in _RECENCY:
            raise ValueError(
                f"Zhipu search_recency_filter must be one of {list(_RECENCY)}, got {search_recency_filter!r}."
            )
        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        payload: dict[str, Any] = {
            "search_query": query[:_QUERY_LIMIT],
            "search_engine": search_engine,
            "search_intent": False,
            "count": max(1, min(int(max_results), 50)),
            "search_recency_filter": search_recency_filter,
            "content_size": content_size,
        }
        domain_filter = kwargs.get("search_domain_filter")
        if domain_filter:
            payload["search_domain_filter"] = domain_filter

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.post(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Zhipu API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        rows = data.get("search_result") or []

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("title", ""))
            url = str(row.get("link", ""))
            # Zhipu returns one body field; it doubles as snippet and content.
            content = str(row.get("content", "") or "")
            media = str(row.get("media", "") or "")
            date = str(row.get("publish_date", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=content,
                    date=date,
                    source=media or "Zhipu",
                    content=content,
                )
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=content,
                    date=date,
                    source=media or "Zhipu",
                    content=content,
                    icon=str(row.get("icon", "") or ""),
                    website=media,
                )
            )

        return WebSearchResponse(
            query=query,
            answer="",
            provider="zhipu",
            timestamp=datetime.now().isoformat(),
            model=search_engine,
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop", "request_id": data.get("request_id", "")},
        )
