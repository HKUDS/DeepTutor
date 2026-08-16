"""Aliyun IQS (信息查询服务) search provider.

API: https://cloud-iqs.aliyuncs.com/search/genericSearch

The unified HTTP entry point, which authenticates with a plain ``X-API-Key``
header -- the OpenAPI-style host (``iqs.cn-zhangjiakou.aliyuncs.com``) wants
AK/SK request signing and would drag in the Aliyun SDK for no gain.

IQS returns page bodies and a rerank score alongside the usual SERP fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

_TIME_RANGE = ("NoLimit", "OneDay", "OneWeek", "OneMonth", "OneYear")
# Vertical corpora the engine can bias toward.
_INDUSTRY = ("finance", "law", "medical", "internet", "tax", "news_province", "news_center")
# IQS always returns a fixed page of 10; there is no count parameter, so the
# cap has to be applied here or every query hands the model 10 full page bodies.
_PAGE_SIZE = 10


def _publish_date(value: Any) -> str:
    """Render IQS's millisecond epoch as an ISO date, or pass text through."""
    if value in (None, "", 0):
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


@register_provider("aliyun_iqs")
class AliyunIQSProvider(BaseSearchProvider):
    """Aliyun IQS generic search provider."""

    description = "Aliyun IQS search with rerank (阿里云)"
    BASE_URL = "https://cloud-iqs.aliyuncs.com/search/genericSearch"
    API_KEY_ENV_VARS = ("ALIYUN_IQS_API_KEY", "IQS_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        time_range: str = "NoLimit",
        industry: str | None = None,
        return_main_text: bool = True,
        return_markdown_text: bool = False,
        enable_rerank: bool = True,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search Aliyun IQS.

        Args:
            query: Search query (1-500 chars; the engine prefers under 30).
            max_results: Result cap. Applied client-side -- IQS has no count
                parameter and always returns a page of 10.
            time_range: One of ``NoLimit``, ``OneDay``, ``OneWeek``,
                ``OneMonth``, ``OneYear``.
            industry: Bias toward a vertical corpus; one of ``finance``,
                ``law``, ``medical``, ``internet``, ``tax``, ``news_province``,
                ``news_center``.
            return_main_text: Include each page's body text.
            return_markdown_text: Also include a markdown rendering of the body.
            enable_rerank: Semantic rerank. On by default; turning it off saves
                roughly 140ms at the cost of ordering quality.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url`` and ``page``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        if time_range not in _TIME_RANGE:
            raise ValueError(
                f"IQS time_range must be one of {list(_TIME_RANGE)}, got {time_range!r}."
            )
        if industry is not None and industry not in _INDUSTRY:
            raise ValueError(f"IQS industry must be one of {list(_INDUSTRY)}, got {industry!r}.")

        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        params: dict[str, Any] = {
            "query": query,
            "timeRange": time_range,
            "page": int(kwargs.get("page", 1)),
            # requests serializes bools as "True"/"False"; the API wants lowercase.
            "returnMainText": str(return_main_text).lower(),
            "returnMarkdownText": str(return_markdown_text).lower(),
            "enableRerank": str(enable_rerank).lower(),
        }
        if industry:
            params["industry"] = industry

        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        request_kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.get(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"Aliyun IQS API error: {resp.status_code} - {resp.text}")

        data = resp.json()
        rows = (data.get("pageItems") or [])[: max(1, min(int(max_results), _PAGE_SIZE))]

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("title", "") or "")
            url = str(row.get("link", "") or "")
            snippet = str(row.get("snippet", "") or "")
            content = str(row.get("markdownText") or row.get("mainText") or "")
            page_map = row.get("pageMap") or {}
            site = str(row.get("displayLink") or page_map.get("hostname") or "")
            date = _publish_date(row.get("publishTime"))
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    date=date,
                    source=site or "Aliyun IQS",
                    content=content,
                    score=float(row.get("score") or 0.0),
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
                    source=site or "Aliyun IQS",
                    content=content,
                    icon=str(page_map.get("hostLogo", "") or ""),
                    website=site,
                )
            )

        info = data.get("searchInformation") or {}
        return WebSearchResponse(
            query=query,
            answer="",
            provider="aliyun_iqs",
            timestamp=datetime.now().isoformat(),
            model="iqs-generic-search",
            citations=citations,
            search_results=search_results,
            metadata={
                "finish_reason": "stop",
                "request_id": data.get("requestId", ""),
                "total_results": info.get("total", 0),
            },
        )
