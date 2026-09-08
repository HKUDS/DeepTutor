"""Read-only plugin discovery and local enablement state.

This registry manages marketplace-level state. It intentionally does not load
``BaseCapability`` or ``BaseTool`` implementations; legacy entry-point loading
remains in :mod:`deeptutor.plugins.loader`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import Distribution, distributions
import json
import logging
from pathlib import Path
from typing import Any

from packaging.version import Version

from deeptutor.__version__ import __version__
from deeptutor.plugins.catalog import (
    CATALOG_PATH,
    CatalogEntry,
    load_catalog,
    resolve_catalog_entry,
)
from deeptutor.plugins.manifest import (
    MANIFEST_FILENAME,
    ManifestValidationError,
    PluginManifestData,
    parse_manifest,
    permission_digest,
    version_matches,
)
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

STATE_SCHEMA_VERSION = 2
LEGACY_STATE_SCHEMA_VERSION = 1
HOST_API_VERSIONS = {
    "app_connector": Version("1"),
    "capability": Version("1"),
    "frontend_page": Version("1"),
    "http_route": Version("1"),
    "loop_capability": Version("1"),
    "persistence_schema": Version("1"),
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
    installation: "PluginInstallation | None" = None
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
        if self.installation is not None:
            result["installation"] = self.installation.to_dict()
        if self.error:
            result["error"] = self.error
        return result


@dataclass(frozen=True, slots=True)
class PluginInstallation:
    """A managed, dependency-isolated plugin installation."""

    version: str
    artifact_path: Path
    artifact_sha256: str
    venv_path: Path
    python_path: Path
    installed_at: str
    dependencies: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "artifact_path": str(self.artifact_path),
            "artifact_sha256": self.artifact_sha256,
            "venv_path": str(self.venv_path),
            "python_path": str(self.python_path),
            "installed_at": self.installed_at,
            "dependencies": list(self.dependencies),
        }


@dataclass(frozen=True, slots=True)
class PluginApproval:
    """The exact permission snapshot accepted by a user."""

    digest: str
    approved_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"digest": self.digest, "approved_at": self.approved_at}


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
            catalog_path = self.catalog_path or CATALOG_PATH
            catalog_ids = {entry.id for entry in load_catalog(catalog_path)}
            for plugin_id in sorted(catalog_ids):
                if plugin_id not in records_by_id:
                    entry = resolve_catalog_entry(
                        plugin_id,
                        allow_deprecated=True,
                        allow_prerelease=True,
                        path=catalog_path,
                    )
                    status = "deprecated" if entry.status == "deprecated" else "available"
                    records_by_id[plugin_id] = PluginRecord(
                        id=plugin_id,
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

    def approve(self, plugin_id: str) -> PluginRecord:
        """Persist approval for the installed manifest's exact permission grant."""
        record = self.get_plugin(plugin_id)
        if record is None:
            raise PluginStateError(f"unknown plugin {plugin_id!r}")
        if record.status == "enabled":
            return record
        if record.status != "approval-required" or record.manifest is None:
            raise PluginStateError(f"plugin {plugin_id!r} is {record.status}")

        state = self._state()
        row = _managed_row(state, plugin_id)
        if row is None:
            row = _external_row(state, plugin_id, record)
        row["approval"] = PluginApproval(
            digest=permission_digest(record.manifest.permissions),
            approved_at=_now(),
        ).to_dict()
        atomic_write_json(self.state_path, state)
        updated = self.get_plugin(plugin_id)
        assert updated is not None
        return updated

    def state_snapshot(self) -> dict[str, Any]:
        """Return the validated state document for lifecycle transactions."""
        return self._state()

    def replace_state(self, state: dict[str, Any]) -> None:
        """Atomically replace plugin state after a lifecycle transaction."""
        atomic_write_json(self.state_path, _validate_state(state))

    def _installed_records(self) -> list[PluginRecord]:
        grouped: dict[str, list[PluginRecord]] = {}
        unkeyed: list[PluginRecord] = []
        managed = self._managed_records()
        managed_ids = {record.id for record in managed}
        for dist in self._distributions():
            for path, raw, read_error in _manifest_files(dist):
                manifest, parse_error = _parse_manifest(raw, read_error)
                plugin_id = manifest.id if manifest is not None else _raw_id(raw)
                if plugin_id in managed_ids:
                    continue
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
                status = "incompatible" if not compatible else "approval-required"
                record = PluginRecord(
                    id=plugin_id,
                    status=status,
                    manifest=manifest,
                    distribution=distribution,
                    error=compatibility_error,
                )
                grouped.setdefault(plugin_id, []).append(record)

        state = self._state()
        disabled = set(state.get("disabled", []))
        catalog_path = self.catalog_path or CATALOG_PATH
        catalog_entries = {(entry.id, entry.version): entry for entry in load_catalog(catalog_path)}
        records: list[PluginRecord] = list(managed)
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
            if record.status == "approval-required" and record.manifest is not None:
                approval = _parse_approval(
                    (state.get("plugins") or {}).get(plugin_id, {}).get("approval")
                    if isinstance((state.get("plugins") or {}).get(plugin_id), dict)
                    else None
                )
                if approval is not None and approval.digest == permission_digest(
                    record.manifest.permissions
                ):
                    record = PluginRecord(
                        id=record.id,
                        status="enabled",
                        manifest=record.manifest,
                        distribution=record.distribution,
                        error=record.error,
                    )
                del approval
            if record.status != "incompatible" and plugin_id in disabled:
                record = PluginRecord(
                    id=record.id,
                    status="disabled",
                    manifest=record.manifest,
                    distribution=record.distribution,
                    error=record.error,
                )
            else:
                installed_version = str(record.manifest.version) if record.manifest else ""
                catalog_entry = catalog_entries.get((plugin_id, installed_version))
                if catalog_entry is not None and catalog_entry.status == "deprecated":
                    record = PluginRecord(
                        id=record.id,
                        status="deprecated",
                        manifest=record.manifest,
                        distribution=record.distribution,
                        error=record.error,
                    )
            records.append(record)
        return records + unkeyed

    def _managed_records(self) -> list[PluginRecord]:
        records: list[PluginRecord] = []
        state = self._state()
        catalog_entries = {
            (entry.id, entry.version): entry
            for entry in load_catalog(self.catalog_path or CATALOG_PATH)
        }
        for plugin_id, row in (state.get("plugins") or {}).items():
            manifest, parse_error = _parse_manifest(row.get("manifest"), "")
            if manifest is None:
                records.append(
                    PluginRecord(
                        id=str(plugin_id),
                        status="broken",
                        distribution="managed",
                        error=parse_error or "managed manifest is missing",
                    )
                )
                continue

            installation = _parse_installation(row.get("installation"))
            if row.get("installation") is None:
                compatible, compatibility_error = self._compatible(manifest)
                status = "incompatible" if not compatible else "approval-required"
                approval = _parse_approval(row.get("approval"))
                if (
                    status != "incompatible"
                    and approval is not None
                    and approval.digest == permission_digest(manifest.permissions)
                ):
                    status = "enabled"
                if status == "enabled" and plugin_id in state.get("disabled", []):
                    status = "disabled"
                records.append(
                    PluginRecord(
                        id=str(plugin_id),
                        status=status,
                        manifest=manifest,
                        distribution="external",
                        error=compatibility_error,
                    )
                )
                continue
            if installation is None:
                records.append(
                    PluginRecord(
                        id=str(plugin_id),
                        status="broken",
                        distribution="managed",
                        manifest=manifest,
                        error="managed installation record is invalid",
                    )
                )
                continue

            compatible, compatibility_error = self._compatible(manifest)
            status = "incompatible" if not compatible else "approval-required"
            if status != "incompatible":
                approval = _parse_approval(row.get("approval"))
                if approval is not None and approval.digest == permission_digest(
                    manifest.permissions
                ):
                    status = "enabled"
            if status == "enabled" and plugin_id in state.get("disabled", []):
                status = "disabled"
            catalog_entry = catalog_entries.get((str(plugin_id), str(manifest.version)))
            if (
                catalog_entry is not None
                and catalog_entry.status == "deprecated"
                and status not in {"incompatible", "disabled"}
            ):
                status = "deprecated"
            records.append(
                PluginRecord(
                    id=str(plugin_id),
                    status=status,
                    manifest=manifest,
                    distribution="managed",
                    installation=installation,
                    error=compatibility_error,
                )
            )
        return records

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
            return _empty_state()
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable plugin state at %s", self.state_path)
            return _empty_state()

        if not isinstance(payload, dict) or payload.get("version") not in {
            STATE_SCHEMA_VERSION,
            LEGACY_STATE_SCHEMA_VERSION,
        }:
            logger.warning("Ignoring unsupported plugin state at %s", self.state_path)
            return _empty_state()
        try:
            return _validate_state(payload)
        except (ValueError, ManifestValidationError):
            logger.warning("Ignoring malformed plugin state at %s", self.state_path)
            return _empty_state()

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


