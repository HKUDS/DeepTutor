# -*- coding: utf-8 -*-
"""
Web Search Base Provider - Abstract base class for all search providers

This module defines the BaseSearchProvider class that all search providers must inherit from.
All providers use a unified SEARCH_API_KEY environment variable.
"""

from abc import ABC, abstractmethod
import os
from typing import Any

from src.logging import get_logger

from .types import WebSearchResponse

# Unified API key environment variable
SEARCH_API_KEY_ENV = "SEARCH_API_KEY"


class BaseSearchProvider(ABC):
    """Abstract base class for search providers.

    All providers use a unified SEARCH_API_KEY environment variable.
    Each provider has its own BASE_URL defined as a class constant.
    """

    name: str = "base"
    display_name: str = "Base Provider"
    description: str = ""
    requires_api_key: bool = True
    supports_answer: bool = False  # Whether provider generates LLM answers
    BASE_URL: str = ""  # Each provider defines its own endpoint

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        """
        Initialize the provider.

        Args:
            api_key: API key for the provider. If not provided, will be read from SEARCH_API_KEY.
            **kwargs: Additional configuration options.
        """
        self.logger = get_logger(f"Search.{self.__class__.__name__}", level="INFO")
        self.api_key = api_key or self._get_api_key()
        self.config = kwargs

    def _get_api_key(self) -> str:
        """Get API key from unified SEARCH_API_KEY environment variable."""
        key = os.environ.get(SEARCH_API_KEY_ENV, "")
        if self.requires_api_key and not key:
            raise ValueError(
                f"{self.name} requires {SEARCH_API_KEY_ENV} environment variable. "
                f"Please set it before using this provider."
            )
        return key

    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> WebSearchResponse:
        """
        Execute search and return standardized response.

        Args:
            query: The search query.
            **kwargs: Provider-specific options.

        Returns:
            WebSearchResponse: Standardized search response.
        """
        pass

    def is_available(self) -> bool:
        """
        Check if provider is available (dependencies installed, API key set).

        Returns:
            bool: True if provider is available, False otherwise.
        """
        try:
            if self.requires_api_key:
                key = self.api_key or os.environ.get(SEARCH_API_KEY_ENV, "")
                if not key:
                    return False
            return True
        except (ValueError, ImportError):
            return False


__all__ = ["BaseSearchProvider", "SEARCH_API_KEY_ENV"]
