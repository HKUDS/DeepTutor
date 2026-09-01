"""DeepTutor plugin package — entry-point discovery lives in ``loader``."""

from deeptutor.plugins.loader import (
    PluginManifest,
    discover_plugins,
    load_plugin_capability,
)
from deeptutor.plugins.manifest import parse_manifest

__all__ = [
    "PluginManifest",
    "discover_plugins",
    "load_plugin_capability",
    "parse_manifest",
]
