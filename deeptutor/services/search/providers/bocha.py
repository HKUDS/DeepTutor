"""Bocha (博查) search provider.

API: https://api.bochaai.com/v1/web-search

Bocha is a China-hosted search engine built for AI applications. Unlike the
``/v1/ai-search`` sibling endpoint, ``/v1/web-search`` returns plain SERP rows
with no model-written answer, so consolidation still supplies the answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

# Accepted by the API; anything else is rejected rather than ignored.
_FRESHNESS = {"noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"}


@register_provider("bocha")
class BochaProvider(BaseSearchProvider):
    """Bocha web search provider."""

    description = "China-hosted SERP for AI apps (博查)"
    BASE_URL = "https://api.bochaai.com/v1/web-search"
    API_KEY_ENV_VARS = ("BOCHA_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        freshness: str = "noLimit",
        summary: bool = True,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search Bocha.

        Args:
            query: Search query.
            max_results: Result cap. Bocha's own ``count`` accepts 1-50.
            freshness: Time window. One of ``noLimit``/``oneDay``/``oneWeek``/
                ``oneMonth``/``oneYear``, or a ``YYYY-MM-DD`` (optionally
                ``YYYY-MM-DD..YYYY-MM-DD``) range, which is passed through.
            summary: Ask for the long-form ``summary`` field per result. Left on
                because the short ``snippet`` alone is thin context for a model.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        # A dated range is legal too, so only bare words are validated.
        if freshness not in _FRESHNESS and not freshness[:1].isdigit():
            raise ValueError(
                f"Bocha freshness must be a date range or one of {sorted(_FRESHNESS)}, got {freshness!r}."
            )
        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        payload = {
            "query": query,
            "summary": summary,
            "freshness": freshness,
            "count": max(1, min(int(max_results), 50)),
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
            raise Exception(f"Bocha API error: {resp.status_code} - {resp.text}")

        payload_json = resp.json()
        # Bocha wraps failures in a 200 with a non-zero code.
        if payload_json.get("code") not in (200, 0, None):
            raise Exception(f"Bocha API error: {payload_json.get('msg') or payload_json}")
        data = payload_json.get("data") or {}
        rows = ((data.get("webPages") or {}).get("value")) or []

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            title = str(row.get("name", ""))
            url = str(row.get("url", ""))
            # `snippet` is the SERP blurb; `summary` is the longer extract.
            snippet = str(row.get("snippet", ""))
            content = str(row.get("summary", "") or "")
            site_name = str(row.get("siteName", "") or "")
            date = str(row.get("datePublished", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    date=date,
                    source=site_name or "Bocha",
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
                    source=site_name or "Bocha",
                    content=content,
                    icon=str(row.get("siteIcon", "") or ""),
                    website=site_name,
                )
            )

        return WebSearchResponse(
            query=query,
            answer="",
            provider="bocha",
            timestamp=datetime.now().isoformat(),
            model="bocha-web-search",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )
