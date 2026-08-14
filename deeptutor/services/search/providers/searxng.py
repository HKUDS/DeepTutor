"""SearXNG search provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized if "://" in normalized else f"http://{normalized}")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("SearXNG base_url must use http/https")
    if not parsed.netloc:
        raise ValueError("SearXNG base_url is missing host")
    return parsed.geturl().rstrip("/")


@register_provider("searxng")
class SearxngProvider(BaseSearchProvider):
    """SearXNG provider."""

    description = "Self-hosted SearXNG endpoint"
    API_KEY_ENV_VARS = ()

    def search(
        self,
        query: str,
        base_url: str = "",
        max_results: int = 5,
        timeout: int = 20,
        **kwargs: Any,
    ) -> WebSearchResponse:
        if not base_url:
            raise ValueError("SearXNG requires base_url")
        endpoint = f"{_validate_base_url(base_url)}/search"
        params = {
            "q": query,
            "format": "json",
        }
        request_kwargs: dict[str, Any] = {"params": params}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.get(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"SearXNG API error: {resp.status_code} - {resp.text}")
        payload = resp.json()
        rows = payload.get("results", [])
        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows[: max(1, min(int(max_results), 10))], 1):
            title = str(row.get("title", ""))
            url = str(row.get("url", ""))
            snippet = str(row.get("content", ""))
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source=str(row.get("engine", "SearXNG")),
                )
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    source=str(row.get("engine", "SearXNG")),
                )
            )
        return WebSearchResponse(
            query=query,
            answer="",
            provider="searxng",
            timestamp=datetime.now().isoformat(),
            model="searxng",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )
