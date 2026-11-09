"""DeepSeek search provider.

API: https://api-docs.deepseek.com/guides/search/
Endpoint: POST https://api.deepseek.com/v1/tools/search

Standalone SERP access to DeepSeek's in-house search engine, usable with any
configured chat LLM — unlike the model-side ``web_search`` tool mapping, which
only applies when the LLM itself is a DeepSeek model. Rows are plain SERP
results with no model-written answer, so consolidation still supplies the
answer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("deepseek")
class DeepSeekProvider(BaseSearchProvider):
    """DeepSeek Search API (``POST /v1/tools/search``) results."""

    description = "DeepSeek in-house search engine results"
    BASE_URL = "https://api.deepseek.com/v1/tools/search"
    API_KEY_ENV_VARS = ("DEEPSEEK_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        need_content: bool = False,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search DeepSeek.

        Args:
            query: Search query (1-128 chars; supports ``site:``, ``lang:``,
                ``after:``/``before:`` and quoted-phrase operators verbatim).
            max_results: Result cap. DeepSeek's own ``count`` accepts 1-50.
            need_content: Ask for each page's body as Markdown in
                ``SearchResult.content``. Off by default so a wide query cannot
                push megabytes of page text into consolidation.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``, used
                verbatim as the endpoint for a self-hosted gateway.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        if not self.api_key:
            raise ValueError("DeepSeek requires an API key in Settings > Search.")
        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        count = max(1, min(int(max_results), 50))
        payload = {
            "query": query,
            "count": count,
            "need_content": bool(need_content),
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
            raise Exception(f"DeepSeek API error: {resp.status_code} - {resp.text}")
        rows = [row for row in resp.json().get("results") or [] if isinstance(row, dict)]
        rows = rows[:count]

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            result = _parse_row(row)
            search_results.append(result)
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=result.url,
                    title=result.title,
                    snippet=result.snippet,
                    date=result.date,
                    source=result.source,
                    content=result.content,
                    icon=str(row.get("site_icon") or ""),
                    website=str(row.get("site_name") or ""),
                )
            )

        return WebSearchResponse(
            query=query,
            answer="",
            provider="deepseek",
            timestamp=datetime.now().isoformat(),
            model="deepseek-search",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )


def _parse_row(row: dict[str, Any]) -> SearchResult:
    """Map one DeepSeek row onto ``SearchResult``.

    ``summary`` (600-800 chars) is written to be read by a model, so it wins
    over the UI-facing ``snippet``; ``content`` carries the page body when
    ``need_content`` was set. ``authority`` (0-4) and ``rerank_score`` (0-3)
    have no slot on ``SearchResult`` and travel in ``attributes``.
    """
    url = str(row.get("url", ""))
    site_name = str(row.get("site_name") or "")
    host = urlsplit(url).hostname if url.startswith(("http://", "https://")) else ""
    attributes: dict[str, Any] = {}
    if row.get("authority") is not None:
        attributes["authority"] = row["authority"]
    if row.get("rerank_score") is not None:
        attributes["rerank_score"] = row["rerank_score"]
    return SearchResult(
        title=str(row.get("title", "") or ""),
        url=url,
        snippet=str(row.get("summary") or row.get("snippet") or ""),
        date=str(row.get("date") or ""),
        source=site_name or host or "DeepSeek",
        content=str(row.get("content") or ""),
        attributes=attributes,
    )
