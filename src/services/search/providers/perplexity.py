# -*- coding: utf-8 -*-
"""
Perplexity AI Search Provider

API: Uses perplexity Python package
Model: sonar (default)

Features:
- AI-powered search with LLM-generated answers
- Automatic citation extraction
- Usage tracking with cost information
"""

from datetime import datetime
from typing import Any

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider


@register_provider("perplexity")
class PerplexityProvider(BaseSearchProvider):
    """Perplexity AI search provider"""

    display_name = "Perplexity"
    description = "AI-powered search with answers"
    supports_answer = True
    BASE_URL = "https://api.perplexity.ai"  # Used by the perplexity package internally

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._client = None

    @property
    def client(self):
        """Lazy-load the Perplexity client."""
        if self._client is None:
            try:
                from perplexity import Perplexity
            except ImportError as e:
                raise ImportError(
                    "perplexityai module is not installed. To use Perplexity search, please install: "
                    "pip install perplexityai"
                ) from e
            self._client = Perplexity(api_key=self.api_key)
        return self._client

    def search(
        self,
        query: str,
        model: str = "sonar",
        system_prompt: str = "You are a helpful AI assistant. Provide detailed and accurate answers based on web search results.",
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform search using Perplexity API.

        Args:
            query: Search query.
            model: Model to use (default: sonar).
            system_prompt: System prompt for the model.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        self.logger.debug(f"Calling Perplexity API with model={model}")
        completion = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
        )

        if not completion.choices or len(completion.choices) == 0:
            raise ValueError("Perplexity API returned no choices")

        answer = completion.choices[0].message.content

        # Build usage info with safe attribute access
        usage_info: dict[str, Any] = {}
        if hasattr(completion, "usage") and completion.usage is not None:
            usage = completion.usage
            usage_info = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
            }
            if hasattr(usage, "cost") and usage.cost is not None:
                cost = usage.cost
                usage_info["cost"] = {
                    "total_cost": getattr(cost, "total_cost", 0),
                    "input_tokens_cost": getattr(cost, "input_tokens_cost", 0),
                    "output_tokens_cost": getattr(cost, "output_tokens_cost", 0),
                }

        # Build search results list
        search_results: list[SearchResult] = []
        if hasattr(completion, "search_results") and completion.search_results:
            for search_item in completion.search_results:
                search_results.append(
                    SearchResult(
                        title=getattr(search_item, "title", "") or "",
                        url=getattr(search_item, "url", "") or "",
                        snippet=getattr(search_item, "snippet", "") or "",
                        date=getattr(search_item, "date", "") or "",
                        source=str(getattr(search_item, "source", ""))
                        if getattr(search_item, "source", None)
                        else "",
                    )
                )

        # Build citations list
        citations: list[Citation] = []
        if hasattr(completion, "citations") and completion.citations:
            for i, citation_url in enumerate(completion.citations, 1):
                # Try to find matching search result for more info
                title = ""
                snippet = ""
                for sr in search_results:
                    if sr.url == citation_url:
                        title = sr.title
                        snippet = sr.snippet
                        break
                citations.append(
                    Citation(
                        id=i,
                        reference=f"[{i}]",
                        url=citation_url,
                        title=title,
                        snippet=snippet,
                    )
                )

        # Ensure answer is a string
        answer_str = str(answer) if answer else ""

        response = WebSearchResponse(
            query=query,
            answer=answer_str,
            provider="perplexity",
            timestamp=datetime.now().isoformat(),
            model=completion.model,
            citations=citations,
            search_results=search_results,
            usage=usage_info,
            metadata={
                "finish_reason": completion.choices[0].finish_reason,
            },
        )

        return response
