"""Neutral plugin discovery for DeepTutor.

External packages register under the ``deeptutor.plugins`` entry-point group.
This module is intentionally domain-agnostic: it only discovers manifests and
instantiates ``BaseCapability`` subclasses.

Call sites already expect:

* ``discover_plugins() -> list[PluginManifest]``
* ``load_plugin_capability(manifest) -> BaseCapability | None``
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import inspect
import logging
from typing import Any

from deeptutor.core.capability_protocol import BaseCapability
from deeptutor.core.entry_points import load_entry_point_group

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "deeptutor.plugins"


@dataclass
class PluginManifest:
    """Static metadata for a discovered plugin."""

    name: str
    type: str  # "capability" | "tool" | …
    description: str = ""
    stages: list[str] = field(default_factory=list)
    version: str = "0.0.0"
    author: str = ""
    entry: str = ""


def discover_plugins() -> list[PluginManifest]:
    """Discover plugins registered via ``deeptutor.plugins`` entry points."""
    return load_entry_point_group(ENTRY_POINT_GROUP, _coerce_manifest, log=logger)


def load_plugin_capability(manifest: PluginManifest) -> BaseCapability | None:
    """Instantiate a capability plugin from *manifest*, or return ``None``."""
    if not manifest.entry:
        return None
    if manifest.entry.endswith("tool.py"):
        return None
    if manifest.type and manifest.type != "capability":
        return None

    obj = _resolve_entry(manifest.entry)
    return _instantiate_capability(obj)


def _coerce_manifest(ep_name: str, loaded: Any) -> PluginManifest | None:
    if isinstance(loaded, PluginManifest):
        if not loaded.name:
            loaded.name = ep_name
        return loaded

    if callable(loaded) and not _is_capability_class(loaded):
        # Manifest factory (not a BaseCapability subclass)
        produced = loaded()
        if isinstance(produced, PluginManifest):
            if not produced.name:
                produced.name = ep_name
            return produced
        if _is_capability_class(produced):
            return _manifest_from_capability_class(ep_name, produced)
        if isinstance(produced, BaseCapability):
            return _manifest_from_capability_instance(ep_name, produced)
        loaded = produced

    if _is_capability_class(loaded):
        return _manifest_from_capability_class(ep_name, loaded)

    if isinstance(loaded, BaseCapability):
        return _manifest_from_capability_instance(ep_name, loaded)

    plugin_manifest = getattr(loaded, "PLUGIN_MANIFEST", None)
    if isinstance(plugin_manifest, PluginManifest):
        if not plugin_manifest.name:
            plugin_manifest.name = ep_name
        return plugin_manifest

    create = getattr(loaded, "create_capability", None)
    if callable(create):
        cap = create()
        if isinstance(cap, BaseCapability):
            return _manifest_from_capability_instance(ep_name, cap)
        if _is_capability_class(cap):
            return _manifest_from_capability_class(ep_name, cap)

    logger.warning(
        "Plugin entry point %r did not yield a capability or PluginManifest.",
        ep_name,
    )
    return None


def _manifest_from_capability_class(ep_name: str, cls: type[BaseCapability]) -> PluginManifest:
    m = cls.manifest
    return PluginManifest(
        name=m.name or ep_name,
        type="capability",
        description=m.description or "",
        stages=list(m.stages or []),
        entry=_qualname(cls),
    )


def _manifest_from_capability_instance(ep_name: str, cap: BaseCapability) -> PluginManifest:
    return PluginManifest(
        name=cap.manifest.name or ep_name,
        type="capability",
        description=cap.manifest.description or "",
        stages=list(cap.manifest.stages or []),
        entry=_qualname(type(cap)),
    )


def _is_capability_class(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseCapability) and obj is not BaseCapability


def _qualname(obj: Any) -> str:
    module = getattr(obj, "__module__", "") or ""
    name = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", "")
    if module and name:
        return f"{module}:{name}"
    return str(name or obj)


def _resolve_entry(entry: str) -> Any:
    if ":" not in entry:
        return importlib.import_module(entry)
    module_path, attr_path = entry.split(":", 1)
    module = importlib.import_module(module_path)
    obj: Any = module
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def _instantiate_capability(obj: Any) -> BaseCapability | None:
    if isinstance(obj, BaseCapability):
        return obj
    if _is_capability_class(obj):
        return obj()
    if callable(obj) and not inspect.isclass(obj):
        produced = obj()
        if isinstance(produced, BaseCapability):
            return produced
        if _is_capability_class(produced):
            return produced()
    return None
