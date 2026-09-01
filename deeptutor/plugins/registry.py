"""Read-only plugin discovery and local enablement state.

This registry manages marketplace-level state. It intentionally does not load
``BaseCapability`` or ``BaseTool`` implementations; legacy entry-point loading
remains in :mod:`deeptutor.plugins.loader`.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import Distribution, distributions
import json
import logging
from pathlib import Path
from typing import Any

from packaging.version import Version

from deeptutor.__version__ import __version__
from deeptutor.plugins.catalog import CATALOG_PATH, CatalogEntry, load_catalog
from deeptutor.plugins.manifest import (
    MANIFEST_FILENAME,
    ManifestValidationError,
    PluginManifestData,
    parse_manifest,
    version_matches,
)
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

STATE_SCHEMA_VERSION = 1
HOST_API_VERSIONS = {
    "capability": Version("1"),
    "loop_capability": Version("1"),
    "tool": Version("1"),
    "reading_extension": Version("1"),
    "visualizer": Version("1"),
}


class PluginStateError(ValueError):
    """Raised when a plugin state transition is not safe."""


@dataclass(frozen=True, slots=True)
class PluginRecord:
    id: str
    status: str
    manifest: PluginManifestData | None = None
    distribution: str = ""
    catalog_entry: CatalogEntry | None = None
    error: str = ""

    @property
    def name(self) -> str:
        if self.manifest is not None:
            return self.manifest.name
        if self.catalog_entry is not None:
            return self.catalog_entry.name
        return self.id

    @property
    def version(self) -> str:
        if self.manifest is not None:
            return str(self.manifest.version)
        if self.catalog_entry is not None:
            return self.catalog_entry.version
        return ""

    @property
    def description(self) -> str:
        source = (
            self.manifest.description_i18n if self.manifest else self.catalog_entry.description_i18n
        )
        return source.get("en", "") if source else ""

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "description": self.description,
        }
        if self.distribution:
            result["distribution"] = self.distribution
        if self.manifest is not None:
            result["manifest"] = self.manifest.to_dict()
        if self.catalog_entry is not None:
            result["catalog"] = self.catalog_entry.to_dict()
        if self.error:
            result["error"] = self.error
        return result


class PluginRegistry:
    """Discover installed manifests and catalog entries without importing them."""

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        catalog_path: Path | None = None,
        deeptutor_version: str = __version__,
        installed_distributions: Any | None = None,
    ) -> None:
        self.state_path = state_path or get_path_service().get_settings_file("plugins")
        self.catalog_path = catalog_path
        self.deeptutor_version = Version(deeptutor_version)
        self._installed_distributions = installed_distributions

    def list_plugins(self, *, include_catalog: bool = True) -> list[PluginRecord]:
        records_by_id = {record.id: record for record in self._installed_records()}
        if include_catalog:
            for entry in load_catalog(self.catalog_path or CATALOG_PATH):
                if entry.id not in records_by_id:
                    status = "deprecated" if entry.status == "deprecated" else "available"
                    records_by_id[entry.id] = PluginRecord(
                        id=entry.id,
                        status=status,
                        catalog_entry=entry,
                    )
        return [records_by_id[plugin_id] for plugin_id in sorted(records_by_id)]

    def get_plugin(self, plugin_id: str) -> PluginRecord | None:
        return next((record for record in self.list_plugins() if record.id == plugin_id), None)

    def is_enabled(self, plugin_id: str) -> bool:
        return plugin_id not in self._state().get("disabled", [])

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRecord:
        record = self.get_plugin(plugin_id)
        if record is None:
            raise PluginStateError(f"unknown plugin {plugin_id!r}")
        if record.status in {"broken", "incompatible"}:
            raise PluginStateError(f"plugin {plugin_id!r} is {record.status}")
        if record.status == "available":
            raise PluginStateError(f"plugin {plugin_id!r} is not installed")

        state = self._state()
        disabled = set(state.get("disabled", []))
        if enabled:
            disabled.discard(plugin_id)
        else:
            disabled.add(plugin_id)
        state["disabled"] = sorted(disabled)
        atomic_write_json(self.state_path, state)
        updated = self.get_plugin(plugin_id)
        assert updated is not None
        return updated

    def _installed_records(self) -> list[PluginRecord]:
        grouped: dict[str, list[PluginRecord]] = {}
        unkeyed: list[PluginRecord] = []
        for dist in self._distributions():
            for path, raw, read_error in _manifest_files(dist):
                manifest, parse_error = _parse_manifest(raw, read_error)
                plugin_id = manifest.id if manifest is not None else _raw_id(raw)
                distribution = _distribution_name(dist)
                if manifest is None or not plugin_id:
                    record = PluginRecord(
                        id=plugin_id or f"distribution:{distribution}",
                        status="broken",
                        distribution=distribution,
                        error=parse_error,
                    )
                    if plugin_id:
                        grouped.setdefault(plugin_id, []).append(record)
                    else:
                        unkeyed.append(record)
                    continue

                compatible, compatibility_error = self._compatible(manifest)
                status = "enabled" if compatible else "incompatible"
                record = PluginRecord(
                    id=plugin_id,
                    status=status,
                    manifest=manifest,
                    distribution=distribution,
                    error=compatibility_error,
                )
                grouped.setdefault(plugin_id, []).append(record)

        disabled = set(self._state().get("disabled", []))
        catalog_entries = {
            entry.id: entry for entry in load_catalog(self.catalog_path or CATALOG_PATH)
        }
        records: list[PluginRecord] = []
        for plugin_id, candidates in grouped.items():
            if len(candidates) > 1:
                records.append(
                    PluginRecord(
                        id=plugin_id,
                        status="broken",
                        distribution=", ".join(sorted(item.distribution for item in candidates)),
                        error="plugin id is provided by multiple installed distributions",
                    )
                )
                continue
            record = candidates[0]
            if record.status != "incompatible" and plugin_id in disabled:
                record = PluginRecord(
                    id=record.id,
                    status="disabled",
                    manifest=record.manifest,
                    distribution=record.distribution,
                    error=record.error,
                )
            elif plugin_id in catalog_entries and catalog_entries[plugin_id].status == "deprecated":
                record = PluginRecord(
                    id=record.id,
                    status="deprecated",
                    manifest=record.manifest,
                    distribution=record.distribution,
                    error=record.error,
                )
            records.append(record)
        return records + unkeyed

    def _compatible(self, manifest: PluginManifestData) -> tuple[bool, str]:
        if not version_matches(self.deeptutor_version, manifest.compatibility.deeptutor):
            return False, f"requires DeepTutor {manifest.compatibility.deeptutor}"
        for extension in manifest.extensions:
            required = manifest.compatibility.api.get(extension.type)
            supported = HOST_API_VERSIONS.get(extension.type)
            if required is None or supported is None or required > supported:
                return False, f"requires {extension.type} API newer than this build"
        return True, ""

    def _state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": STATE_SCHEMA_VERSION, "disabled": []}
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable plugin state at %s", self.state_path)
            return {"version": STATE_SCHEMA_VERSION, "disabled": []}

        if not isinstance(payload, dict) or payload.get("version") != STATE_SCHEMA_VERSION:
            logger.warning("Ignoring unsupported plugin state at %s", self.state_path)
            return {"version": STATE_SCHEMA_VERSION, "disabled": []}
        disabled = payload.get("disabled", [])
        if not isinstance(disabled, list) or not all(isinstance(item, str) for item in disabled):
            return {"version": STATE_SCHEMA_VERSION, "disabled": []}
        return {"version": STATE_SCHEMA_VERSION, "disabled": sorted(set(disabled))}

    def _distributions(self):
        if self._installed_distributions is not None:
            return list(self._installed_distributions)
        return distributions()


_default_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = PluginRegistry()
    return _default_registry


def reset_plugin_registry_cache() -> None:
    global _default_registry
    _default_registry = None


def _manifest_files(dist: Distribution) -> list[tuple[Path, Any, str]]:
    files = dist.files or []
    results: list[tuple[Path, Any, str]] = []
    for item in files:
        if item.name.lower() != MANIFEST_FILENAME:
            continue
        path = dist.locate_file(item)
        try:
            results.append((Path(path), json.loads(Path(path).read_text(encoding="utf-8")), ""))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            results.append((Path(path), None, str(exc)))
    return results


def _parse_manifest(raw: Any, read_error: str) -> tuple[PluginManifestData | None, str]:
    if read_error:
        return None, read_error
    try:
        return parse_manifest(raw), ""
    except ManifestValidationError as exc:
        return None, str(exc)


def _raw_id(raw: Any) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("id"), str):
        return raw["id"].strip()
    return ""


def _distribution_name(dist: Distribution) -> str:
    return dist.metadata.get("Name", "") or dist.metadata.get("name", "") or "unknown"


__all__ = [
    "HOST_API_VERSIONS",
    "PluginRecord",
    "PluginRegistry",
    "PluginStateError",
    "get_plugin_registry",
    "reset_plugin_registry_cache",
]
