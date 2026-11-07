# -*- coding: utf-8 -*-
"""
Web Search Types - Shared dataclasses and type definitions

This module defines the standardized types used across all search providers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Citation:
    """Standardized citation from search results"""

    id: int
    reference: str  # e.g., "[1]"
    url: str
    title: str = ""
    snippet: str = ""
    date: str = ""
    source: str = ""
    content: str = ""  # Full content if available
    # Additional fields for backward compatibility with legacy format
    type: str = "web"  # Citation type (web, pdf, etc.)
    icon: str = ""  # Source icon URL
    website: str = ""  # Website name
    web_anchor: str = ""  # Web anchor text


@dataclass
class SearchResult:
    """Individual search result item"""

    title: str
    url: str
    snippet: str
    date: str = ""
    source: str = ""
    content: str = ""  # Full content if available (e.g., from Jina)
    score: float = 0.0  # Relevance score if available
    # Additional fields for rich results
    sitelinks: list[dict[str, str]] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebSearchResponse:
    """Standardized response from any search provider"""

    query: str
    answer: str  # LLM-generated answer or empty for raw SERP providers
    provider: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    citations: list[Citation] = field(default_factory=list)
    search_results: list[SearchResult] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (backward compatible format)"""
        result = {
            "timestamp": self.timestamp,
            "query": self.query,
            "model": self.model,
            "provider": self.provider,
            "answer": self.answer,
            "response": {
                "content": self.answer,
                "role": "assistant",
                "finish_reason": self.metadata.get("finish_reason", "stop"),
            },
            "usage": self.usage,
            "citations": [
                {
                    "id": c.id,
                    "reference": c.reference,
                    "url": c.url,
                    "title": c.title,
                    "snippet": c.snippet,
                    "date": c.date,
                    "source": c.source,
                    "content": c.content,
                    "type": c.type,
                    "icon": c.icon,
                    "website": c.website,
                    "web_anchor": c.web_anchor,
                }
                for c in self.citations
            ],
            "search_results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "date": r.date,
                    "source": r.source,
                    "content": r.content,
                    "score": r.score,
                    "sitelinks": r.sitelinks,
                    "attributes": r.attributes,
                }
                for r in self.search_results
            ],
        }
        # Add any extra metadata that isn't already in the result
        for key, value in self.metadata.items():
            if key not in result and key != "finish_reason":
                result[key] = value
        return result


__all__ = ["Citation", "SearchResult", "WebSearchResponse"]
