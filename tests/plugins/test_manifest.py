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
        "dependencies": ["requests>=2.32,<3"],
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
    assert manifest.dependencies == ("requests<3,>=2.32",)


def test_parse_manifest_normalizes_web_and_app_extension_contracts() -> None:
    raw = _manifest()
    raw["compatibility"]["api"] = {
        "app_connector": "1",
        "frontend_page": "1",
        "http_route": "1",
        "persistence_schema": "1",
    }
    raw["extensions"] = [
        {
            "type": "http_route",
            "id": "echo_route",
            "entry_point": "example.worker",
            "path": "/learning/echo",
            "methods": ["GET", "POST"],
            "auth": "authenticated",
        },
        {
            "type": "frontend_page",
            "id": "echo_page",
            "path": "/echo",
            "auth": "public",
            "manifest": "frontend/page.json",
        },
        {
            "type": "persistence_schema",
            "id": "echo_store",
            "schema": "schemas/echo.json",
            "operations": ["read", "write"],
        },
        {
            "type": "app_connector",
            "id": "echo_connector",
            "operations": ["import-course"],
        },
    ]

    manifest = parse_manifest(raw)

    assert [extension.to_dict() for extension in manifest.extensions] == [
        {
            "type": "http_route",
            "id": "echo_route",
            "entry_point": "example.worker",
            "path": "/learning/echo",
            "methods": ["GET", "POST"],
            "auth": "authenticated",
        },
        {
            "type": "frontend_page",
            "id": "echo_page",
            "path": "/echo",
            "auth": "public",
            "manifest": "frontend/page.json",
        },
        {
            "type": "persistence_schema",
            "id": "echo_store",
            "schema": "schemas/echo.json",
            "operations": ["read", "write"],
        },
        {
            "type": "app_connector",
            "id": "echo_connector",
            "operations": ["import-course"],
        },
    ]


def test_executable_frontend_page_requires_sandboxed_ui_permission() -> None:
    raw = _manifest()
    raw["compatibility"]["api"] = {"frontend_page": "1"}
    raw["permissions"]["ui"] = []
    raw["extensions"] = [
        {
            "type": "frontend_page",
            "id": "echo_page",
            "path": "/echo",
            "auth": "authenticated",
            "manifest": "frontend/page.json",
        }
    ]

    with pytest.raises(ManifestValidationError, match="sandboxed-iframe"):
        parse_manifest(raw)


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
        (
            {"dependencies": ["requests>=2.32,<3; sys_platform == 'darwin'"]},
            "name-and-version",
        ),
        ({"dependencies": ["requests", "REQUESTS>=2"]}, "duplicate"),
        (
            {
                "compatibility": {"deeptutor": ">=1.6.0,<2", "api": {}},
                "extensions": [
                    {
                        "type": "http_route",
                        "id": "echo",
                        "entry_point": "example.worker",
                        "path": "/../echo",
                        "methods": ["GET"],
                        "auth": "authenticated",
                    }
                ],
            },
            "static relative /path",
        ),
        (
            {
                "compatibility": {"deeptutor": ">=1.6.0,<2", "api": {}},
                "extensions": [
                    {
                        "type": "http_route",
                        "id": "echo",
                        "entry_point": "example.worker",
                        "path": "/echo",
                        "methods": ["TRACE"],
                        "auth": "authenticated",
                    }
                ],
            },
            "unsupported HTTP method",
        ),
        (
            {
                "compatibility": {"deeptutor": ">=1.6.0,<2", "api": {}},
                "extensions": [
                    {
                        "type": "frontend_page",
                        "id": "echo",
                        "path": "/echo",
                        "auth": "superuser",
                    }
                ],
            },
            "public, authenticated, or admin",
        ),
        (
            {
                "compatibility": {"deeptutor": ">=1.6.0,<2", "api": {}},
                "extensions": [
                    {
                        "type": "persistence_schema",
                        "id": "echo",
                        "schema": "../schemas/echo.json",
                        "operations": ["read"],
                    }
                ],
            },
            "traversal segments",
        ),
        (
            {
                "compatibility": {"deeptutor": ">=1.6.0,<2", "api": {}},
                "extensions": [
                    {
                        "type": "http_route",
                        "id": "echo",
                        "entry_point": "example.worker",
                        "path": "/echo",
                        "methods": ["GET"],
                        "auth": "authenticated",
                        "schema": "schemas/echo.json",
                    }
                ],
            },
            "unknown fields: schema",
        ),
    ],
)
def test_parse_manifest_rejects_invalid_contracts(mutation: dict, message: str) -> None:
    raw = _manifest()
    raw.update(mutation)

    with pytest.raises(ManifestValidationError, match=message):
        parse_manifest(raw)
