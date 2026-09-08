"""Catalog snapshot parsing must fail per row, not per store."""

from __future__ import annotations

import json

import pytest

from deeptutor.plugins.catalog import CatalogValidationError, load_catalog, parse_catalog_entry


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


def test_malformed_catalog_row_does_not_hide_valid_rows(tmp_path) -> None:
    valid = _entry()
    invalid = _entry("org.author.broken")
    invalid["artifact"]["sha256"] = "not-a-hash"
    payload = {
        "schema_version": "deeptutor.plugin-catalog/v1",
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
