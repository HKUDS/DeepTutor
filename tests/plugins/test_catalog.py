"""Catalog snapshot parsing must fail per row, not per store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.plugins.catalog import (
    CATALOG_SCHEMA_VERSION,
    CatalogResolutionError,
    CatalogValidationError,
    load_catalog,
    parse_catalog_entry,
    resolve_catalog_entry,
)


def _entry(plugin_id: str = "org.author.example") -> dict:
    return {
        "id": plugin_id,
        "name": "Example Plugin",
        "version": "1.0.0",
        "description_i18n": {"en": "Example extension package"},
        "author": "Author Name",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://github.com/author/example",
        "compatibility": {"deeptutor": ">=1.6.0,<2", "api": {"tool": "1"}},
        "permissions": {"network": ["https://api.example.com"]},
        "dependencies": ["helper==2.0"],
        "artifact": {
            "kind": "python-package",
            "requirement": "example-plugin==1.0.0",
            "sha256": "0" * 64,
            "url": "https://artifacts.example.com/example-plugin-1.0.0.whl",
            "size_bytes": 128,
            "platform_tags": ["py3-none-any"],
        },
    }


def test_catalog_entry_requires_pinned_python_artifact() -> None:
    entry = parse_catalog_entry(_entry())

    assert entry.id == "org.author.example"
    assert entry.artifact.requirement == "example-plugin==1.0.0"
    assert entry.artifact.sha256 == "0" * 64
    assert entry.to_dict()["dependencies"] == ["helper==2.0"]


def test_catalog_entry_rejects_unpinned_requirement() -> None:
    raw = _entry()
    raw["artifact"]["requirement"] = "example-plugin>=1.0"

    with pytest.raises(CatalogValidationError, match="exactly one == pin"):
        parse_catalog_entry(raw)


def test_catalog_v1_remains_readable_without_download_metadata() -> None:
    raw = _entry()
    raw["artifact"].pop("url")
    raw["artifact"].pop("size_bytes")
    raw["artifact"].pop("platform_tags")

    entry = parse_catalog_entry(raw, schema_version="deeptutor.plugin-catalog/v1")

    assert entry.artifact.url == ""
    assert entry.to_dict()["artifact"] == {
        "kind": "python-package",
        "requirement": "example-plugin==1.0.0",
        "sha256": "0" * 64,
    }


def test_catalog_v2_requires_complete_download_pin() -> None:
    raw = _entry()
    raw["artifact"]["url"] = "http://artifacts.example.com/example.whl"

    with pytest.raises(CatalogValidationError, match="HTTPS URL"):
        parse_catalog_entry(raw)

    raw["artifact"]["url"] = "https://artifacts.example.com/example.zip"
    with pytest.raises(CatalogValidationError, match="wheel"):
        parse_catalog_entry(raw)


def test_catalog_v2_rejects_requirement_version_mismatch() -> None:
    raw = _entry()
    raw["artifact"]["requirement"] = "example-plugin==1.0.1"

    with pytest.raises(CatalogValidationError, match="entry version must match"):
        parse_catalog_entry(raw)


def test_malformed_catalog_row_does_not_hide_valid_rows(tmp_path) -> None:
    valid = _entry()
    invalid = _entry("org.author.broken")
    invalid["artifact"]["sha256"] = "not-a-hash"
    payload = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "meta": {
            "generated_at": "2026-08-31T00:00:00Z",
            "reviewed_at": "2026-08-31T00:00:00Z",
            "reviewers": ["maintainer"],
        },
        "entries": [invalid, valid],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    entries = load_catalog(path)

    assert [entry.id for entry in entries] == ["org.author.example"]


def test_resolver_selects_latest_stable_and_exact_catalog_versions(tmp_path) -> None:
    payload = _catalog(
        _entry(),
        _version_entry("1.1.0"),
        _version_entry("1.2.0b1"),
        _version_entry("1.0.0", status="deprecated"),
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    latest = resolve_catalog_entry("org.author.example", path=path)
    exact = resolve_catalog_entry("org.author.example", "1.0.0", path=path)
    prerelease = resolve_catalog_entry("org.author.example", "1.2.0b1", path=path)

    assert latest.version == "1.1.0"
    assert exact.version == "1.0.0"
    assert prerelease.version == "1.2.0b1"


def test_prerelease_is_install_explicit_but_browsable(tmp_path) -> None:
    path = _catalog_json(tmp_path, _version_entry("1.0.0b1"))

    with pytest.raises(CatalogResolutionError, match="stable"):
        resolve_catalog_entry("org.author.example", path=path)
    assert (
        resolve_catalog_entry("org.author.example", allow_prerelease=True, path=path).version
        == "1.0.0b1"
    )


def test_resolver_requires_opt_in_for_deprecated_and_never_sees_hidden(
    tmp_path,
) -> None:
    payload = _catalog(
        _version_entry("1.0.0", status="deprecated"),
        _version_entry("1.1.0", status="hidden"),
    )
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CatalogResolutionError, match="--allow-deprecated"):
        resolve_catalog_entry("org.author.example", "1.0.0", path=path)
    assert (
        resolve_catalog_entry(
            "org.author.example", "1.0.0", allow_deprecated=True, path=path
        ).version
        == "1.0.0"
    )
    with pytest.raises(CatalogResolutionError, match="not available"):
        resolve_catalog_entry("org.author.example", "1.1.0", path=path)


def _version_entry(version: str, *, status: str = "available") -> dict:
    raw = _entry()
    raw["version"] = version
    raw["status"] = status
    raw["artifact"]["requirement"] = f"example-plugin=={version}"
    raw["artifact"]["url"] = f"https://artifacts.example.com/example-{version}.whl"
    return raw


def _catalog(*entries: dict) -> dict:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "meta": {
            "generated_at": "2026-08-31T00:00:00Z",
            "reviewed_at": "2026-08-31T00:00:00Z",
            "reviewers": ["maintainer"],
        },
        "entries": list(entries),
    }


def _catalog_json(tmp_path, *entries: dict) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(_catalog(*entries)), encoding="utf-8")
    return path
