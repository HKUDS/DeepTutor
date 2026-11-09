"""Manifest and payload validation stay functional without an import-time jsonschema."""

from __future__ import annotations

import pytest

from deeptutor.visualizers.protocol import VisualizerManifest, VisualizerPlugin


def _manifest(**overrides):
    values = {
        "id": "test.schema",
        "display_name": "Schema Check",
        "description": "Exercises manifest and payload validation.",
        "render_target": "artifact",
        "payload_format": "json",
        "payload_kind": "json",
        "payload_schema": {
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
        "prompt": "Render the payload.",
    }
    values.update(overrides)
    return VisualizerManifest(**values)


def test_manifest_accepts_a_valid_payload_schema() -> None:
    manifest = _manifest()

    assert manifest.payload_schema["type"] == "object"


def test_manifest_rejects_an_invalid_payload_schema() -> None:
    with pytest.raises(ValueError) as excinfo:
        _manifest(payload_schema={"type": 123})

    assert "payload_schema is invalid" in str(excinfo.value)


def test_payload_validation_rejects_a_schema_violation() -> None:
    plugin = VisualizerPlugin(manifest=_manifest(), origin="user")

    ok, data, message = plugin.validate_payload('{"value": 42}')

    assert ok is False
    assert data is None
    assert message.startswith("payload schema violation at $")


def test_payload_validation_accepts_a_matching_payload() -> None:
    plugin = VisualizerPlugin(manifest=_manifest(), origin="user")

    ok, data, message = plugin.validate_payload('{"value": "ok"}')

    assert ok is True
    assert data == {"value": "ok"}
    assert message == ""
