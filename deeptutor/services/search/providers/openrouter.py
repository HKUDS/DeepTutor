"""
OpenRouter Search Provider
==========================

API: Uses openai Python package with OpenRouter base URL
Model: perplexity/sonar (or other supported models)

Features:
- Compatible with OpenRouter's OpenAI-like API
- Extracts citations from response (supports 'citations' in root or choice)
- Maps string URLs to Citation objects
"""

from datetime import datetime
from typing import Any, List

from deeptutor.services.search.base import BaseSearchProvider
from deeptutor.services.search.providers import register_provider
from deeptutor.services.search.types import Citation, SearchResult, WebSearchResponse


@register_provider("openrouter")
class OpenRouterProvider(BaseSearchProvider):
    """OpenRouter search provider (wrapper for Perplexity models via OpenRouter)"""

    display_name = "OpenRouter"
    description = "Search via OpenRouter (Perplexity models)"
    supports_answer = True
    requires_api_key = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key, **kwargs)
        self._client = None
        # Default base URL for OpenRouter
        # Note: kwargs might override base_url if provided by config
        self.base_url = kwargs.get("base_url", "https://openrouter.ai/api/v1")

    @property
    def client(self):
        """Lazy-load the OpenAI client configured for OpenRouter."""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ImportError(
                    "openai module is not installed. To use OpenRouter search, please install: "
                    "pip install openai"
                ) from e

            if not self.api_key:
                raise ValueError("API Key is required for OpenRouter search provider.")

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def search(
        self,
        query: str,
        model: str = "perplexity/sonar",
        system_prompt: str = "You are a helpful AI assistant. Provide detailed and accurate answers based on web search results.",
        **kwargs: Any,
    ) -> WebSearchResponse:
        """
        Perform search using OpenRouter API.

        Args:
            query: Search query.
            model: Model to use (default: perplexity/sonar).
            system_prompt: System prompt for the model.
            **kwargs: Additional options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        self.logger.debug(f"Calling OpenRouter API with model={model}")

        completion = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            # Request citations explicitly
            extra_body={"return_citations": True},
        )

        if not completion.choices or len(completion.choices) == 0:
            raise ValueError("OpenRouter API returned no choices")

        choice = completion.choices[0]
        answer = choice.message.content or ""

        # Build usage info
        usage_info: dict[str, Any] = {}
        if completion.usage:
            usage = completion.usage
            usage_info = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }

        # Extract citations
        # OpenRouter returns citations in the root of the response object usually
        # But openai library models usage as Pydantic models, so we access via model_extra or dict

        citations_data = []
        raw_dict = completion.model_dump()

        # Check root level 'citations' (OpenRouter standard for Perplexity models)
        if "citations" in raw_dict:
            citations_data = raw_dict["citations"]
        elif "citations" in raw_dict.get("choices", [{}])[0]:
            citations_data = raw_dict["choices"][0]["citations"]

        citations: List[Citation] = []
        search_results: List[SearchResult] = []

        if citations_data:
            for i, cite_item in enumerate(citations_data, 1):
                url = ""
                if isinstance(cite_item, str):
                    url = cite_item
                elif isinstance(cite_item, dict):
                    url = cite_item.get("url", "")

                if url:
                    citations.append(
                        Citation(
                            id=i,
                            reference=f"[{i}]",
                            url=url,
                            title=f"Source {i}",  # Fallback as we don't get title
                            snippet="Content not available from meta-data.",  # Fallback
                            source="OpenRouter",
                        )
                    )
                    # Also populate search_results as some UI components might use it
                    search_results.append(
                        SearchResult(
                            title=f"Source {i}",
                            url=url,
                            snippet="Content not available from meta-data.",
                            source="OpenRouter",
                        )
                    )

        response = WebSearchResponse(
            query=query,
            answer=answer,
            provider="openrouter",
            timestamp=datetime.now().isoformat(),
            model=completion.model,
            citations=citations,
            search_results=search_results,
            usage=usage_info,
            metadata={
                "finish_reason": choice.finish_reason,
            },
        )

        return response
