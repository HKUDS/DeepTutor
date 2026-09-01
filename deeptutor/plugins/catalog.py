"""Read and search DeepTutor's vendored official plugin catalog.

The catalog is an index, not an installer and not a live registry client. It is
reviewed and pinned in the DeepTutor release, so browsing never depends on a
third-party service being online.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import Any, Mapping

from packaging.requirements import Requirement

from deeptutor.plugins.manifest import (
    ManifestValidationError,
    PluginCompatibility,
    PluginPermissions,
    is_sha256,
    parse_manifest,
)

logger = logging.getLogger(__name__)

CATALOG_SCHEMA_VERSION = "deeptutor.plugin-catalog/v1"
CATALOG_PATH = Path(__file__).with_name("catalog.json")
CATALOG_STATUSES = frozenset({"available", "deprecated", "hidden"})


class CatalogValidationError(ValueError):
    """Raised when a catalog row cannot be modeled."""


@dataclass(frozen=True, slots=True)
class CatalogArtifact:
    kind: str
    requirement: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    name: str
    version: str
    description_i18n: Mapping[str, str]
    author: str
    license: str
    homepage: str
    source_url: str
    compatibility: PluginCompatibility
    permissions: PluginPermissions
    artifact: CatalogArtifact
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description_i18n": dict(self.description_i18n),
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "source_url": self.source_url,
            "compatibility": self.compatibility.to_dict(),
            "permissions": self.permissions.to_dict(),
            "artifact": {
                "kind": self.artifact.kind,
                "requirement": self.artifact.requirement,
                "sha256": self.artifact.sha256,
            },
            "status": self.status,
        }


@lru_cache(maxsize=8)
def load_catalog(path: Path = CATALOG_PATH) -> tuple[CatalogEntry, ...]:
    """Return every valid non-hidden catalog row in deterministic ID order."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Plugin catalog is unreadable at %s", path)
        return ()

    try:
        _validate_root(payload)
    except CatalogValidationError as exc:
        logger.error("Ignoring plugin catalog at %s: %s", path, exc)
        return ()

    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for row in payload["entries"]:
        try:
            entry = parse_catalog_entry(row)
        except (CatalogValidationError, ManifestValidationError) as exc:
            row_id = row.get("id") if isinstance(row, Mapping) else "?"
            logger.warning("Skipping invalid plugin catalog entry %r: %s", row_id, exc)
            continue
        if entry.id in seen:
            logger.warning("Skipping duplicate plugin catalog entry %r", entry.id)
            continue
        seen.add(entry.id)
        if entry.status != "hidden":
            entries.append(entry)
    return tuple(sorted(entries, key=lambda entry: entry.id))


def reset_catalog_cache() -> None:
    load_catalog.cache_clear()


def search_catalog(query: str = "", *, path: Path = CATALOG_PATH) -> tuple[CatalogEntry, ...]:
    needle = query.strip().casefold()
    if not needle:
        return load_catalog(path)
    matches = []
    for entry in load_catalog(path):
        haystack = " ".join(
            (
                entry.id,
                entry.name,
                entry.version,
                entry.author,
                *entry.description_i18n.values(),
            )
        ).casefold()
        if needle in haystack:
            matches.append(entry)
    return tuple(matches)


def get_catalog_entry(entry_id: str, *, path: Path = CATALOG_PATH) -> CatalogEntry | None:
    return next((entry for entry in load_catalog(path) if entry.id == entry_id), None)


