"""WebRouter search provider (no API key required).

WebRouter (https://github.com/Nimbleway/webrouter) is an open-source library
that sends one search to whichever of its backends can serve it, falling back
from one to the next when a backend fails. With no key it uses keyless tiers;
each backend key found in the process environment (``TAVILY_API_KEY``,
``EXA_API_KEY``, ``BRAVE_SEARCH_API_KEY``, ...) adds that backend to the route.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("webrouter")
class WebRouterProvider(BaseSearchProvider):
    """Search through WebRouter's automatic backend routing."""

    description = "WebRouter search with backend fallback (no API key required)"
    API_KEY_ENV_VARS = ()

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search through WebRouter and return its rows as citations."""
        try:
            from web_router import WebRouter
        except ImportError as e:
            raise ImportError(
                "webrouter module is not installed. To use WebRouter search, please install: "
                "pip install webrouter"
            ) from e

        count = max(1, min(int(max_results), 20))
        with WebRouter() as router:
            response = router.search(
                query, max_results=count, timeout=float(timeout), data_apis=False
            )

        search_results = [_parse_row(row) for row in response.results[:count]]
        citations = [
            Citation(
                id=idx,
                reference=f"[{idx}]",
                url=result.url,
                title=result.title,
                snippet=result.snippet,
                date=result.date,
                source=result.source,
            )
            for idx, result in enumerate(search_results, 1)
        ]
        metadata: dict[str, Any] = {"finish_reason": "stop", "backend": response.provider}
        if response.request_id:
            metadata["request_id"] = response.request_id

        return WebSearchResponse(
            query=query,
            answer="",
            provider="webrouter",
            timestamp=datetime.now().isoformat(),
            model=f"webrouter:{response.provider}",
            citations=citations,
            search_results=search_results,
            metadata=metadata,
        )


def _parse_row(row: Any) -> SearchResult:
    url = str(row.url or "")
    host = urlsplit(url).hostname if url.startswith(("http://", "https://")) else ""
    return SearchResult(
        title=str(row.title or ""),
        url=url,
        snippet=str(row.description or row.content or ""),
        date=str(row.published_date or ""),
        source=host or "WebRouter",
    )
