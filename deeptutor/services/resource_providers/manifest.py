"""Resource provider manifests.

A manifest is the declarative half of the provider contract: it tells
DeepTutor what the provider is, what languages it covers, and whether it
needs the network, without importing the provider implementation. Request
handling lives in :mod:`deeptutor.services.resource_providers.protocol`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PROVIDER_TYPE_DICTIONARY = "dictionary"
PROVIDER_TYPE_GLOSSARY = "glossary"
PROVIDER_TYPE_EXTERNAL_BRIDGE = "external_bridge"
PROVIDER_TYPES = frozenset(
    {
        PROVIDER_TYPE_DICTIONARY,
        PROVIDER_TYPE_GLOSSARY,
        PROVIDER_TYPE_EXTERNAL_BRIDGE,
    }
)


@dataclass(frozen=True)
class ProviderManifest:
    """Declarative description of one learning-resource provider."""

    name: str
    provider_type: str
    version: str
    languages: tuple[str, ...]
    offline: bool = True
    permissions: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("provider name must not be empty")
        if self.provider_type not in PROVIDER_TYPES:
            raise ValueError(
                f"unknown provider type {self.provider_type!r}; expected one of {sorted(PROVIDER_TYPES)}"
            )
        if not self.version or not self.version.strip():
            raise ValueError("provider version must not be empty")

    def to_payload(self) -> dict[str, object]:
        """Return the JSON-serializable manifest shape used by API/CLI."""
        return {
            "name": self.name,
            "type": self.provider_type,
            "version": self.version,
            "languages": list(self.languages),
            "offline": self.offline,
            "permissions": list(self.permissions),
            "description": self.description,
        }
