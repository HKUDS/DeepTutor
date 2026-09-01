"""Contract tests for the unified plugin root manifest."""

from __future__ import annotations

import pytest

from deeptutor.plugins.manifest import ManifestValidationError, parse_manifest


def _manifest() -> dict:
    return {
        "schema_version": "deeptutor.plugin/v1",
        "id": "org.author.example",
        "name": "Example Plugin",
        "version": "1.0.0",
        "description_i18n": {"en": "Example extension package", "zh": "示例扩展包"},
        "author": "Author Name",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://github.com/author/example",
        "compatibility": {
            "deeptutor": ">=1.6.0,<2",
            "api": {"reading_extension": "1", "visualizer": "1"},
        },
        "permissions": {
            "reading": ["selection", "visible_text"],
            "learning_events": [],
            "network": ["https://api.example.com"],
            "models": [],
            "storage": ["plugin-private"],
            "ui": ["sandboxed-iframe"],
        },
        "extensions": [
            {"type": "reading_extension", "id": "translation", "entry_point": "translation"},
            {
                "type": "visualizer",
                "id": "fraction_tiles",
                "manifest": "visualizers/fraction_tiles/visualizer.json",
            },
        ],
    }


def test_parse_manifest_normalizes_typed_extensions() -> None:
    manifest = parse_manifest(_manifest())

    assert manifest.id == "org.author.example"
    assert str(manifest.version) == "1.0.0"
    assert [extension.id for extension in manifest.extensions] == [
        "translation",
        "fraction_tiles",
    ]
    assert manifest.permissions.scopes["reading"] == ("selection", "visible_text")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"schema_version": "deeptutor.plugin/v2"}, "unsupported schema_version"),
        ({"entry_points": []}, "unknown fields: entry_points"),
        ({"compatibility": {"deeptutor": "not-a-specifier", "api": {}}}, "invalid"),
        (
            {"extensions": [{"type": "visualizer", "id": "broken"}]},
            "manifest is required for visualizers",
        ),
    ],
)
def test_parse_manifest_rejects_invalid_contracts(mutation: dict, message: str) -> None:
    raw = _manifest()
    raw.update(mutation)

    with pytest.raises(ManifestValidationError, match=message):
        parse_manifest(raw)
