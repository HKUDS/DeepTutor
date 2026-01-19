# -*- coding: utf-8 -*-
"""
Web Search Provider Registry

This module manages the registration and retrieval of search providers.
"""

import os
from typing import Type

from ..base import BaseSearchProvider

_PROVIDERS: dict[str, Type[BaseSearchProvider]] = {}


def register_provider(name: str):
    """
    Decorator to register a provider.

    Args:
        name: Name to register the provider under.

    Returns:
        Decorator function.
    """

    def decorator(cls: Type[BaseSearchProvider]):
        _PROVIDERS[name.lower()] = cls
        cls.name = name.lower()
        return cls

    return decorator


def get_provider(name: str, **kwargs) -> BaseSearchProvider:
    """
    Get a provider instance by name.

    Args:
        name: Provider name (case-insensitive).
        **kwargs: Arguments to pass to provider constructor.

    Returns:
        BaseSearchProvider: Provider instance.

    Raises:
        ValueError: If provider is not found.
    """
    name = name.lower()
    if name not in _PROVIDERS:
        available = ", ".join(sorted(_PROVIDERS.keys()))
        raise ValueError(f"Unknown provider: {name}. Available: {available}")
    return _PROVIDERS[name](**kwargs)


def list_providers() -> list[str]:
    """
    List all registered providers.

    Returns:
        list[str]: Sorted list of provider names.
    """
    return sorted(_PROVIDERS.keys())


def get_available_providers() -> list[str]:
    """
    List providers that are currently available (have API keys set).

    Returns:
        list[str]: Sorted list of available provider names.
    """
    available = []
    for name, cls in _PROVIDERS.items():
        try:
            instance = cls()
            if instance.is_available():
                available.append(name)
        except Exception:
            pass
    return sorted(available)


def get_providers_info() -> list[dict]:
    """
    Get full provider info from class attributes for frontend display.

    Returns:
        list[dict]: List of provider info dicts with id, name, description, supports_answer
    """
    providers_info = []
    for provider_id, cls in sorted(_PROVIDERS.items()):
        providers_info.append(
            {
                "id": provider_id,
                "name": cls.display_name,
                "description": cls.description,
                "supports_answer": cls.supports_answer,
                "requires_api_key": cls.requires_api_key,
            }
        )
    return providers_info


def get_default_provider(**kwargs) -> BaseSearchProvider:
    """
    Get the default provider based on SEARCH_PROVIDER env var.

    Args:
        **kwargs: Arguments to pass to provider constructor.

    Returns:
        BaseSearchProvider: Default provider instance.
    """
    provider_name = os.environ.get("SEARCH_PROVIDER", "perplexity").lower()
    return get_provider(provider_name, **kwargs)


# Auto-import all providers to trigger registration
from . import baidu, exa, jina, perplexity, serper, tavily

__all__ = [
    "register_provider",
    "get_provider",
    "list_providers",
    "get_available_providers",
    "get_providers_info",
    "get_default_provider",
]
