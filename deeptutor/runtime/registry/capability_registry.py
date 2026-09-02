"""Compatibility view of turn capabilities backed by CapabilityCatalog."""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any
import warnings

from pydantic import BaseModel

from deeptutor.core.capability_protocol import TurnCapability
from deeptutor.core.entry_points import load_entry_point_group
from deeptutor.i18n.metadata_i18n import capability_description_i18n
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_CLASSES
from deeptutor.runtime.capability_catalog import (
    CapabilityCatalog,
    EmptyConfig,
    get_capability_catalog,
)
from deeptutor.runtime.request_contracts import CAPABILITY_CONFIG_MODELS

logger = logging.getLogger(__name__)

EXTENSIONS_GROUP = "deeptutor.extensions"
LEGACY_PLUGINS_GROUP = "deeptutor.plugins"


def _import_capability_class(path: str) -> type[TurnCapability]:
    module_path, class_name = path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _turn_factory(loaded: object) -> tuple[TurnCapability, type[TurnCapability]] | None:
    obj: Any = loaded
    if inspect.isclass(obj):
        instance = obj()
        factory = obj
    elif callable(obj) and not isinstance(obj, TurnCapability):
        produced = obj()
        if inspect.isclass(produced):
            instance = produced()
            factory = produced
        else:
            instance = produced
            factory = type(produced)
    else:
        instance = obj
        factory = type(obj)
    if not isinstance(instance, TurnCapability):
        return None
    return instance, factory


class CapabilityRegistry:
    """Legacy turn-only registry facade; every ``get`` creates an instance."""

    def __init__(self, catalog: CapabilityCatalog | None = None) -> None:
        self.catalog = catalog if catalog is not None else CapabilityCatalog()

    def register(
        self,
        capability: TurnCapability | type[TurnCapability] | Any,
        *,
        config_model: type[BaseModel] | None = None,
    ) -> None:
        resolved = _turn_factory(capability)
        if resolved is None:
            raise TypeError("Expected a TurnCapability class, factory, or instance")
        instance, factory = resolved
        model = config_model or CAPABILITY_CONFIG_MODELS.get(instance.name, EmptyConfig)
        self.catalog.register(
            name=instance.name,
            kind="turn",
            manifest=instance.manifest,
            factory=factory,
            config_model=model,
            replace=True,
        )
        logger.debug("Registered turn capability factory: %s", instance.name)

    def load_builtins(self) -> None:
        for name, class_path in BUILTIN_CAPABILITY_CLASSES.items():
            if self.catalog.get("turn", name) is not None:
                continue
            try:
                self.register(
                    _import_capability_class(class_path),
                    config_model=CAPABILITY_CONFIG_MODELS[name],
                )
            except Exception:
                logger.warning("Failed to load capability %s", name, exc_info=True)

    def load_plugins(self) -> None:
        """Load the canonical extension group, then the one-version legacy group."""

        def _accept(ep_name: str, loaded: object) -> str | None:
            resolved = _turn_factory(loaded)
            if resolved is None:
                return None
            instance, _factory = resolved
            if self.catalog.get("turn", instance.name) is not None:
                logger.warning("Turn extension %s is already registered; ignoring", ep_name)
                return None
            self.register(loaded)
            return instance.name

        load_entry_point_group(EXTENSIONS_GROUP, _accept, log=logger)

        try:
            module = importlib.import_module("deeptutor.plugins.loader")
            discover = getattr(module, "discover_plugins", None)
            load = getattr(module, "load_plugin_capability", None)
            manifests = list(discover()) if callable(discover) else []
            if manifests:
                warnings.warn(
                    f"{LEGACY_PLUGINS_GROUP} is deprecated; register under {EXTENSIONS_GROUP}",
                    DeprecationWarning,
                    stacklevel=2,
                )
            for manifest in manifests:
                if self.catalog.get("turn", manifest.name) is not None:
                    continue
                if manifest.entry.endswith("tool.py"):
                    continue
                capability = load(manifest) if callable(load) else None
                if capability is not None:
                    self.register(capability)
        except Exception:
            logger.debug("Legacy plugin loader unavailable", exc_info=True)

    def get(self, name: str) -> TurnCapability | None:
        capability = self.catalog.create("turn", name)
        return capability if isinstance(capability, TurnCapability) else None

    def list_capabilities(self) -> list[str]:
        return [entry.name for entry in self.catalog.entries("turn")]

    def get_manifests(self) -> list[dict[str, Any]]:
        return [
            {
                "name": entry.name,
                "kind": entry.kind,
                "description": entry.manifest.description,
                "description_i18n": capability_description_i18n(
                    entry.name,
                    entry.manifest.description,
                ),
                "stages": entry.manifest.stages,
                "tools_used": entry.manifest.tools_used,
                "cli_aliases": entry.manifest.cli_aliases,
                "request_schema": entry.config_model.model_json_schema(mode="validation"),
                "config_defaults": entry.manifest.config_defaults,
            }
            for entry in self.catalog.entries("turn")
        ]


_default_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = CapabilityRegistry(get_capability_catalog())
        _default_registry.load_builtins()
        _default_registry.load_plugins()
    return _default_registry


__all__ = [
    "CapabilityRegistry",
    "EXTENSIONS_GROUP",
    "get_capability_registry",
]
