"""
Web Search Provider Registry

This module manages the registration and retrieval of search providers.
"""

from typing import Type

from deeptutor.services.config import get_env_store

from ..base import BaseSearchProvider

_PROVIDERS: dict[str, Type[BaseSearchProvider]] = {}
_DEPRECATED_UNSUPPORTED: dict[str, str] = {
    "exa": "Deprecated; use brave/tavily/jina/searxng/duckduckgo/perplexity/serper.",
    "baidu": "Deprecated; use brave/tavily/jina/searxng/duckduckgo/perplexity/serper.",
    "openrouter": "Deprecated; use brave/tavily/jina/searxng/duckduckgo/perplexity/serper.",
}


def register_provider(name: str):
    """
    Decorator to register a provider.

    Args:
        name: Name to register the provider under.

    Returns:
        Decorator function.
    """

    def decorator(cls: Type[BaseSearchProvider]):
        key = name.lower()
        if key in _DEPRECATED_UNSUPPORTED:
            cls.name = key
            return cls
        _PROVIDERS[key] = cls
        cls.name = key
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
        if name in _DEPRECATED_UNSUPPORTED:
            raise ValueError(f"Unsupported provider `{name}`: {_DEPRECATED_UNSUPPORTED[name]}")
        available = ", ".join(sorted(_PROVIDERS.keys()))
        deprecated = ", ".join(sorted(_DEPRECATED_UNSUPPORTED.keys()))
        raise ValueError(
            f"Unknown provider: {name}. Available: {available}. "
            f"Deprecated/unsupported: {deprecated}"
        )
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
                "status": "supported",
            }
        )
    for provider_id, reason in sorted(_DEPRECATED_UNSUPPORTED.items()):
        providers_info.append(
            {
                "id": provider_id,
                "name": provider_id,
                "description": reason,
                "supports_answer": False,
                "requires_api_key": False,
                "status": "deprecated",
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
    provider_name = get_env_store().get("SEARCH_PROVIDER", "brave").lower()
    if provider_name in _DEPRECATED_UNSUPPORTED:
        provider_name = "duckduckgo"
    return get_provider(provider_name, **kwargs)


def _register_builtin_providers() -> None:
    # Import for side effects (register_provider decorators).
    from . import brave, duckduckgo, jina, perplexity, searxng, serper, tavily

    _ = (brave, duckduckgo, jina, perplexity, searxng, serper, tavily)


_register_builtin_providers()

__all__ = [
    "register_provider",
    "get_provider",
    "list_providers",
    "get_available_providers",
    "get_providers_info",
    "get_default_provider",
    "_DEPRECATED_UNSUPPORTED",
]
