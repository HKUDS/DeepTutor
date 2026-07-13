"""
Web Search Tool - Simple entry point for agents

This module provides a simple interface to the web search service.
All search logic is implemented in deeptutor/services/search/.

Usage:
    from deeptutor.tools.web_search import web_search

    # Simple usage
    result = web_search("What is AI?")

    # With provider
    result = web_search("What is AI?", provider="tavily")

Configuration:
    Search profiles live in data/user/settings/model_catalog.json.

Available Providers:
    - brave: Brave web search API
    - tavily: Research-focused with optional answers
    - jina: SERP with full content extraction
    - searxng: Self-hosted SearXNG endpoint
    - duckduckgo: Zero-config search
    - perplexity: AI-powered search with answers
"""

# Re-export from services layer
from deeptutor.services.search import (
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
    "PROVIDER_TEMPLATES",
    # Base class
    "BaseSearchProvider",
    "SearchProvider",
    "SEARCH_API_KEY_ENV",
]
