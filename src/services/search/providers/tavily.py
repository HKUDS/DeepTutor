# -*- coding: utf-8 -*-
"""
Tavily Search Provider

API Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search

Features:
- Research-focused search with relevance scoring
- Optional LLM-generated answers (include_answer=true)
- Full raw content extraction (include_raw_content=true)
- Topic filtering (general, news, finance)
- Time range filtering (day, week, month, year)
- Domain include/exclude lists
"""

from datetime import datetime
import json
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("tavily")
class TavilyProvider(BaseSearchProvider):
    """Tavily research-focused search provider"""

    name = "tavily"
    display_name = "Tavily"
    description = "Research-focused search"
    supports_answer = True
    BASE_URL = "https://api.tavily.com/search"

    def search(
        self,
        query: str,
        search_depth: str = "basic",  # basic, advanced
        topic: str = "general",  # general, news, finance
        max_results: int = 10,
        include_answer: bool = True,  # Get LLM-generated answer
        include_raw_content: bool = False,  # Get full page content
        include_images: bool = False,
        days: int | None = None,  # Time filter (1-365)
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        timeout: int = 60,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform research-focused search using Tavily API.

        Args:
            query: Search query.
            search_depth: Search depth - "basic" (faster) or "advanced" (more thorough).
            topic: Topic category - "general", "news", or "finance".
            max_results: Maximum number of results (1-20).
            include_answer: Include LLM-generated answer.
            include_raw_content: Include full raw content of pages.
            include_images: Include images in results.
            days: Filter results to last N days (1-365).
            include_domains: List of domains to include.
            exclude_domains: List of domains to exclude.
            timeout: Request timeout in seconds.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        self.logger.debug(f"Calling Tavily API depth={search_depth}, max_results={max_results}")
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
        }

        if days is not None:
            payload["days"] = days
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        response = requests.post(self.BASE_URL, json=payload, timeout=timeout)

        if response.status_code != 200:
            try:
                error_data = response.json()
            except (json.JSONDecodeError, ValueError):
                error_data = {"error": response.text}
            self.logger.error(f"Tavily API error: {response.status_code} - {error_data}")
            raise Exception(
                f"Tavily API error: {response.status_code} - "
                f"{error_data.get('error', response.text)}"
            )

        data = response.json()
        self.logger.debug(f"Tavily returned {len(data.get('results', []))} results")

        # Extract answer
        answer = data.get("answer", "")

        # Extract search results
        citations: list[Citation] = []
        search_results: list[SearchResult] = []

        for i, result in enumerate(data.get("results", []), 1):
            sr = SearchResult(
                title=result.get("title", ""),
                url=result.get("url", ""),
                snippet=result.get("content", ""),
                date=result.get("published_date", ""),
                source=result.get("source", ""),
                content=result.get("raw_content", ""),
                score=result.get("score", 0.0),
            )
            search_results.append(sr)

            citations.append(
                Citation(
                    id=i,
                    reference=f"[{i}]",
                    url=result.get("url", ""),
                    title=result.get("title", ""),
                    snippet=result.get("content", ""),
                    source=result.get("source", ""),
                    content=result.get("raw_content", ""),
                )
            )

        # Build metadata
        metadata: dict[str, Any] = {
            "finish_reason": "stop",
            "search_depth": search_depth,
            "topic": topic,
        }

        if data.get("images"):
            metadata["images"] = data["images"]
        if data.get("response_time"):
            metadata["response_time"] = data["response_time"]

        response_obj = WebSearchResponse(
            query=query,
            answer=answer,
            provider="tavily",
            timestamp=datetime.now().isoformat(),
            model=f"tavily-{search_depth}",
            citations=citations,
            search_results=search_results,
            usage={},  # Tavily doesn't provide token usage
            metadata=metadata,
        )

        return response_obj
