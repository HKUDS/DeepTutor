# -*- coding: utf-8 -*-
"""
Serper Google SERP Provider

API: https://serper.dev
Endpoint: https://google.serper.dev/{mode}

Features:
- Real-time Google search results (1-2 seconds)
- Modes: search, scholar
- Knowledge graph extraction
- People Also Ask extraction
- Related searches
- Very cheap: $1/1000 queries at scale
"""

from datetime import datetime
import json
from typing import Any

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


class SerperAPIError(Exception):
    """Serper API error"""

    pass


@register_provider("serper")
class SerperProvider(BaseSearchProvider):
    """Serper Google SERP provider"""

    display_name = "Serper"
    description = "Google SERP results"
    supports_answer = False  # Raw SERP results, no LLM answer
    BASE_URL = "https://google.serper.dev"

    def search(
        self,
        query: str,
        mode: str = "search",  # search, scholar
        num: int = 10,
        gl: str = "us",  # Country code
        hl: str = "en",  # Language code
        page: int = 1,
        autocorrect: bool = True,
        timeout: int = 30,
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform Google SERP search using Serper API.

        Args:
            query: Search query.
            mode: Search mode - "search" or "scholar".
            num: Number of results (default 10, max 100).
            gl: Country code (default "us").
            hl: Language code (default "en").
            page: Page number for pagination.
            autocorrect: Enable autocorrect (default True).
            timeout: Request timeout in seconds.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        self.logger.debug(f"Calling Serper API mode={mode}, num={num}")
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "q": query,
            "num": num,
            "gl": gl,
            "hl": hl,
            "page": page,
            "autocorrect": autocorrect,
        }

        url = f"{self.BASE_URL}/{mode}"
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)

        if response.status_code != 200:
            try:
                error_data = response.json()
            except (json.JSONDecodeError, ValueError):
                error_data = {"message": response.text}
            self.logger.error(f"Serper API error: {response.status_code} - {error_data}")
            raise SerperAPIError(
                f"Serper API error: {response.status_code} - "
                f"{error_data.get('message', response.text)}"
            )

        data = response.json()
        self.logger.debug(f"Serper returned {len(data.get('organic', []))} results")

        # Extract search results
        citations: list[Citation] = []
        search_results: list[SearchResult] = []

        # Both search and scholar return results in "organic" key
        results_key = "organic"

        for i, result in enumerate(data.get(results_key, []), 1):
            # Handle different result formats
            title = result.get("title", "")
            url_val = result.get("link", result.get("url", ""))
            snippet = result.get("snippet", result.get("description", ""))
            date = result.get("date", "")

            # Extract sitelinks if available
            sitelinks = []
            if result.get("sitelinks"):
                for sl in result["sitelinks"]:
                    sitelinks.append({"title": sl.get("title", ""), "link": sl.get("link", "")})

            # Build attributes dict with scholar-specific fields
            attributes: dict[str, Any] = result.get("attributes", {})

            # Scholar mode: extract publication info, citations, PDF URL, year
            if mode == "scholar":
                # publicationInfo is a string like "A Vaswani, N Shazeer... - Advances in neural..., 2017"
                if result.get("publicationInfo"):
                    attributes["publicationInfo"] = result["publicationInfo"]
                # citedBy is a number
                if result.get("citedBy") is not None:
                    attributes["citedBy"] = result["citedBy"]
                # pdfUrl is a direct link to PDF
                if result.get("pdfUrl"):
                    attributes["pdfUrl"] = result["pdfUrl"]
                # year is a number
                if result.get("year") is not None:
                    attributes["year"] = result["year"]
                # paper ID
                if result.get("id"):
                    attributes["paperId"] = result["id"]

            sr = SearchResult(
                title=title,
                url=url_val,
                snippet=snippet,
                date=date,
                source=result.get("source", ""),
                sitelinks=sitelinks,
                attributes=attributes,
            )
            search_results.append(sr)

            citations.append(
                Citation(
                    id=i,
                    reference=f"[{i}]",
                    url=url_val,
                    title=title,
                    snippet=snippet,
                    date=date,
                    source=result.get("source", ""),
                )
            )

        # Build metadata with rich SERP data
        metadata: dict[str, Any] = {
            "finish_reason": "stop",
            "mode": mode,
            "searchParameters": data.get("searchParameters", {}),
        }

        # Include knowledge graph if available
        if data.get("knowledgeGraph"):
            metadata["knowledgeGraph"] = data["knowledgeGraph"]

        # Include answer box if available
        if data.get("answerBox"):
            metadata["answerBox"] = data["answerBox"]

        # Include People Also Ask
        if data.get("peopleAlsoAsk"):
            metadata["peopleAlsoAsk"] = data["peopleAlsoAsk"]

        # Include related searches
        if data.get("relatedSearches"):
            metadata["relatedSearches"] = data["relatedSearches"]

        # Build answer from answer box or knowledge graph if available
        answer = ""
        if data.get("answerBox"):
            ab = data["answerBox"]
            answer = ab.get("answer", ab.get("snippet", ""))
        elif data.get("knowledgeGraph"):
            kg = data["knowledgeGraph"]
            answer = kg.get("description", "")

        return WebSearchResponse(
            query=query,
            answer=answer,
            provider="serper_scholar" if mode == "scholar" else "serper",
            timestamp=datetime.now().isoformat(),
            model=f"serper-{mode}",
            citations=citations,
            search_results=search_results,
            usage={},
            metadata=metadata,
        )
