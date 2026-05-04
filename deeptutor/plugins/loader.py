"""
Plugin Loader
=============

Discovers plugins under ``deeptutor/plugins/<name>/`` by reading their
``manifest.yaml`` and importing the declared ``capability.py`` entry point.

The loader is referenced from
``deeptutor.runtime.registry.capability_registry.CapabilityRegistry.load_plugins``
and from ``deeptutor.api.routers.plugins_api`` — both call sites already
treat ``ImportError`` and missing-attribute errors as benign, so the loader
stays a strict no-op when no plugins are installed.

Manifest contract (minimal)::

    name: sage
    version: 0.1.0
    type: companion              # informational
    description: "..."
    entry: capability.py:SageMemoryCompanion   # MODULE_BASENAME:CLASS

    # Optional — surfaced in the Playground listing only:
    stages: []
    author: ""

The loader also tolerates the historical AGENTS.md form where
``capability.py`` is implicit and only ``stages`` is given; in that case it
falls back to importing ``deeptutor.plugins.<name>.capability`` and grabs
the first ``BaseCapability`` subclass defined there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import logging
from pathlib import Path
from typing import Any

import yaml  # PyYAML is a top-level dependency

from deeptutor.core.capability_protocol import BaseCapability

logger = logging.getLogger(__name__)

_PLUGINS_DIR = Path(__file__).resolve().parent


@dataclass
class PluginManifest:
    """Lightweight view of a plugin's ``manifest.yaml``.

    The capability registry only reads ``name`` + ``entry``; the other
    fields are surfaced via the Playground ``/plugins/list`` endpoint.
    """

    name: str
    entry: str
    version: str = "0.0.0"
    type: str = "playground"
    description: str = ""
    stages: list[str] = field(default_factory=list)
    author: str = ""
    plugin_dir: Path | None = None


def _read_manifest(plugin_dir: Path) -> PluginManifest | None:
    manifest_path = plugin_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None
    try:
        data: dict[str, Any] = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning("Failed to parse plugin manifest %s", manifest_path, exc_info=True)
        return None

    name = str(data.get("name") or plugin_dir.name)
    entry = str(data.get("entry") or "capability.py")
    return PluginManifest(
        name=name,
        entry=entry,
        version=str(data.get("version") or "0.0.0"),
        type=str(data.get("type") or "playground"),
        description=str(data.get("description") or ""),
        stages=list(data.get("stages") or []),
        author=str(data.get("author") or ""),
        plugin_dir=plugin_dir,
    )


def discover_plugins() -> list[PluginManifest]:
    """Return a manifest for every plugin under ``deeptutor/plugins/<name>/``."""
    manifests: list[PluginManifest] = []
    if not _PLUGINS_DIR.exists():
        return manifests
    for entry in sorted(_PLUGINS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue
        manifest = _read_manifest(entry)
        if manifest is not None:
            manifests.append(manifest)
    return manifests


def _resolve_capability_class(manifest: PluginManifest) -> type[BaseCapability] | None:
    """Import the capability class declared by ``manifest.entry``."""
    package = f"deeptutor.plugins.{manifest.name}"

    entry = manifest.entry.strip()
    module_part, _, class_part = entry.partition(":")
    module_part = module_part.strip()
    class_part = class_part.strip()

    # Drop a trailing ``.py`` so callers can write ``capability.py:Cls``.
    if module_part.endswith(".py"):
        module_part = module_part[:-3]
    if not module_part:
        module_part = "capability"

    module_name = f"{package}.{module_part}" if "." not in module_part else module_part
    try:
        module = importlib.import_module(module_name)
    except Exception:
        logger.warning("Failed to import plugin module %s", module_name, exc_info=True)
        return None

    if class_part:
        cls = getattr(module, class_part, None)
        if cls is not None and isinstance(cls, type) and issubclass(cls, BaseCapability):
            return cls
        logger.warning(
            "Plugin %s declares entry %s but %s is not a BaseCapability subclass",
            manifest.name,
            entry,
            class_part,
        )
        return None

    # Fallback: pick the first BaseCapability subclass defined in the module.
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, BaseCapability) and obj is not BaseCapability:
            return obj
    logger.debug(
        "Plugin %s defines no BaseCapability subclass; treating as side-effect-only", manifest.name
    )
    return None


def load_plugin_capability(manifest: PluginManifest) -> BaseCapability | None:
    """Instantiate the capability declared by *manifest*.

    Returns ``None`` for plugins that intentionally have no capability
    (e.g. plugins that only register EventBus listeners) — the registry
    already handles ``None`` by skipping registration.
    """
    cls = _resolve_capability_class(manifest)
    if cls is None:
        return None
    try:
        return cls()
    except Exception:
        logger.warning("Failed to instantiate plugin capability %s", manifest.name, exc_info=True)
        return None
