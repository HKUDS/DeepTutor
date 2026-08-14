"""Baidu Qianfan (百度千帆) AI search provider.

API: https://qianfan.baidubce.com/v2/ai_search/web_search

Registered as ``qianfan`` rather than ``baidu``: the retired ``baidu`` provider
sits in ``DEPRECATED_SEARCH_PROVIDERS``, and reusing that key would keep this
one out of the registry. The name is also the accurate one -- this is Qianfan's
official search endpoint, not a scrape of baidu.com.

The response shape is where :class:`~deeptutor.services.search.types.Citation`
got its ``web_anchor`` / ``icon`` / ``website`` fields, so rows map across
one-for-one with no invention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

_RECENCY = ("week", "month", "semiyear", "year")
# Longer queries are rejected by the API rather than truncated.
_QUERY_LIMIT = 72
# Per-modality ceilings the API enforces.
_TOP_K_MAX = 50


@register_provider("qianfan")
class QianfanProvider(BaseSearchProvider):
    """Baidu Qianfan AI search provider."""

    description = "Baidu web search via Qianfan (百度千帆)"
    BASE_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    API_KEY_ENV_VARS = ("QIANFAN_API_KEY", "BAIDU_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        search_recency_filter: str | None = None,
        edition: str = "standard",
        safe_search: bool = False,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search Baidu Qianfan.

        Args:
            query: Search query. Truncated to 72 chars, which the API enforces.
            max_results: Result cap (``top_k``, max 50 for web).
            search_recency_filter: Time window; one of ``week``, ``month``,
                ``semiyear``, ``year``. ``None`` leaves it unbounded.
            edition: ``standard`` or ``turbo`` (faster, shallower).
            safe_search: Filter adult content.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        if search_recency_filter is not None and search_recency_filter not in _RECENCY:
            raise ValueError(
                f"Qianfan search_recency_filter must be one of {list(_RECENCY)}, got {search_recency_filter!r}."
            )
        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": query[:_QUERY_LIMIT]}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [
                {"type": "web", "top_k": max(1, min(int(max_results), _TOP_K_MAX))}
            ],
            "edition": edition,
            "safe_search": safe_search,
        }
        if search_recency_filter:
            payload["search_recency_filter"] = search_recency_filter

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.post(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Qianfan API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        # Errors arrive as a 200 carrying `code`/`message` and no references.
        # `code` is documented as error-only, but treat the success codes as
        # success rather than assuming any code at all means failure.
        if data.get("code") not in (None, 0, 200, "0", "200"):
            raise Exception(f"Qianfan API error: {data.get('code')} - {data.get('message')}")
        rows = data.get("references") or []

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("title", "") or "")
            url = str(row.get("url", "") or "")
            snippet = str(row.get("snippet", "") or "")
            content = str(row.get("content", "") or "")
            website = str(row.get("website", "") or "")
            date = str(row.get("date", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    date=date,
                    source=website or "Baidu",
                    content=content,
                )
            )
            citations.append(
                Citation(
                    # Qianfan numbers its own references; keep its id so the
                    # markers line up with anything echoing the raw payload.
                    id=int(row.get("id", idx) or idx),
                    reference=f"[{row.get('id', idx)}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    date=date,
                    source=website or "Baidu",
                    content=content,
                    type=str(row.get("type", "web") or "web"),
                    icon=str(row.get("icon", "") or ""),
                    website=website,
                    web_anchor=str(row.get("web_anchor", "") or ""),
                )
            )

        return WebSearchResponse(
            query=query,
            answer="",
            provider="qianfan",
            timestamp=datetime.now().isoformat(),
            model="baidu_search_v2",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop", "request_id": data.get("request_id", "")},
        )
