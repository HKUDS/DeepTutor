"""Compatibility view of turn capabilities backed by CapabilityCatalog."""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any
import warnings

from pydantic import BaseModel

from deeptutor.core.capability_protocol import TurnCapability
from deeptutor.i18n.metadata_i18n import capability_description_i18n
from deeptutor.plugins.entry_points import load_entry_point_group
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS
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
            factory = obj
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
        for name, spec in BUILTIN_CAPABILITY_SPECS.items():
            if self.catalog.get("turn", name) is not None:
                continue
            class_path = spec.class_path

            def _factory(path: str = class_path) -> TurnCapability:
                return _import_capability_class(path)()

            self.catalog.register(
                name=name,
                kind="turn",
                manifest=spec.manifest,
                factory=_factory,
                config_model=CAPABILITY_CONFIG_MODELS[name],
            )
            logger.debug("Registered lazy built-in turn capability: %s", name)

    def load_plugins(self) -> None:
        """Load the canonical extension group, then the one-version legacy group."""

        def _accept(ep_name: str, loaded: object) -> str | None:
            resolved = _turn_factory(loaded)
            if resolved is None:
                return None
            instance, _factory = resolved
            existing = self.catalog.get("turn", instance.name)
            if (
                existing is not None
                and getattr(existing.factory, "_plugin_allowed", lambda: True)()
            ):
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
        if name not in BUILTIN_CAPABILITY_SPECS:
            from deeptutor.plugins.registry import PluginRegistry
            from deeptutor.plugins.runtime import PluginWorkerCapability, runtime_plugin_records

            for record in runtime_plugin_records(PluginRegistry()):
                if (
                    record.status != "enabled"
                    or record.manifest is None
                    or record.installation is None
                ):
                    continue
                if any(
                    extension.type == "capability" and extension.id == name
                    for extension in record.manifest.extensions
                ):
                    return PluginWorkerCapability(
                        manifest=record.manifest,
                        installation=record.installation,
                        extension_id=name,
                    )
        if name not in BUILTIN_CAPABILITY_SPECS:
            self.load_plugins()
        entry = self.catalog.get("turn", name)
        if entry is not None and not getattr(entry.factory, "_plugin_allowed", lambda: True)():
            return None
        capability = self.catalog.create("turn", name)
        return capability if isinstance(capability, TurnCapability) else None

    def list_capabilities(self) -> list[str]:
        return [manifest["name"] for manifest in self.get_manifests()]

    def get_manifests(self) -> list[dict[str, Any]]:
        manifests = [
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
            if getattr(entry.factory, "_plugin_allowed", lambda: True)()
        ]
        from deeptutor.plugins.runtime import runtime_plugin_records

        known = {row["name"] for row in manifests}
        for record in runtime_plugin_records():
            if record.status != "enabled" or record.manifest is None:
                continue
            for extension in record.manifest.extensions:
                if extension.type != "capability" or extension.id in known:
                    continue
                manifests.append(
                    {
                        "name": extension.id,
                        "kind": "turn",
                        "description": record.description,
                        "description_i18n": dict(record.manifest.description_i18n),
                        "stages": [],
                        "tools_used": [],
                        "cli_aliases": [],
                        "request_schema": EmptyConfig.model_json_schema(mode="validation"),
                        "config_defaults": {},
                    }
                )
                known.add(extension.id)
        return manifests


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
