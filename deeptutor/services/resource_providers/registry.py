"""Provider registry with durable enable/disable state.

Providers are registered in-process and addressed by manifest name.
Enabled state lives in ``resource_providers.json`` (workspace settings) so
disabling survives restarts and never depends on Python package changes.
Disabling a provider preserves its registration and configuration; it only
removes it from lookup routing.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.config.runtime_settings import (
    get_runtime_settings_service,
)

from .protocol import (
    LOOKUP_DISABLED,
    LOOKUP_ERROR,
    LOOKUP_NOT_FOUND,
    LookupRequest,
    LookupResult,
)

logger = logging.getLogger(__name__)


def load_provider_states(service: Any = None) -> dict[str, dict[str, Any]]:
    """Return the raw provider-state slice from workspace settings."""
    svc = service or get_runtime_settings_service()
    payload = svc.load_resource_providers()
    providers = payload.get("providers")
    return providers if isinstance(providers, dict) else {}


def is_provider_enabled(name: str, service: Any = None) -> bool:
    """Default is enabled: installing must not imply extra configuration."""
    state = load_provider_states(service).get(name)
    if not isinstance(state, dict):
        return True
    return bool(state.get("enabled", True))


def set_provider_enabled(name: str, enabled: bool, service: Any = None) -> None:
    """Persist one provider's enable/disable state atomically."""
    svc = service or get_runtime_settings_service()
    payload = svc.load_resource_providers()
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    state = providers.get(name)
    merged = dict(state) if isinstance(state, dict) else {}
    merged["enabled"] = bool(enabled)
    providers[name] = merged
    svc.save_resource_providers({"version": payload.get("version", 1), "providers": providers})


class ResourceProviderRegistry:
    """Holds in-process providers and routes bounded lookups."""

    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, provider: Any) -> None:
        manifest = provider.manifest
        self._providers[manifest.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def get(self, name: str) -> Any | None:
        return self._providers.get(name)

    def descriptions(self, service: Any = None) -> list[dict[str, Any]]:
        """Return manifest plus live state for API/CLI surfaces."""
        states = load_provider_states(service)
        rows: list[dict[str, Any]] = []
        for name, provider in sorted(self._providers.items()):
            state = states.get(name)
            enabled = bool(state.get("enabled", True)) if isinstance(state, dict) else True
            row = dict(provider.manifest.to_payload())
            row["enabled"] = enabled
            rows.append(row)
        return rows

    async def lookup(
        self,
        request: LookupRequest,
        *,
        provider_name: str = "",
        service: Any = None,
    ) -> LookupResult:
        """Route one lookup; failures degrade to explicit results."""
        candidates = self._route(request, provider_name)
        if not candidates:
            if provider_name:
                return LookupResult(
                    status=LOOKUP_ERROR,
                    provider=provider_name,
                    message=f"Provider {provider_name!r} is not registered",
                )
            return LookupResult(
                status=LOOKUP_NOT_FOUND,
                message="No enabled provider covers this language pair",
            )

        last_error = ""
        for provider in candidates:
            if not is_provider_enabled(provider.manifest.name, service):
                continue
            try:
                return await provider.lookup(request)
            except Exception as exc:  # provider crash must not break the caller
                logger.exception("Resource provider %s failed", provider.manifest.name)
                last_error = str(exc)
        if last_error:
            return LookupResult(status=LOOKUP_ERROR, message=last_error)
        return LookupResult(
            status=LOOKUP_DISABLED,
            message="All matching providers are disabled",
        )

    def _route(self, request: LookupRequest, provider_name: str) -> list[Any]:
        if provider_name:
            provider = self._providers.get(provider_name)
            return [provider] if provider else []
        pair = {request.source_lang, request.target_lang}
        matches = [
            provider
            for provider in self._providers.values()
            if pair.issubset({lang.lower() for lang in provider.manifest.languages})
        ]
        return matches


_registry: ResourceProviderRegistry | None = None


def get_resource_provider_registry() -> ResourceProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ResourceProviderRegistry()
        from .reference import ReferenceOfflineDictionaryProvider

        _registry.register(ReferenceOfflineDictionaryProvider())
    return _registry
