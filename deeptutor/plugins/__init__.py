"""DeepTutor plugin package — entry-point discovery lives in ``loader``."""

from deeptutor.plugins.loader import (
    PluginManifest,
    discover_plugins,
    load_plugin_capability,
)
from deeptutor.plugins.manifest import parse_manifest
from deeptutor.plugins.registry import PluginRegistry, get_plugin_registry

__all__ = [
    "PluginManifest",
    "PluginRegistry",
    "discover_plugins",
    "get_plugin_registry",
    "load_plugin_capability",
    "parse_manifest",
]
