"""SpecStream search provider.

API: https://specstream.ai/docs/search-api

SpecStream answers a question from the live web: a confirmed ``answer`` for
fact questions, ``rows`` for every value found, and ``sources`` for the pages
read in rank order. The endpoint takes only ``q`` -- there is no count
parameter -- so the result cap is applied client-side, like Aliyun IQS.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("specstream")
class SpecStreamProvider(BaseSearchProvider):
    """SpecStream answer-first web search provider."""

    description = "Answer-first live web search"
    BASE_URL = "https://api.specstream.ai/v1/web-search"
    API_KEY_ENV_VARS = ("SPECSTREAM_API_KEY", "SEARCH_API_KEY")

    def search(
        self,
        query: str,
        max_results: int = 5,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """Search SpecStream.

        Args:
            query: Search query in everyday words (1-2,000 chars).
            max_results: Result cap. Applied client-side -- the API has no
                count parameter and returns every source it read.
            timeout: Request timeout in seconds.
            **kwargs: Additional options, including ``base_url``.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        endpoint = str(kwargs.get("base_url") or self.BASE_URL)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        params = {"q": query}
        request_kwargs: dict[str, Any] = {"headers": headers, "params": params}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.get(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            raise Exception(f"SpecStream API error: {resp.status_code} - {resp.text}")

        data = resp.json().get("data") or {}
        cap = max(1, int(max_results))
        # The answer is written only when two sites print the value (or the
        # vote rates it likelier than not); rows keep every candidate found.
        answer = str((data.get("answer") or {}).get("value") or "")
        rows = (data.get("rows") or [])[:cap]
        sources = (data.get("sources") or [])[:cap]

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        for idx, src in enumerate(sources, 1):
            title = str(src.get("title", "") or "")
            url = str(src.get("url", "") or "")
            snippet = str(src.get("snippet", "") or "")
            site = str(src.get("site", "") or "")
            date = str(src.get("published", "") or "")
            search_results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    date=date,
                    source=site or "SpecStream",
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
                    source=site or "SpecStream",
                    website=site,
                )
            )

        metadata: dict[str, Any] = {"finish_reason": "stop", "kind": str(data.get("kind") or "")}
        if data.get("request_id"):
            metadata["request_id"] = data["request_id"]
        if data.get("took_ms") is not None:
            metadata["took_ms"] = data["took_ms"]
        # On a list request the rows are the results the query asked for;
        # nothing else in the standard response shape carries them.
        if rows:
            metadata["rows"] = [
                {
                    "name": row.get("name", ""),
                    "page": row.get("page", ""),
                    "probability": row.get("probability"),
                }
                for row in rows
            ]

        return WebSearchResponse(
            query=query,
            answer=answer,
            provider="specstream",
            timestamp=datetime.now().isoformat(),
            model="specstream-web-search",
            citations=citations,
            search_results=search_results,
            metadata=metadata,
        )
