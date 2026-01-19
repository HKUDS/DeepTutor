# -*- coding: utf-8 -*-
"""
LLM Provider Registry
====================

Simple provider registration system for LLM providers.
"""

from typing import Dict, Type

# Global registry for LLM providers
_provider_registry: Dict[str, Type] = {}


def register_provider(name: str):
    """
    Decorator to register an LLM provider class.

    Args:
        name: Name to register the provider under

    Returns:
        Decorator function
    """

    def decorator(cls):
        if name in _provider_registry:
            raise ValueError(f"Provider '{name}' is already registered")
        _provider_registry[name] = cls
        cls.__provider_name__ = name  # Store name on class for introspection
        return cls

    return decorator


def get_provider_class(name: str) -> Type:
    """
    Get a registered provider class by name.

    Args:
        name: Provider name

    Returns:
        Provider class

    Raises:
        KeyError: If provider is not registered
    """
    return _provider_registry[name]


def list_providers() -> list[str]:
    """
    List all registered provider names.

    Returns:
        List of provider names
    """
    return list(_provider_registry.keys())


def is_provider_registered(name: str) -> bool:
    """
    Check if a provider is registered.

    Args:
        name: Provider name

    Returns:
        True if registered, False otherwise
    """
    return name in _provider_registry
