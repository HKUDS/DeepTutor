"""SearchApi search provider.

API: https://www.searchapi.io
Docs: https://www.searchapi.io/docs/google
Endpoint: https://www.searchapi.io/api/v1/search?engine=<engine>&q=<query>

SearchApi serves live Google SERP rows plus the Google News and Google Scholar
verticals behind one key, selected with the ``engine`` parameter, so a study
session can go from "what is X" to "what do the papers say about X" without
switching providers. Every mode returns plain rows with no model-written
answer, so consolidation still supplies the answer.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

# mode -> SearchApi engine
_ENGINES: dict[str, str] = {
    "search": "google",
    "news": "google_news",
    "scholar": "google_scholar",
}


@register_provider("searchapi")
class SearchApiProvider(BaseSearchProvider):
    """SearchApi Google SERP / News / Scholar provider."""

    description = "Google SERP, News and Scholar results"
    BASE_URL = "https://www.searchapi.io/api/v1"
    API_KEY_ENV_VARS = ("SEARCHAPI_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        mode: str = "search",
        max_results: int = 5,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search SearchApi.

        Args:
            query: Search query.
            mode: ``search`` (Google web), ``news`` (Google News) or ``scholar``
                (Google Scholar).
            max_results: Result cap. Google retired ``num`` for web and news
                results, so those come one page (about 10 rows) at a time and
                are cut here; Scholar still honors ``num`` (1-20).
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``, the API root
                (``/search`` is appended) for a self-hosted gateway, and the
                optional Google ``gl`` / ``hl`` localisation codes.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        if mode not in _ENGINES:
            raise ValueError(f"SearchApi mode must be one of {sorted(_ENGINES)}, got {mode!r}.")
        engine = _ENGINES[mode]
        root = str(kwargs.get("base_url") or self.BASE_URL).rstrip("/")
        limit = max(1, int(max_results))
        params: dict[str, Any] = {"engine": engine, "q": query}
        if mode == "scholar":
            params["num"] = min(limit, 20)
        elif mode == "news":
            # Resolve Google's redirect links to the publisher's own URL.
            params["link"] = "resolved"
        for key in ("gl", "hl"):
            if kwargs.get(key):
                params[key] = kwargs[key]
        headers = {
            # The key travels only in the header, never in the URL.
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "DeepTutor",
        }
        request_kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        self.logger.debug(f"Calling SearchApi engine={engine}, max_results={limit}")
        resp = requests.get(f"{root}/search", timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("error") or resp.text
            except (json.JSONDecodeError, ValueError, AttributeError):
                detail = resp.text
            self.logger.error(f"SearchApi error: {resp.status_code} - {detail}")
            raise Exception(f"SearchApi API error: {resp.status_code} - {detail}")
        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise Exception("SearchApi API error: response was not valid JSON") from exc
        if not isinstance(payload, dict):
            payload = {}
        rows = [row for row in payload.get("organic_results") or [] if isinstance(row, dict)]
        rows = rows[:limit]

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, row in enumerate(rows, 1):
            result = _parse_row(mode, row)
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
                )
            )

        metadata: dict[str, Any] = {"finish_reason": "stop", "mode": mode}
        if payload.get("related_searches"):
            metadata["relatedSearches"] = payload["related_searches"]
        if payload.get("knowledge_graph"):
            metadata["knowledgeGraph"] = payload["knowledge_graph"]

        return WebSearchResponse(
            query=query,
            answer="",
            provider="searchapi_scholar" if mode == "scholar" else "searchapi",
            timestamp=datetime.now().isoformat(),
            model=f"searchapi-{engine}",
            citations=citations,
            search_results=search_results,
            metadata=metadata,
        )


def _parse_row(mode: str, row: dict[str, Any]) -> SearchResult:
    """Map one SearchApi row onto ``SearchResult``; each engine has its own shape."""
    title = str(row.get("title", ""))
    url = str(row.get("link", ""))
    snippet = str(row.get("snippet", "") or "")
    if mode == "news":
        return SearchResult(
            title=title,
            url=url,
            snippet=snippet,
            # ``iso_date`` is absolute; ``date`` is Google's "8 hours ago".
            date=str(row.get("iso_date") or row.get("date") or ""),
            source=str(row.get("source") or "Google News"),
        )
    if mode == "scholar":
        # Keyed like Serper's scholar rows so the shared academic template renders them.
        attributes: dict[str, Any] = {}
        authors = [
            author.get("name")
            for author in row.get("authors") or []
            if isinstance(author, dict) and author.get("name")
        ]
        publication = row.get("publication") or ", ".join(authors)
        if publication:
            attributes["publicationInfo"] = publication
        cited = ((row.get("inline_links") or {}).get("cited_by") or {}).get("total")
        if cited is not None:
            attributes["citedBy"] = cited
        pdf_url = (row.get("resource") or {}).get("link") or ""
        if pdf_url.startswith("http") and "javascript:" not in pdf_url:
            attributes["pdfUrl"] = pdf_url
        if row.get("data_cid"):
            attributes["paperId"] = row["data_cid"]
        return SearchResult(
            title=title,
            url=url,
            snippet=snippet,
            source="Google Scholar",
            attributes=attributes,
        )
    return SearchResult(
        title=title,
        url=url,
        snippet=snippet,
        date=str(row.get("date", "") or ""),
        source=str(row.get("source") or row.get("domain") or "Google"),
    )
