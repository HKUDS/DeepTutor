"""Tests for provider registry utilities."""

from src.services.llm import registry


def test_registry_register_and_lookup() -> None:
    """Registering a provider should make it discoverable."""

    class _Provider:
        pass

    name = "registry_test"
    registry._provider_registry.pop(name, None)
    try:
        decorated = registry.register_provider(name)(_Provider)

        assert registry.is_provider_registered(name) is True
        assert registry.get_provider_class(name) is decorated
        assert name in registry.list_providers()
    finally:
        registry._provider_registry.pop(name, None)
