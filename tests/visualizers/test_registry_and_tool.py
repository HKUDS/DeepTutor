from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.visualizers.protocol import VISUALIZATION_RESULT_KEY
from deeptutor.visualizers.registry import VisualizerRegistry
from deeptutor.visualizers.store import VisualizerStore, VisualizerStoreError
from deeptutor.visualizers.tool import SubmitVisualizationTool


def _registry(tmp_path: Path) -> VisualizerRegistry:
    return VisualizerRegistry(
        store=VisualizerStore(
            root=tmp_path / "visualizers",
            state_file=tmp_path / "settings" / "visualizers.json",
        )
    )


def _plugin_zip(path: Path, *, visualizer_id: str = "number_line") -> Path:
    manifest = {
        "id": visualizer_id,
        "version": "1.2.0",
        "display_name": "Number Line",
        "description": "Interactive number-line renderer.",
        "render_target": "iframe",
        "renderer_entry": "index.html",
        "payload_format": "application/json",
        "payload_kind": "json",
        "payload_schema": {
            "type": "object",
            "required": ["min", "max", "points"],
            "properties": {
                "min": {"type": "number"},
                "max": {"type": "number"},
                "points": {"type": "array", "items": {"type": "number"}},
            },
            "additionalProperties": False,
        },
        "prompt": "Return strict JSON containing min, max and points.",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("visualizer.json", json.dumps(manifest))
        archive.writestr(
            "index.html",
            "<script>addEventListener('message', event => document.body.textContent = JSON.stringify(event.data.payload))</script>",
        )
    return path


def test_registry_lifecycle_for_bundled_and_imported_types(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    assert registry.get("svg") is not None
    assert registry.get("geogebra") is None

    registry.install_bundled("geogebra")
    assert registry.get("geogebra") is not None
    registry.set_enabled("geogebra", False)
    assert registry.get("geogebra") is None
    assert registry.get("geogebra", require_enabled=False) is not None
    registry.uninstall("geogebra")
    assert registry.get("geogebra", require_enabled=False) is None

    plugin = registry.install_archive(_plugin_zip(tmp_path / "number-line.zip"))
    assert plugin.origin == "user"
    assert registry.asset_path("number_line", "index.html").is_file()
    ok, _, error = plugin.validate_payload('{"min":0,"max":10}')
    assert ok is False
    assert "schema violation" in error
    ok, data, error = plugin.validate_payload('{"min":0,"max":10,"points":[2,5,8]}')
    assert ok is True, error
    assert data["points"] == [2, 5, 8]
    assert "Payload JSON Schema" in registry.prompt_catalog("number_line")
    registry.uninstall("number_line")
    assert registry.get("number_line", require_enabled=False) is None


def test_import_rejects_reserved_id_and_path_traversal(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(VisualizerStoreError, match="reserved"):
        registry.install_archive(_plugin_zip(tmp_path / "reserved.zip", visualizer_id="svg"))

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../visualizer.json", "{}")
    with pytest.raises(VisualizerStoreError, match="illegal package path"):
        registry.install_archive(bad)


def test_core_visualizer_quality_gates(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    chart = registry.get("chartjs")
    assert chart is not None
    ok, _, error = chart.validate_payload('{"type":"line","data":{}}')
    assert ok is False
    assert "datasets" in error
    ok, data, error = chart.validate_payload(
        json.dumps(
            {
                "type": "line",
                "data": {
                    "labels": ["Week 1", "Week 2"],
                    "datasets": [{"label": "Recall", "data": [0.6, 0.8]}],
                },
                "options": {"responsive": True},
            }
        )
    )
    assert ok is True, error
    assert data["data"]["datasets"][0]["label"] == "Recall"

    html = registry.get("html")
    assert html is not None
    ok, _, error = html.validate_payload("<div>Not a complete lab</div>")
    assert ok is False
    assert "complete document" in error
    ok, _, error = html.validate_payload(
        '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
        '</head><body><label>Value <input></label><button id="reset">Reset</button>'
        "<script>document.querySelector('#reset').onclick=()=>{};</script></body></html>"
    )
    assert ok is True, error


@pytest.mark.asyncio
async def test_submit_tool_validates_and_commits_geogebra_envelope(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.install_bundled("geogebra")
    context = UnifiedContext(user_message="Construct a perpendicular bisector")
    tool = SubmitVisualizationTool()

    invalid = await tool.execute(
        _visualize_context=context,
        _visualizer_registry=registry,
        _requested_visualizer="geogebra",
        visualizer="geogebra",
        payload='{"app_name":"geometry","commands":["A=(0,0)"]}',
    )
    assert invalid.success is False
    assert "at least two" in invalid.content

    missing_view = await tool.execute(
        _visualize_context=context,
        _visualizer_registry=registry,
        _requested_visualizer="geogebra",
        visualizer="geogebra",
        payload=json.dumps({"app_name": "geometry", "commands": ["A=(0,0)", "B=(4,0)"]}),
    )
    assert missing_view.success is False
    assert "coordinate bounds is required" in missing_view.content

    accepted = await tool.execute(
        _visualize_context=context,
        _visualizer_registry=registry,
        _requested_visualizer="geogebra",
        visualizer="geogebra",
        payload=json.dumps(
            {
                "app_name": "geometry",
                "commands": [
                    "A=(0,0)",
                    "B=(4,0)",
                    "s=Segment(A,B)",
                    "SetLabelMode(s,1)",
                ],
                "view": {"x_min": -2, "x_max": 6, "y_min": -3, "y_max": 3},
            }
        ),
        title="Perpendicular bisector",
        description="Drag A or B to explore the construction.",
        alt_text="A segment with two draggable endpoints.",
    )
    assert accepted.success is True
    envelope = context.metadata[VISUALIZATION_RESULT_KEY]
    assert envelope["renderer"]["native_renderer"] == "geogebra"
    # The validator canonicalizes English command calls to GeoGebra's bracket
    # syntax before the frontend ever receives them.
    assert envelope["payload"]["data"]["commands"][-2:] == [
        "s=Segment[A,B]",
        "SetLabelMode[s,1]",
    ]
