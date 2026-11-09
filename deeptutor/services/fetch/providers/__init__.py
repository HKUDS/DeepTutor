"""Web Fetch Provider Registry.

Adapters are registered against the ``FETCH_PROVIDERS`` spec table in
``deeptutor/services/config/provider_runtime.py``; metadata (display name,
which connection fields the backend needs) is stamped on the class from
that table so it stays the single source of truth — the same shape as the
search-provider registry.
"""

from __future__ import annotations

from typing import Any, Type

from deeptutor.services.config import fetch_provider_spec

from ..base import BaseFetchProvider

_PROVIDERS: dict[str, Type[BaseFetchProvider]] = {}


def register_fetch_provider(name: str):
    """Decorator registering a fetch-backend adapter under ``name``.

    A name absent from ``FETCH_PROVIDERS`` stays importable but never
    enters the registry, so it cannot be selected.
    """

    def decorator(cls: Type[BaseFetchProvider]) -> Type[BaseFetchProvider]:
        key = (name or "").strip().lower()
        cls.name = key
        spec = fetch_provider_spec(key)
        if spec is None:
            return cls
        cls.display_name = spec.label
        cls.requires_api_key = spec.requires_api_key
        cls.requires_base_url = spec.requires_base_url
        _PROVIDERS[key] = cls
        return cls

    return decorator


def get_fetch_provider(name: str, **kwargs: Any) -> BaseFetchProvider:
    """Instantiate the fetch backend registered under ``name``.

    Raises ``ValueError`` for an unknown name, mirroring the search
    registry's ``get_provider``.
    """
    from deeptutor.services.config import supported_fetch_providers_hint

    key = (name or "").strip().lower()
    if key not in _PROVIDERS:
        raise ValueError(
            f"Unknown fetch backend: {name}. Available: {supported_fetch_providers_hint()}."
        )
    return _PROVIDERS[key](**kwargs)


def list_fetch_providers() -> list[str]:
    """Sorted names of every registered fetch backend."""
    return sorted(_PROVIDERS.keys())


def _register_builtin_providers() -> None:
    # Import for side effects (register_fetch_provider decorators).
    from . import deepseek, local

    _ = (deepseek, local)


_register_builtin_providers()


__all__ = [
    "register_fetch_provider",
    "get_fetch_provider",
    "list_fetch_providers",
]
