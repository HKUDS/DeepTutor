"""
Web Search Provider Registry

This module manages the registration and retrieval of search providers.
"""

from typing import Type

from deeptutor.services.config import (
    DEPRECATED_SEARCH_PROVIDERS,
    SEARCH_FALLBACK_PROVIDER,
    search_missing_credential,
    search_provider_credentials,
    search_provider_spec,
    supported_search_providers_hint,
)

from ..base import BaseSearchProvider

_PROVIDERS: dict[str, Type[BaseSearchProvider]] = {}
_DEPRECATED_UNSUPPORTED: dict[str, str] = {
    name: f"Deprecated; use {supported_search_providers_hint()}."
    for name in sorted(DEPRECATED_SEARCH_PROVIDERS)
}


def register_provider(name: str):
    """
    Decorator to register a provider.

    Metadata that the rest of the app reads off the class — display name,
    which credentials it needs, whether it writes its own answer — is stamped
    on from ``SEARCH_PROVIDERS`` so the spec table stays the single source of
    truth. A name absent from that table (a deprecated provider, or one that
    was never wired up) stays importable but never enters the registry, so it
    cannot be selected.

    Args:
        name: Name to register the provider under.

    Returns:
        Decorator function.
    """

    def decorator(cls: Type[BaseSearchProvider]):
        key = name.lower()
        cls.name = key
        spec = search_provider_spec(key)
        if spec is None:
            return cls
        cls.display_name = spec.label
        cls.requires_api_key = spec.requires_api_key
        cls.supports_answer = spec.supports_answer
        _PROVIDERS[key] = cls
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
    List providers that can run right now — either they need no credentials, or
    a configured search profile supplies the ones they do need.

    Returns:
        list[str]: Sorted list of available provider names.
    """
    available = []
    for name in _PROVIDERS:
        api_key, base_url = search_provider_credentials(name)
        if not search_missing_credential(name, api_key, base_url):
            available.append(name)
    return sorted(available)


def get_providers_info() -> list[dict]:
    """
    Get full provider info for frontend/CLI display.

    Returns:
        list[dict]: List of provider info dicts with id, name, description,
        supports_answer, and which connection fields the provider needs.
    """
    providers_info = []
    for provider_id, cls in sorted(_PROVIDERS.items()):
        spec = search_provider_spec(provider_id)
        providers_info.append(
            {
                "id": provider_id,
                "name": cls.display_name,
                "description": cls.description,
                "supports_answer": cls.supports_answer,
                "requires_api_key": cls.requires_api_key,
                "requires_base_url": bool(spec and spec.requires_base_url),
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
                "requires_base_url": False,
                "status": "deprecated",
            }
        )
    return providers_info


def get_default_provider(**kwargs) -> BaseSearchProvider:
    """
    Get the default provider from Settings > Catalog.

    Args:
        **kwargs: Arguments to pass to provider constructor.

    Returns:
        BaseSearchProvider: Default provider instance.
    """
    from deeptutor.services.config import resolve_search_runtime_config

    provider_name = resolve_search_runtime_config().provider.lower()
    if provider_name not in _PROVIDERS and provider_name != "none":
        # Stale config naming a retired provider still gets a working default;
        # an explicit "none" keeps raising, since that means search is off.
        provider_name = SEARCH_FALLBACK_PROVIDER
    return get_provider(provider_name, **kwargs)


def _register_builtin_providers() -> None:
    # Import for side effects (register_provider decorators).
    from . import (
        aliyun_iqs,
        bocha,
        brave,
        doubao,
        duckduckgo,
        firecrawl,
        jina,
        perplexity,
        qianfan,
        searxng,
        serper,
        serply,
        tavily,
        zhipu,
    )

    _ = (
        aliyun_iqs,
        bocha,
        brave,
        doubao,
        duckduckgo,
        firecrawl,
        jina,
        perplexity,
        qianfan,
        searxng,
        serper,
        serply,
        tavily,
        zhipu,
    )


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
