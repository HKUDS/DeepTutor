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
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import Version

from deeptutor.plugins.manifest import (
    ManifestValidationError,
    PluginCompatibility,
    PluginPermissions,
    is_sha256,
    parse_manifest,
)

logger = logging.getLogger(__name__)

CATALOG_SCHEMA_VERSION = "deeptutor.plugin-catalog/v2"
SUPPORTED_CATALOG_SCHEMA_VERSIONS = frozenset(
    {"deeptutor.plugin-catalog/v1", CATALOG_SCHEMA_VERSION}
)
CATALOG_PATH = Path(__file__).with_name("catalog.json")
CATALOG_STATUSES = frozenset({"available", "deprecated", "hidden"})
MAX_CATALOG_ARTIFACT_BYTES = 256 * 1024 * 1024
PLATFORM_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CatalogValidationError(ValueError):
    """Raised when a catalog row cannot be modeled."""


class CatalogResolutionError(ValueError):
    """Raised when a reviewed catalog version cannot be selected."""


@dataclass(frozen=True, slots=True)
class CatalogArtifact:
    kind: str
    requirement: str
    sha256: str
    url: str = ""
    size_bytes: int = 0
    platform_tags: tuple[str, ...] = ()


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
    dependencies: tuple[str, ...]
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
            "dependencies": list(self.dependencies),
            "artifact": {
                "kind": self.artifact.kind,
                "requirement": self.artifact.requirement,
                "sha256": self.artifact.sha256,
                **(
                    {
                        "url": self.artifact.url,
                        "size_bytes": self.artifact.size_bytes,
                        "platform_tags": list(self.artifact.platform_tags),
                    }
                    if self.artifact.url
                    else {}
                ),
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
        schema_version = _validate_root(payload)
    except CatalogValidationError as exc:
        logger.error("Ignoring plugin catalog at %s: %s", path, exc)
        return ()

    entries: list[CatalogEntry] = []
    seen: set[str | tuple[str, str]] = set()
    for row in payload["entries"]:
        try:
            entry = parse_catalog_entry(row, schema_version=schema_version)
        except (CatalogValidationError, ManifestValidationError) as exc:
            row_id = row.get("id") if isinstance(row, Mapping) else "?"
            logger.warning("Skipping invalid plugin catalog entry %r: %s", row_id, exc)
            continue
        identity = entry.id if schema_version.endswith("/v1") else (entry.id, entry.version)
        if identity in seen:
            logger.warning("Skipping duplicate plugin catalog entry %r", identity)
            continue
        seen.add(identity)
        if entry.status != "hidden":
            entries.append(entry)
    return tuple(sorted(entries, key=lambda entry: (entry.id, Version(entry.version))))


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
    try:
        return resolve_catalog_entry(
            entry_id,
            allow_deprecated=True,
            allow_prerelease=True,
            path=path,
        )
    except CatalogResolutionError:
        return None


def resolve_catalog_entry(
    plugin_id: str,
    version: str = "latest",
    *,
    allow_deprecated: bool = False,
    allow_prerelease: bool = False,
    path: Path = CATALOG_PATH,
) -> CatalogEntry:
    """Resolve one browsable catalog row without consulting remote state."""
    candidates = [entry for entry in load_catalog(path) if entry.id == plugin_id]
    if not candidates:
        raise CatalogResolutionError(f"plugin {plugin_id!r} is not in the reviewed catalog")

    if version != "latest":
        matches = [entry for entry in candidates if entry.version == version]
        if len(matches) != 1:
            raise CatalogResolutionError(
                f"plugin {plugin_id!r} version {version!r} is not available"
            )
        entry = matches[0]
        if entry.status == "deprecated" and not allow_deprecated:
            raise CatalogResolutionError(
                f"plugin {plugin_id!r} version {version!r} is deprecated; use --allow-deprecated"
            )
        return entry

    eligible = [
        entry
        for entry in candidates
        if entry.status == "available" or (allow_deprecated and entry.status == "deprecated")
    ]
    stable = [
        entry for entry in eligible if allow_prerelease or not Version(entry.version).is_prerelease
    ]
    if not stable:
        raise CatalogResolutionError(
            f"plugin {plugin_id!r} has no available stable catalog version"
        )
    return max(stable, key=lambda entry: Version(entry.version))


def parse_catalog_entry(raw: Any, *, schema_version: str = CATALOG_SCHEMA_VERSION) -> CatalogEntry:
    if not isinstance(raw, Mapping):
        raise CatalogValidationError("catalog entry must be an object")
    if schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
        raise CatalogValidationError("unsupported catalog schema_version")

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
        "dependencies",
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
    artifact_fields = {"kind", "requirement", "sha256"}
    if schema_version == CATALOG_SCHEMA_VERSION:
        artifact_fields.update({"url", "size_bytes", "platform_tags"})
    _reject_unknown(artifact_raw, artifact_fields)
    kind = artifact_raw.get("kind")
    requirement = artifact_raw.get("requirement")
    sha256 = artifact_raw.get("sha256")
    if kind != "python-package":
        raise CatalogValidationError("artifact.kind must be python-package")
    if not isinstance(requirement, str) or not requirement.strip():
        raise CatalogValidationError("artifact.requirement is required")
    try:
        parsed_requirement = Requirement(requirement)
    except InvalidRequirement as exc:
        raise CatalogValidationError("artifact.requirement is invalid") from exc
    _require_pinned_requirement(parsed_requirement, manifest.version)
    if not isinstance(sha256, str) or not is_sha256(sha256):
        raise CatalogValidationError("artifact.sha256 must be a lowercase SHA-256")
    url = artifact_raw.get("url", "")
    size_bytes = artifact_raw.get("size_bytes", 0)
    platform_tags_raw = artifact_raw.get("platform_tags", [])
    if schema_version == CATALOG_SCHEMA_VERSION:
        _validate_download_artifact(url, size_bytes, platform_tags_raw)
        url = str(url)
        size_bytes = int(size_bytes)
        platform_tags = tuple(platform_tags_raw)
    else:
        platform_tags = ()

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
        dependencies=manifest.dependencies,
        artifact=CatalogArtifact(
            kind=str(kind),
            requirement=requirement.strip(),
            sha256=sha256,
            url=url,
            size_bytes=size_bytes,
            platform_tags=platform_tags,
        ),
        status=str(status),
    )


