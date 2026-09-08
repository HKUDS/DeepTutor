"""Validation model for ``deeptutor.plugin.json``.

The root manifest is deliberately independent from runtime protocol classes.
Registry browsing must not import third-party Python modules, so this module
only accepts JSON-compatible dictionaries and normalizes them into small
dataclasses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

SCHEMA_VERSION = "deeptutor.plugin/v1"
MANIFEST_FILENAME = "deeptutor.plugin.json"

SUPPORTED_EXTENSION_TYPES = frozenset(
    {
        "app_connector",
        "capability",
        "frontend_page",
        "http_route",
        "loop_capability",
        "persistence_schema",
        "tool",
        "reading_extension",
        "visualizer",
    }
)
SUPPORTED_API_CONTRACTS = frozenset(SUPPORTED_EXTENSION_TYPES)
SUPPORTED_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
SUPPORTED_PLUGIN_AUTH_POLICIES = frozenset({"public", "authenticated", "admin"})
SUPPORTED_PERMISSION_SCOPES = frozenset(
    {
        "reading",
        "learning_events",
        "network",
        "models",
        "storage",
        "ui",
    }
)

_PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
_EXTENSION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_API_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
_HTTP_PATH = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9._~-]*(?:/[A-Za-z0-9][A-Za-z0-9._~-]*)*$")
_OPERATION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ManifestValidationError(ValueError):
    """Raised when a plugin manifest cannot be modeled."""


@dataclass(frozen=True, slots=True)
class PluginCompatibility:
    deeptutor: SpecifierSet
    api: Mapping[str, Version]

    def to_dict(self) -> dict[str, Any]:
        return {
            "deeptutor": str(self.deeptutor),
            "api": {name: str(version) for name, version in self.api.items()},
        }


@dataclass(frozen=True, slots=True)
class PluginPermissions:
    scopes: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {name: list(values) for name, values in self.scopes.items()}


@dataclass(frozen=True, slots=True)
class PluginExtension:
    type: str
    id: str
    entry_point: str = ""
    manifest: str = ""
    path: str = ""
    methods: tuple[str, ...] = ()
    auth: str = ""
    schema: str = ""
    operations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = {"type": self.type, "id": self.id}
        if self.entry_point:
            result["entry_point"] = self.entry_point
        if self.manifest:
            result["manifest"] = self.manifest
        if self.path:
            result["path"] = self.path
        if self.methods:
            result["methods"] = list(self.methods)
        if self.auth:
            result["auth"] = self.auth
        if self.schema:
            result["schema"] = self.schema
        if self.operations:
            result["operations"] = list(self.operations)
        return result


@dataclass(frozen=True, slots=True)
class PluginManifestData:
    schema_version: str
    id: str
    name: str
    version: Version
    description_i18n: Mapping[str, str]
    author: str
    license: str
    homepage: str
    source_url: str
    compatibility: PluginCompatibility
    permissions: PluginPermissions
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    extensions: tuple[PluginExtension, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["version"] = str(self.version)
        result["compatibility"] = self.compatibility.to_dict()
        result["permissions"] = self.permissions.to_dict()
        result["dependencies"] = list(self.dependencies)
        result["extensions"] = [extension.to_dict() for extension in self.extensions]
        return result


def parse_manifest(raw: Mapping[str, Any] | None) -> PluginManifestData:
    """Validate and normalize one root manifest.

    Unknown top-level fields are rejected rather than silently ignored. This is
    the compatibility contract third-party packages will build against, so a
    typo such as ``entryPoints`` must fail during review instead of changing
    behavior between DeepTutor releases.
    """
    if not isinstance(raw, Mapping):
        raise ManifestValidationError("manifest must be a JSON object")

    allowed = {
        "schema_version",
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
        "extensions",
    }
    _reject_unknown("manifest", raw, allowed)

    schema_version = _required_str("schema_version", raw.get("schema_version"))
    if schema_version != SCHEMA_VERSION:
        raise ManifestValidationError(f"unsupported schema_version {schema_version!r}")

    plugin_id = _required_str("id", raw.get("id"))
    if not _PLUGIN_ID.fullmatch(plugin_id):
        raise ManifestValidationError("id must be lowercase reverse-DNS-like identifier")

    name = _required_str("name", raw.get("name"), max_length=120)
    version = _version(_required_str("version", raw.get("version")))
    description = _i18n(raw.get("description_i18n"), required_language="en")
    author = _required_str("author", raw.get("author"), max_length=160)
    license_ = _required_str("license", raw.get("license"), max_length=80)
    homepage = _optional_url("homepage", raw.get("homepage"))
    source_url = _url("source_url", raw.get("source_url"))

    compatibility_raw = raw.get("compatibility")
    if not isinstance(compatibility_raw, Mapping):
        raise ManifestValidationError("compatibility must be an object")
    compatibility = _compatibility(compatibility_raw)

    permissions_raw = raw.get("permissions")
    if not isinstance(permissions_raw, Mapping):
        raise ManifestValidationError("permissions must be an object")
    permissions = _permissions(permissions_raw)

    dependencies_raw = raw.get("dependencies", [])
    if not isinstance(dependencies_raw, list):
        raise ManifestValidationError("dependencies must be an array")
    dependencies = _dependencies(dependencies_raw)

    extensions_raw = raw.get("extensions")
    if not isinstance(extensions_raw, list):
        raise ManifestValidationError("extensions must be an array")
    extensions = _extensions(extensions_raw)
    if any(extension.type == "frontend_page" and extension.manifest for extension in extensions):
        ui_scopes = permissions.scopes.get("ui", ())
        if "sandboxed-iframe" not in ui_scopes:
            raise ManifestValidationError(
                "executable frontend_page requires permissions.ui sandboxed-iframe"
            )

    return PluginManifestData(
        schema_version=schema_version,
        id=plugin_id,
        name=name,
        version=version,
        description_i18n=description,
        author=author,
        license=license_,
        homepage=homepage,
        source_url=source_url,
        compatibility=compatibility,
        permissions=permissions,
        dependencies=dependencies,
        extensions=extensions,
    )


def version_matches(version: Version, requirement: str | SpecifierSet) -> bool:
    try:
        specifier = (
            requirement if isinstance(requirement, SpecifierSet) else SpecifierSet(requirement)
        )
    except InvalidSpecifier as exc:
        raise ManifestValidationError(f"invalid version requirement {requirement!r}") from exc
    return specifier.contains(version, prereleases=True)


def is_sha256(value: str) -> bool:
    return bool(_SHA256.fullmatch(value))


def permission_digest(permissions: PluginPermissions) -> str:
    """Return a stable digest of the exact permission grant a user approved."""
    payload = json.dumps(
        permissions.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compatibility(raw: Mapping[str, Any]) -> PluginCompatibility:
    _reject_unknown("compatibility", raw, {"deeptutor", "api"})
    deeptutor_raw = raw.get("deeptutor")
    if not isinstance(deeptutor_raw, str) or not deeptutor_raw.strip():
        raise ManifestValidationError("compatibility.deeptutor is required")
    try:
        deeptutor = SpecifierSet(deeptutor_raw)
    except InvalidSpecifier as exc:
        raise ManifestValidationError("invalid compatibility.deeptutor specifier") from exc

    api_raw = raw.get("api")
    if not isinstance(api_raw, Mapping):
        raise ManifestValidationError("compatibility.api must be an object")
    _reject_unknown("compatibility.api", api_raw, SUPPORTED_API_CONTRACTS)
    api: dict[str, Version] = {}
    for name, value in api_raw.items():
        if name not in SUPPORTED_API_CONTRACTS:
            raise ManifestValidationError(f"unknown API contract {name!r}")
        if not isinstance(value, str) or not _API_VERSION.fullmatch(value):
            raise ManifestValidationError(f"compatibility.api.{name} must be a version")
        api[name] = Version(value)
    return PluginCompatibility(deeptutor=deeptutor, api=api)


def _permissions(raw: Mapping[str, Any]) -> PluginPermissions:
    _reject_unknown("permissions", raw, SUPPORTED_PERMISSION_SCOPES)
    scopes: dict[str, tuple[str, ...]] = {}
    for name, values in raw.items():
        if not isinstance(values, list):
            raise ManifestValidationError(f"permissions.{name} must be an array")
        normalized = tuple(
            _required_str(f"permissions.{name}[]", value, max_length=240) for value in values
        )
        if len(set(normalized)) != len(normalized):
            raise ManifestValidationError(f"permissions.{name} contains duplicate values")
        scopes[name] = normalized
    return PluginPermissions(scopes=scopes)


def _dependencies(raw: list[Any]) -> tuple[str, ...]:
    if len(raw) > 50:
        raise ManifestValidationError("dependencies supports at most 50 requirements")
    dependencies: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, str):
            raise ManifestValidationError(f"dependencies[{index}] must be a string")
        text = value.strip()
        if not text:
            raise ManifestValidationError(f"dependencies[{index}] is required")
        try:
            requirement = Requirement(text)
        except InvalidRequirement as exc:
            raise ManifestValidationError(
                f"dependencies[{index}] is not a valid PEP 508 requirement"
            ) from exc
        if requirement.url or requirement.marker or requirement.extras:
            raise ManifestValidationError(
                f"dependencies[{index}] must be a name-and-version requirement"
            )
        canonical_name = str(getattr(requirement, "canonical_name", requirement.name)).casefold()
        if canonical_name in seen:
            raise ManifestValidationError(f"dependencies contains duplicate {requirement.name}")
        seen.add(canonical_name)
        dependencies.append(str(requirement))
    return tuple(dependencies)


def _extensions(raw: list[Any]) -> tuple[PluginExtension, ...]:
    extensions: list[PluginExtension] = []
    seen: set[str] = set()
    seen_http_paths: set[str] = set()
    allowed_fields = {
        "capability": {"type", "id", "entry_point"},
        "loop_capability": {"type", "id", "entry_point"},
        "tool": {"type", "id", "entry_point"},
        "reading_extension": {"type", "id", "entry_point"},
        "visualizer": {"type", "id", "manifest"},
        "http_route": {"type", "id", "entry_point", "path", "methods", "auth"},
        "frontend_page": {"type", "id", "path", "auth", "manifest"},
        "persistence_schema": {"type", "id", "schema", "operations"},
        "app_connector": {"type", "id", "operations"},
    }
    for index, row in enumerate(raw):
        label = f"extensions[{index}]"
        if not isinstance(row, Mapping):
            raise ManifestValidationError(f"{label} must be an object")
        extension_type = _required_str(f"{label}.type", row.get("type"))
        if extension_type not in SUPPORTED_EXTENSION_TYPES:
            raise ManifestValidationError(f"{label}.type is not supported")
        _reject_unknown(label, row, allowed_fields[extension_type])
        extension_id = _required_str(f"{label}.id", row.get("id"))
        if not _EXTENSION_ID.fullmatch(extension_id):
            raise ManifestValidationError(f"{label}.id is invalid")
        if extension_id in seen:
            raise ManifestValidationError(f"duplicate extension id {extension_id!r}")
        seen.add(extension_id)

        entry_point = _optional_str(f"{label}.entry_point", row.get("entry_point"))
        manifest_path = _optional_str(f"{label}.manifest", row.get("manifest"))
        path = ""
        methods: tuple[str, ...] = ()
        auth = ""
        schema = ""
        operations: tuple[str, ...] = ()

        if extension_type == "visualizer":
            if not manifest_path:
                raise ManifestValidationError(f"{label}.manifest is required for visualizers")
        elif extension_type in {"capability", "loop_capability", "tool", "reading_extension"}:
            if not entry_point:
                raise ManifestValidationError(f"{label}.entry_point is required")
        elif extension_type == "http_route":
            if not entry_point:
                raise ManifestValidationError(f"{label}.entry_point is required")
            path = _http_path(f"{label}.path", row.get("path"))
            if path in seen_http_paths:
                raise ManifestValidationError(f"{label}.path is declared by multiple routes")
            seen_http_paths.add(path)
            methods = _methods(f"{label}.methods", row.get("methods"))
            auth = _auth_policy(f"{label}.auth", row.get("auth"))
        elif extension_type == "frontend_page":
            path = _http_path(f"{label}.path", row.get("path"))
            auth = _auth_policy(f"{label}.auth", row.get("auth"))
            if manifest_path:
                manifest_path = _package_path(f"{label}.manifest", manifest_path)
        elif extension_type == "persistence_schema":
            schema = _package_path(f"{label}.schema", row.get("schema"))
            operations = _operations(f"{label}.operations", row.get("operations"))
        elif extension_type == "app_connector":
            operations = _operations(f"{label}.operations", row.get("operations"))

        extensions.append(
            PluginExtension(
                type=extension_type,
                id=extension_id,
                entry_point=entry_point,
                manifest=manifest_path,
                path=path,
                methods=methods,
                auth=auth,
                schema=schema,
                operations=operations,
            )
        )
    return tuple(extensions)


def _http_path(name: str, value: Any) -> str:
    result = _required_str(name, value, max_length=512)
    if _HTTP_PATH.fullmatch(result) is None:
        raise ManifestValidationError(f"{name} must be a static relative /path")
    return result


def _methods(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ManifestValidationError(f"{name} must be a non-empty array")
    result = tuple(_required_str(f"{name}[]", item, max_length=16) for item in value)
    if len(set(result)) != len(result):
        raise ManifestValidationError(f"{name} contains duplicate values")
    if not set(result).issubset(SUPPORTED_HTTP_METHODS):
        raise ManifestValidationError(f"{name} contains an unsupported HTTP method")
    return result


def _auth_policy(name: str, value: Any) -> str:
    result = _required_str(name, value, max_length=32)
    if result not in SUPPORTED_PLUGIN_AUTH_POLICIES:
        raise ManifestValidationError(f"{name} must be public, authenticated, or admin")
    return result


def _package_path(name: str, value: Any) -> str:
    result = _required_str(name, value, max_length=512)
    if "\\" in result or "\x00" in result:
        raise ManifestValidationError(f"{name} must be a POSIX package path")
    path = PurePosixPath(result)
    if path.is_absolute() or not path.parts or path.suffix != ".json":
        raise ManifestValidationError(f"{name} must be a packaged JSON file path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestValidationError(f"{name} must not contain traversal segments")
    return result


def _operations(name: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ManifestValidationError(f"{name} must be a non-empty array")
    if len(value) > 32:
        raise ManifestValidationError(f"{name} supports at most 32 operations")
    result = tuple(_required_str(f"{name}[]", item, max_length=64) for item in value)
    if len(set(result)) != len(result):
        raise ManifestValidationError(f"{name} contains duplicate values")
    if any(_OPERATION_ID.fullmatch(item) is None for item in result):
        raise ManifestValidationError(f"{name} contains an invalid operation id")
    return result


def _i18n(raw: Any, *, required_language: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ManifestValidationError("description_i18n must be an object")
    result: dict[str, str] = {}
    for language, value in raw.items():
        if not isinstance(language, str) or not _LANGUAGE.fullmatch(language):
            raise ManifestValidationError(f"invalid language tag {language!r}")
        result[language] = _required_str(f"description_i18n.{language}", value, max_length=1000)
    if not result.get(required_language, "").strip():
        raise ManifestValidationError(f"description_i18n.{required_language} is required")
    return result


def _version(value: str) -> Version:
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise ManifestValidationError("version must be a valid semantic-style version") from exc


def _required_str(name: str, value: Any, *, max_length: int = 300) -> str:
    result = _optional_str(name, value)
    if not result:
        raise ManifestValidationError(f"{name} is required")
    if len(result) > max_length:
        raise ManifestValidationError(f"{name} exceeds {max_length} characters")
    return result


def _optional_str(name: str, value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ManifestValidationError(f"{name} must be a string")
    return value.strip()


def _url(name: str, value: Any) -> str:
    result = _required_str(name, value, max_length=2048)
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ManifestValidationError(f"{name} must be an absolute http(s) URL")
    return result


def _optional_url(name: str, value: Any) -> str:
    if value is None:
        return ""
    return _url(name, value)


def _reject_unknown(label: str, raw: Mapping[str, Any], allowed: Any) -> None:
    allowed_names = set(allowed)
    unknown = set(raw) - allowed_names
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise ManifestValidationError(f"{label} has unknown fields: {names}")


__all__ = [
    "MANIFEST_FILENAME",
    "SCHEMA_VERSION",
    "SUPPORTED_API_CONTRACTS",
    "SUPPORTED_EXTENSION_TYPES",
    "SUPPORTED_HTTP_METHODS",
    "SUPPORTED_PLUGIN_AUTH_POLICIES",
    "SUPPORTED_PERMISSION_SCOPES",
    "ManifestValidationError",
    "PluginCompatibility",
    "PluginExtension",
    "PluginManifestData",
    "PluginPermissions",
    "is_sha256",
    "parse_manifest",
    "permission_digest",
    "version_matches",
]
