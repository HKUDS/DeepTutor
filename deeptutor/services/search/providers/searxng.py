"""SearXNG search provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


class SearxngResponseError(ValueError):
    """The endpoint replied, but not with the SearXNG JSON search schema."""


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    try:
        parsed = urlparse(normalized if "://" in normalized else f"http://{normalized}")
        valid = parsed.scheme in {"http", "https"} and parsed.hostname
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise requests.exceptions.InvalidURL("SearXNG base_url must be a valid HTTP/HTTPS address.")
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
            # Keep the status for diagnostics, without echoing upstream bodies or keys.
            raise requests.HTTPError(
                f"SearXNG API returned HTTP {resp.status_code}.", response=resp
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SearxngResponseError("SearXNG search did not return valid JSON.") from exc
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SearxngResponseError("SearXNG JSON response is missing a valid results list.")
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
