"""
Web Search Tool - Simple entry point for agents

This module provides a simple interface to the web search service.
All search logic is implemented in src/services/search/.

Usage:
    from src.tools.web_search import web_search

    # Simple usage
    result = web_search("What is AI?")

    # With provider
    result = web_search("What is AI?", provider="tavily")

Environment Variables:
    - SEARCH_PROVIDER: Default search provider (default: perplexity)
    - SEARCH_API_KEY: Unified API key for all providers

Available Providers:
    - perplexity: AI-powered search (default)
    - baidu: Baidu AI Search
    - tavily: Research-focused with optional answers
    - exa: Neural/embeddings search with summaries
    - serper: Google SERP results
    - jina: SERP with full content extraction
"""

# Re-export from services layer
from src.services.search import (
    CONSOLIDATION_TYPES,
    PROVIDER_TEMPLATES,
    SEARCH_API_KEY_ENV,
    AnswerConsolidator,
    BaseSearchProvider,
    Citation,
    SearchProvider,
    SearchResult,
    WebSearchResponse,
    get_available_providers,
    get_current_config,
    get_default_provider,
    get_provider,
    get_providers_info,
    list_providers,
    web_search,
)

__all__ = [
    # Main function
    "web_search",
    "get_current_config",
    # Provider management
    "get_provider",
    "list_providers",
    "get_available_providers",
    "get_default_provider",
    "get_providers_info",
    # Types
    "WebSearchResponse",
    "Citation",
    "SearchResult",
    # Consolidation
    "AnswerConsolidator",
    "CONSOLIDATION_TYPES",
    "PROVIDER_TEMPLATES",
    # Base class
    "BaseSearchProvider",
    "SearchProvider",
    "SEARCH_API_KEY_ENV",
]
