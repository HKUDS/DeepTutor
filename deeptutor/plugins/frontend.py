"""Validated static frontend page contracts for managed plugins."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping

FRONTEND_PAGE_SCHEMA_VERSION = "deeptutor.plugin-frontend-page/v1"
MAX_PAGE_MANIFEST_BYTES = 64 * 1024
MAX_PAGE_ASSET_BYTES = 5 * 1024 * 1024
MAX_PAGE_ASSET_TOTAL_BYTES = 20 * 1024 * 1024
MAX_PAGE_ASSETS = 64
_ASSET_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")
_ASSET_SUFFIXES = frozenset(
    {
        ".css",
        ".html",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".png",
        ".svg",
        ".txt",
        ".webp",
        ".woff2",
    }
)


class FrontendPageError(ValueError):
    """Raised when a packaged frontend page is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class FrontendPageManifest:
    entry: str
    assets: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FRONTEND_PAGE_SCHEMA_VERSION,
            "entry": self.entry,
            "assets": list(self.assets),
        }


def parse_frontend_page_manifest(raw: Any) -> FrontendPageManifest:
    if not isinstance(raw, Mapping):
        raise FrontendPageError("frontend page manifest must be an object")
    _reject_unknown(raw, {"schema_version", "entry", "assets"})
    if raw.get("schema_version") != FRONTEND_PAGE_SCHEMA_VERSION:
        raise FrontendPageError("unsupported frontend page schema_version")
    entry = _asset_path("entry", raw.get("entry"))
    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, list) or not assets_raw:
        raise FrontendPageError("frontend page assets must be a non-empty array")
    if len(assets_raw) > MAX_PAGE_ASSETS:
        raise FrontendPageError(f"frontend page supports at most {MAX_PAGE_ASSETS} assets")
    assets = tuple(_asset_path("assets[]", item) for item in assets_raw)
    if len(set(assets)) != len(assets):
        raise FrontendPageError("frontend page assets must be unique")
    if entry not in assets:
        raise FrontendPageError("frontend page entry must be listed in assets")
    return FrontendPageManifest(entry=entry, assets=assets)


def load_frontend_page_manifest(path: Path) -> FrontendPageManifest:
    try:
        payload = path.read_bytes()
        if len(payload) > MAX_PAGE_MANIFEST_BYTES:
            raise FrontendPageError("frontend page manifest exceeds 64 KiB")
        return parse_frontend_page_manifest(json.loads(payload))
    except FrontendPageError:
        raise
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise FrontendPageError("frontend page manifest is unreadable") from exc


def resolve_frontend_page_asset(
    page: FrontendPageManifest,
    package_root: Path,
    requested: str,
) -> Path:
    if requested not in page.assets:
        raise FrontendPageError("frontend page asset is not declared")
    root = _package_root(package_root)
    total = 0
    try:
        for asset in page.assets:
            path = _resolve_asset(root, asset)
            size = path.stat().st_size
            if size > MAX_PAGE_ASSET_BYTES:
                raise FrontendPageError("frontend page asset exceeds 5 MiB")
            total += size
            if total > MAX_PAGE_ASSET_TOTAL_BYTES:
                raise FrontendPageError("frontend page assets exceed 20 MiB total")
            if asset == requested:
                return path
    except OSError as exc:
        raise FrontendPageError("frontend page asset is unreadable") from exc
    raise FrontendPageError("frontend page asset is unavailable")


def _package_root(value: Path) -> Path:
    try:
        root = value.resolve(strict=True)
        if not root.is_dir():
            raise FrontendPageError("plugin package root is unavailable")
        return root
    except OSError as exc:
        raise FrontendPageError("plugin package root is unavailable") from exc


def _resolve_asset(root: Path, asset: str) -> Path:
    relative = PurePosixPath(asset)
    lexical = root.joinpath(*relative.parts)
    current = lexical
    while current != root:
        if current.is_symlink():
            raise FrontendPageError("frontend page assets must not be symlinks")
        current = current.parent
    resolved = lexical.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise FrontendPageError("frontend page asset escapes the plugin package") from exc
    if not resolved.is_file():
        raise FrontendPageError("frontend page asset is not a file")
    return resolved


def _asset_path(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise FrontendPageError(f"{name} must be a POSIX asset path")
    path = PurePosixPath(value)
    if len(value) > 256 or path.is_absolute() or not path.parts:
        raise FrontendPageError(f"{name} must be a relative asset path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise FrontendPageError(f"{name} must not contain traversal segments")
    if any(_ASSET_SEGMENT.fullmatch(part) is None for part in path.parts):
        raise FrontendPageError(f"{name} contains an invalid path segment")
    if path.suffix.lower() not in _ASSET_SUFFIXES:
        raise FrontendPageError(f"{name} has an unsupported file type")
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise FrontendPageError(f"unknown fields: {', '.join(sorted(unknown))}")