def _validate_root(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        raise CatalogValidationError("catalog must be an object")
    _reject_unknown(payload, {"schema_version", "meta", "entries"})
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str):
        raise CatalogValidationError("catalog schema_version must be a string")
    if schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
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
    return str(schema_version)


def _validate_download_artifact(url: Any, size_bytes: Any, platform_tags: Any) -> None:
    if not isinstance(url, str) or not url.strip():
        raise CatalogValidationError("artifact.url is required")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CatalogValidationError("artifact.url must be an HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CatalogValidationError("artifact.url must be a direct immutable path")
    if not parsed.path.lower().endswith(".whl"):
        raise CatalogValidationError("artifact.url must point to a wheel")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or not (0 < size_bytes <= MAX_CATALOG_ARTIFACT_BYTES)
    ):
        raise CatalogValidationError("artifact.size_bytes is outside the supported range")
    if not isinstance(platform_tags, list) or not platform_tags:
        raise CatalogValidationError("artifact.platform_tags must be a non-empty array")
    if any(not isinstance(tag, str) or not PLATFORM_TAG.fullmatch(tag) for tag in platform_tags):
        raise CatalogValidationError("artifact.platform_tags contain an invalid tag")
    if len(set(platform_tags)) != len(platform_tags):
        raise CatalogValidationError("artifact.platform_tags must be unique")


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise CatalogValidationError(f"unknown fields: {', '.join(sorted(unknown))}")


def _require_pinned_requirement(requirement: Requirement, expected_version: Version) -> None:
    if requirement.url or requirement.marker or requirement.extras:
        raise CatalogValidationError("artifact.requirement must be a direct pinned package name")
    specifiers = list(requirement.specifier)
    if len(specifiers) != 1 or specifiers[0].operator != "==":
        raise CatalogValidationError("artifact.requirement must use exactly one == pin")
    if Version(str(specifiers[0].version)) != expected_version:
        raise CatalogValidationError("artifact.requirement and entry version must match")


__all__ = [
    "CATALOG_PATH",
    "CATALOG_SCHEMA_VERSION",
    "CatalogArtifact",
    "CatalogEntry",
    "CatalogValidationError",
    "CatalogResolutionError",
    "get_catalog_entry",
    "load_catalog",
    "parse_catalog_entry",
    "reset_catalog_cache",
    "search_catalog",
]
