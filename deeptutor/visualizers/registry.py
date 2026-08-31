"""Registry composition for core, bundled and per-user visualizer types."""

from __future__ import annotations

import json
from pathlib import Path

from .builtin import bundled_visualizers, core_visualizers
from .protocol import VisualizerPlugin, manifest_public_dict
from .store import VisualizerStore, VisualizerStoreError


class VisualizerRegistry:
    def __init__(self, *, store: VisualizerStore | None = None) -> None:
        self.store = store or VisualizerStore()
        self._catalog: dict[str, VisualizerPlugin] = {}
        self._installed: set[str] = set()
        self._enabled: set[str] = set()
        self.reload()

    def reload(self) -> None:
        state = self.store.state()
        explicitly_installed = set(state["installed"])
        disabled = set(state["disabled"])
        uninstalled = set(state["uninstalled"])
        catalog: dict[str, VisualizerPlugin] = {}
        installed: set[str] = set()

        for plugin in core_visualizers():
            catalog.setdefault(plugin.manifest.id, plugin)
            installed.add(plugin.manifest.id)
        for plugin in bundled_visualizers():
            catalog.setdefault(plugin.manifest.id, plugin)
            if plugin.manifest.id in explicitly_installed or (
                plugin.manifest.default_installed and plugin.manifest.id not in uninstalled
            ):
                installed.add(plugin.manifest.id)
        for manifest, root in self.store.user_packages():
            if manifest.id in catalog:
                continue
            catalog[manifest.id] = VisualizerPlugin(
                manifest=manifest,
                origin="user",
                root=str(root),
            )
            installed.add(manifest.id)

        self._catalog = catalog
        self._installed = installed
        self._enabled = installed - disabled

    def catalog(self) -> list[VisualizerPlugin]:
        return sorted(self._catalog.values(), key=lambda item: item.manifest.priority)

    def installed(self, *, include_disabled: bool = False) -> list[VisualizerPlugin]:
        ids = self._installed if include_disabled else self._enabled
        return [plugin for plugin in self.catalog() if plugin.manifest.id in ids]

    def agentic(self) -> list[VisualizerPlugin]:
        return [plugin for plugin in self.installed() if plugin.manifest.agentic]

    def get(self, visualizer_id: str, *, require_enabled: bool = True) -> VisualizerPlugin | None:
        plugin = self._catalog.get(str(visualizer_id or "").strip().lower())
        if plugin is None:
            return None
        if plugin.manifest.id not in self._installed:
            return None
        if require_enabled and plugin.manifest.id not in self._enabled:
            return None
        return plugin

    def public_catalog(self) -> list[dict[str, object]]:
        return [
            manifest_public_dict(
                plugin,
                installed=plugin.manifest.id in self._installed,
                enabled=plugin.manifest.id in self._enabled,
            )
            for plugin in self.catalog()
        ]

    def set_enabled(self, visualizer_id: str, enabled: bool) -> None:
        plugin = self._catalog.get(visualizer_id)
        if plugin is None or plugin.manifest.id not in self._installed:
            raise VisualizerStoreError(f"visualizer is not installed: {visualizer_id}")
        self.store.set_enabled(visualizer_id, enabled)
        self.reload()

    def install_bundled(self, visualizer_id: str) -> None:
        plugin = self._catalog.get(visualizer_id)
        if plugin is None or plugin.origin != "bundled":
            raise VisualizerStoreError(f"bundled visualizer not found: {visualizer_id}")
        self.store.set_bundled_installed(visualizer_id, True)
        self.reload()

    def uninstall(self, visualizer_id: str) -> None:
        plugin = self._catalog.get(visualizer_id)
        if plugin is None:
            raise VisualizerStoreError(f"visualizer not found: {visualizer_id}")
        if plugin.manifest.core:
            raise VisualizerStoreError("core visualizers cannot be uninstalled; disable them")
        if plugin.origin == "bundled":
            self.store.set_bundled_installed(visualizer_id, False)
        elif plugin.origin == "user":
            self.store.uninstall_user(visualizer_id)
        self.reload()

    def install_archive(self, archive_path: Path) -> VisualizerPlugin:
        manifest = self.store.install_archive(
            archive_path,
            reserved_ids=set(self._catalog),
        )
        self.reload()
        plugin = self.get(manifest.id)
        if plugin is None:  # pragma: no cover - defensive
            raise VisualizerStoreError("installed visualizer was not discoverable")
        return plugin

    def asset_path(self, visualizer_id: str, relative_path: str) -> Path:
        plugin = self.get(visualizer_id)
        if plugin is None or plugin.origin != "user":
            raise VisualizerStoreError("visualizer asset not found")
        return self.store.asset_path(visualizer_id, relative_path)

    def prompt_catalog(self, requested: str = "auto") -> str:
        plugins = self.agentic()
        if requested != "auto":
            selected = self.get(requested)
            if selected is None or not selected.manifest.agentic:
                raise VisualizerStoreError(f"visualizer is unavailable: {requested}")
            plugins = [selected]
        blocks: list[str] = []
        for plugin in plugins:
            manifest = plugin.manifest
            schema = ""
            if manifest.payload_schema:
                schema = "\nPayload JSON Schema:\n" + json.dumps(
                    manifest.payload_schema, ensure_ascii=False, indent=2
                )
            blocks.append(
                f"### {manifest.id} — {manifest.display_name}\n"
                f"Use for: {manifest.description}\n"
                f"Payload format: {manifest.payload_format}{schema}\n"
                f"Rules:\n{manifest.prompt.strip()}"
            )
        return "\n\n".join(blocks)


def get_visualizer_registry() -> VisualizerRegistry:
    # Per-user paths are resolved by PathService/current-user context, so a
    # process singleton would leak one user's installed set into another's.
    return VisualizerRegistry()


__all__ = ["VisualizerRegistry", "get_visualizer_registry"]