def _empty_state() -> dict[str, Any]:
    return {"version": STATE_SCHEMA_VERSION, "disabled": [], "plugins": {}}


def _validate_state(payload: dict[str, Any]) -> dict[str, Any]:
    disabled = payload.get("disabled", [])
    plugins = payload.get("plugins", {})
    if not isinstance(disabled, list) or not all(isinstance(item, str) for item in disabled):
        raise ValueError("disabled must be an array of plugin IDs")
    if not isinstance(plugins, dict):
        raise ValueError("plugins must be an object")

    normalized = _empty_state()
    normalized["disabled"] = sorted(set(disabled))
    for plugin_id, row in plugins.items():
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise ValueError("plugin state IDs must be non-empty strings")
        if not isinstance(row, dict):
            raise ValueError(f"plugin state for {plugin_id!r} must be an object")
        copied = dict(row)
        if copied.get("manifest") is not None:
            parse_manifest(copied["manifest"])
        if (
            copied.get("installation") is not None
            and _parse_installation(copied["installation"]) is None
        ):
            raise ValueError(f"plugin installation for {plugin_id!r} is invalid")
        if copied.get("approval") is not None and _parse_approval(copied["approval"]) is None:
            raise ValueError(f"plugin approval for {plugin_id!r} is invalid")
        history = copied.get("history", [])
        if not isinstance(history, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("version"), str)
            and isinstance(item.get("manifest"), dict)
            and isinstance(item.get("installation"), dict)
            for item in history
        ):
            raise ValueError(f"plugin history for {plugin_id!r} is invalid")
        copied["history"] = history
        normalized["plugins"][plugin_id] = copied
    return normalized


