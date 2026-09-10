"""Pluggable learning-resource providers.

Level-1 foundations for #961: declarative provider manifests, a neutral
lookup schema, durable enable/disable state, and one bundled offline
dictionary reference. External bridges are intentionally out of scope until
the lifecycle and permission model settles.
"""

from .manifest import PROVIDER_TYPES, ProviderManifest
from .protocol import LookupEntry, LookupRequest, LookupResult
from .reference import ReferenceOfflineDictionaryProvider
from .registry import (
    ResourceProviderRegistry,
    get_resource_provider_registry,
    is_provider_enabled,
    set_provider_enabled,
)

__all__ = [
    "PROVIDER_TYPES",
    "LookupEntry",
    "LookupRequest",
    "LookupResult",
    "ProviderManifest",
    "ReferenceOfflineDictionaryProvider",
    "ResourceProviderRegistry",
    "get_resource_provider_registry",
    "is_provider_enabled",
    "set_provider_enabled",
]
