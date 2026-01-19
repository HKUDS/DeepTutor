# -*- coding: utf-8 -*-
"""
Jina Reader Search Provider

API Docs: https://jina.ai/reader
Search Endpoint: https://s.jina.ai/{query}
Reader Endpoint: https://r.jina.ai/{url}

Features:
- Web search with SERP results (s.jina.ai)
- URL to clean content conversion (r.jina.ai)
- Returns clean, LLM-friendly text
- Automatic content extraction
- Image captioning support
- PDF support
- Free tier: 10M tokens
"""

from datetime import datetime
from typing import Any
import urllib.parse

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("jina")
class JinaProvider(BaseSearchProvider):
    """Jina Reader search provider"""

    display_name = "Jina"
    description = "SERP with content extraction (free tier)"
    supports_answer = False  # Returns raw content, not LLM answers
    requires_api_key = False  # Has free tier without API key
    BASE_URL = "https://s.jina.ai"

    def search(
        self,
        query: str,
        enrich: bool = True,
        timeout: int = 60,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform web search using Jina Reader API.

        Args:
            query: Search query.
            enrich: If True, fetch full content + images. If False, basic SERP only.
            timeout: Request timeout in seconds.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        headers: dict[str, str] = {
            "Accept": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if enrich:
            # Enriched mode: full content + images
            headers["X-Engine"] = "direct"
            headers["X-Timeout"] = str(timeout)
            headers["X-With-Images-Summary"] = "true"
        else:
            # Basic mode: SERP only, no content
            headers["X-Respond-With"] = "no-content"

        # URL encode the query
        encoded_query = urllib.parse.quote(query)
        url = f"{self.BASE_URL}/{encoded_query}"

        response = requests.get(url, headers=headers, timeout=timeout)

        if response.status_code != 200:
            self.logger.error(f"Jina API error: {response.status_code}")
            raise Exception(f"Jina API error: {response.status_code} - {response.text}")

        data = response.json()
        self.logger.debug(f"Jina returned {len(data.get('data', []))} results")

        # Extract search results
        citations: list[Citation] = []
        search_results: list[SearchResult] = []

        # Jina Search API returns results in 'data' array
        # Basic fields: title, url, description, date, content, usage
        # Enriched fields (enrich=true): images, publishedTime, metadata, external
        for i, result in enumerate(data.get("data", []), 1):
            # Build attributes dict for enriched fields
            attributes: dict[str, Any] = {}
            if result.get("images"):
                attributes["images"] = result["images"]
            if result.get("publishedTime"):
                attributes["publishedTime"] = result["publishedTime"]
            if result.get("metadata"):
                attributes["metadata"] = result["metadata"]
            if result.get("external"):
                attributes["external"] = result["external"]

            sr = SearchResult(
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("description", ""),
                date=result.get("date", ""),
                content=result.get("content", ""),
                attributes=attributes,
            )
            search_results.append(sr)

            citations.append(
                Citation(
                    id=i,
                    reference=f"[{i}]",
                    url=result.get("url", ""),
                    title=result.get("title", ""),
                    snippet=result.get("description", ""),
                    date=result.get("date", ""),
                    content=result.get("content", ""),
                )
            )

        # Build metadata
        metadata: dict[str, Any] = {
            "finish_reason": "stop",
            "code": data.get("code", 200),
            "status": data.get("status", 20000),
        }

        # Calculate total tokens - prefer meta.usage.tokens if available
        total_tokens = 0
        if data.get("meta", {}).get("usage", {}).get("tokens"):
            total_tokens = data["meta"]["usage"]["tokens"]
        else:
            # Fallback: sum per-result tokens
            for result in data.get("data", []):
                if result.get("usage", {}).get("tokens"):
                    total_tokens += result["usage"]["tokens"]

        usage: dict[str, Any] = {}
        if total_tokens > 0:
            usage["total_tokens"] = total_tokens

        response_obj = WebSearchResponse(
            query=query,
            answer="",  # Jina doesn't provide LLM answers
            provider="jina",
            timestamp=datetime.now().isoformat(),
            model="jina-reader",
            citations=citations,
            search_results=search_results,
            usage=usage,
            metadata=metadata,
        )

        return response_obj