def _managed_row(state: dict[str, Any], plugin_id: str) -> dict[str, Any] | None:
    row = state.get("plugins", {}).get(plugin_id)
    return row if isinstance(row, dict) else None


def _external_row(
    state: dict[str, Any],
    plugin_id: str,
    record: PluginRecord,
) -> dict[str, Any]:
    if record.manifest is None:
        raise PluginStateError(f"plugin {plugin_id!r} has no valid manifest")
    row = {
        "manifest": record.manifest.to_dict(),
        "installation": record.installation.to_dict() if record.installation else None,
        "history": [],
    }
    state.setdefault("plugins", {})[plugin_id] = row
    return row


def _parse_installation(raw: Any) -> PluginInstallation | None:
    if not isinstance(raw, dict):
        return None
    required_strings = (
        "version",
        "artifact_path",
        "artifact_sha256",
        "venv_path",
        "python_path",
        "installed_at",
    )
    if not all(isinstance(raw.get(name), str) and raw[name] for name in required_strings):
        return None
    dependencies_raw = raw.get("dependencies", [])
    if not isinstance(dependencies_raw, list) or not all(
        isinstance(item, str) for item in dependencies_raw
    ):
        return None
    return PluginInstallation(
        version=raw["version"],
        artifact_path=Path(raw["artifact_path"]),
        artifact_sha256=raw["artifact_sha256"],
        venv_path=Path(raw["venv_path"]),
        python_path=Path(raw["python_path"]),
        installed_at=raw["installed_at"],
        dependencies=tuple(dependencies_raw),
    )


def _parse_approval(raw: Any) -> PluginApproval | None:
    if not isinstance(raw, dict):
        return None
    digest = raw.get("digest")
    approved_at = raw.get("approved_at")
    if not isinstance(digest, str) or not isinstance(approved_at, str):
        return None
    return PluginApproval(digest=digest, approved_at=approved_at)


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
    "PluginApproval",
    "PluginInstallation",
    "PluginRecord",
    "PluginRegistry",
    "PluginStateError",
    "get_plugin_registry",
    "reset_plugin_registry_cache",
]