def parse_catalog_entry(raw: Any) -> CatalogEntry:
    if not isinstance(raw, Mapping):
        raise CatalogValidationError("catalog entry must be an object")

    # Reuse identity and typed declaration validation while allowing catalog-only
    # packaging fields on top of the package manifest shape.
    manifest_fields = {
        "id",
        "name",
        "version",
        "description_i18n",
        "author",
        "license",
        "homepage",
        "source_url",
        "compatibility",
        "permissions",
        "status",
        "artifact",
    }
    unknown = set(raw) - manifest_fields
    if unknown:
        raise CatalogValidationError(f"unknown fields: {', '.join(sorted(unknown))}")
    manifest_view = {key: value for key, value in raw.items() if key not in {"status", "artifact"}}
    manifest_view["schema_version"] = "deeptutor.plugin/v1"
    manifest_view["extensions"] = []
    manifest = parse_manifest(manifest_view)

    status = raw.get("status", "available")
    if status not in CATALOG_STATUSES:
        raise CatalogValidationError(f"invalid status {status!r}")
    artifact_raw = raw.get("artifact")
    if not isinstance(artifact_raw, Mapping):
        raise CatalogValidationError("artifact must be an object")
    _reject_unknown(artifact_raw, {"kind", "requirement", "sha256"})
    kind = artifact_raw.get("kind")
    requirement = artifact_raw.get("requirement")
    sha256 = artifact_raw.get("sha256")
    if kind != "python-package":
        raise CatalogValidationError("artifact.kind must be python-package")
    if not isinstance(requirement, str) or not requirement.strip():
        raise CatalogValidationError("artifact.requirement is required")
    parsed_requirement = Requirement(requirement)
    _require_pinned_requirement(parsed_requirement)
    if not isinstance(sha256, str) or not is_sha256(sha256):
        raise CatalogValidationError("artifact.sha256 must be a lowercase SHA-256")

    return CatalogEntry(
        id=manifest.id,
        name=manifest.name,
        version=str(manifest.version),
        description_i18n=manifest.description_i18n,
        author=manifest.author,
        license=manifest.license,
        homepage=manifest.homepage,
        source_url=manifest.source_url,
        compatibility=manifest.compatibility,
        permissions=manifest.permissions,
        artifact=CatalogArtifact(
            kind=str(kind),
            requirement=requirement.strip(),
            sha256=sha256,
        ),
        status=str(status),
    )


def _validate_root(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        raise CatalogValidationError("catalog must be an object")
    _reject_unknown(payload, {"schema_version", "meta", "entries"})
    if payload.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise CatalogValidationError("unsupported catalog schema_version")
    meta = payload.get("meta")
    if not isinstance(meta, Mapping):
        raise CatalogValidationError("catalog meta must be an object")
    _reject_unknown(meta, {"generated_at", "reviewed_at", "reviewers"})
    if not isinstance(meta.get("generated_at"), str) or not meta["generated_at"].strip():
        raise CatalogValidationError("catalog meta.generated_at is required")
    if not isinstance(meta.get("reviewed_at"), str) or not meta["reviewed_at"].strip():
        raise CatalogValidationError("catalog meta.reviewed_at is required")
    reviewers = meta.get("reviewers")
    if not isinstance(reviewers, list) or not reviewers:
        raise CatalogValidationError("catalog meta.reviewers must be a non-empty array")
    if not all(isinstance(reviewer, str) and reviewer.strip() for reviewer in reviewers):
        raise CatalogValidationError("catalog reviewers must be non-empty strings")
    if not isinstance(payload.get("entries"), list):
        raise CatalogValidationError("catalog entries must be an array")


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise CatalogValidationError(f"unknown fields: {', '.join(sorted(unknown))}")


def _require_pinned_requirement(requirement: Requirement) -> None:
    if requirement.url or requirement.marker or requirement.extras:
        raise CatalogValidationError("artifact.requirement must be a direct pinned package name")
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==":
        raise CatalogValidationError("artifact.requirement must use exactly one == pin")


__all__ = [
    "CATALOG_PATH",
    "CATALOG_SCHEMA_VERSION",
    "CatalogArtifact",
    "CatalogEntry",
    "CatalogValidationError",
    "get_catalog_entry",
    "load_catalog",
    "parse_catalog_entry",
    "reset_catalog_cache",
    "search_catalog",
]
