"""Built-in and bundled visualizer type declarations."""

from __future__ import annotations

import json
from typing import Any

from deeptutor.tools.vision.ggb_validator import validate_ggbscript

from .protocol import VisualizerManifest, VisualizerPlugin

_GENERAL = """
Generate the visualization itself, not an essay about it. Keep labels concise,
use a coherent visual hierarchy, and include only elements that help the stated
learning goal. The payload must be complete and directly renderable. Do not put
Markdown fences around the payload passed to submit_visualization.
""".strip()


def _text_validator(render_type: str):
    def validate(raw: str) -> tuple[bool, Any, str]:
        from deeptutor.agents.visualize.utils import validate_visualization

        ok, error = validate_visualization(raw, render_type)
        if not ok:
            return False, None, error
        if render_type == "svg":
            lowered = raw.lower()
            if "<title" not in lowered or "<desc" not in lowered:
                return (
                    False,
                    None,
                    "SVG must include direct <title> and <desc> accessibility elements",
                )
        if render_type == "html":
            lowered = raw.lower()
            required = ("<!doctype", "<html", "<body", "<script")
            missing = [token for token in required if token not in lowered]
            if missing:
                return (
                    False,
                    None,
                    "Interactive HTML must be a complete document with doctype, html, "
                    f"body and script; missing: {', '.join(missing)}",
                )
            if 'name="viewport"' not in lowered and "name='viewport'" not in lowered:
                return False, None, "Interactive HTML must include a viewport meta tag"
            has_control = any(token in lowered for token in ("<button", "<input", "<select"))
            if not has_control:
                return False, None, "Interactive HTML must include a learner control"
            if "reset" not in lowered:
                return False, None, "Interactive HTML must include a reset control"
            if "aria-label" not in lowered and "<label" not in lowered:
                return False, None, "Interactive controls need labels or aria-labels"
        return True, raw, ""

    return validate


def _json_visualization_validator(render_type: str):
    def validate(raw: str) -> tuple[bool, Any, str]:
        from deeptutor.agents.visualize.utils import validate_visualization

        ok, error = validate_visualization(raw, render_type)
        if not ok:
            return False, None, error
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:  # defensive; validator is strict JSON
            return False, None, str(exc)
        if render_type == "chartjs":
            supported = {
                "bar",
                "bubble",
                "doughnut",
                "line",
                "pie",
                "polarArea",
                "radar",
                "scatter",
            }
            chart_type = data.get("type") if isinstance(data, dict) else None
            if chart_type not in supported:
                return False, None, f"unsupported Chart.js type: {chart_type}"
            chart_data = data.get("data")
            if not isinstance(chart_data, dict):
                return False, None, "Chart.js data must be an object"
            datasets = chart_data.get("datasets")
            if not isinstance(datasets, list) or not datasets:
                return False, None, "Chart.js data.datasets must be a non-empty array"
            for index, dataset in enumerate(datasets):
                if not isinstance(dataset, dict):
                    return False, None, f"Chart.js dataset {index} must be an object"
                if not str(dataset.get("label") or "").strip():
                    return False, None, f"Chart.js dataset {index} needs a label"
                if not isinstance(dataset.get("data"), list) or not dataset["data"]:
                    return False, None, f"Chart.js dataset {index} needs non-empty data"
            if "options" in data and not isinstance(data["options"], dict):
                return False, None, "Chart.js options must be an object"
        return True, data, ""

    return validate


def _geogebra_validator(raw: str) -> tuple[bool, Any, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, None, f"GeoGebra payload must be strict JSON: {exc}"
    if not isinstance(data, dict):
        return False, None, "GeoGebra payload must be a JSON object"
    commands = data.get("commands")
    if not isinstance(commands, list):
        return False, None, "GeoGebra payload.commands must be an array"
    clean_commands = [str(item).strip() for item in commands if str(item).strip()]
    if len(clean_commands) < 2:
        return False, None, "GeoGebra construction needs at least two commands"
    if len(clean_commands) > 100:
        return False, None, "GeoGebra construction exceeds the 100-command limit"
    fixed, warnings, errors = validate_ggbscript("\n".join(clean_commands))
    fixed_commands = [line.strip() for line in fixed.splitlines() if line.strip()]
    if errors or len(fixed_commands) < 2:
        return False, None, "; ".join(errors) or "no usable GeoGebra commands"
    app_name = str(data.get("app_name") or "geometry").strip().lower()
    if app_name not in {"geometry", "graphing", "3d", "classic"}:
        return False, None, f"unsupported GeoGebra app_name: {app_name}"
    view = data.get("view") if isinstance(data.get("view"), dict) else {}
    if not view:
        return False, None, "GeoGebra payload.view with coordinate bounds is required"
    normalized_view: dict[str, float] = {}
    for key in ("x_min", "x_max", "y_min", "y_max"):
        value = view.get(key)
        if value is None:
            continue
        try:
            normalized_view[key] = float(value)
        except (TypeError, ValueError):
            return False, None, f"GeoGebra view.{key} must be numeric"
    required_bounds = {"x_min", "x_max", "y_min", "y_max"}
    if set(normalized_view) != required_bounds:
        return False, None, "GeoGebra view must contain all four coordinate bounds"
    if normalized_view["x_min"] >= normalized_view["x_max"]:
        return False, None, "GeoGebra x_min must be smaller than x_max"
    if normalized_view["y_min"] >= normalized_view["y_max"]:
        return False, None, "GeoGebra y_min must be smaller than y_max"
    result: dict[str, Any] = {
        "app_name": app_name,
        "commands": fixed_commands,
    }
    result["view"] = normalized_view
    if warnings:
        result["validation_warnings"] = warnings
    return True, result, ""


def core_visualizers() -> tuple[VisualizerPlugin, ...]:
    return (
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="svg",
                display_name="SVG",
                description="Precise explanatory illustrations and custom diagrams.",
                subjects=["general"],
                intents=["explain", "illustrate", "compare"],
                native_renderer="svg",
                payload_format="image/svg+xml",
                language_tag="svg",
                core=True,
                priority=10,
                prompt=_GENERAL
                + """

Return one well-formed raw <svg> element with xmlns and camel-case viewBox.
Use a transparent background and the host classes t/th/ts, box, arr, leader,
and c-gray/c-blue/c-teal/c-coral/c-purple/c-green/c-amber/c-red. Do not hardcode
text colors. Include <title> and <desc>. Calculate positions before drawing;
no labels, boxes or arrows may overlap or leave the viewBox.
""",
            ),
            origin="core",
            validator=_text_validator("svg"),
        ),
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="mermaid",
                display_name="Mermaid",
                description="Structured flows, sequences, states, classes, ERDs and timelines.",
                subjects=["general", "computer_science"],
                intents=["structure", "flow", "sequence"],
                native_renderer="mermaid",
                payload_format="text/vnd.mermaid",
                language_tag="mermaid",
                core=True,
                priority=20,
                prompt=_GENERAL
                + """

Return valid Mermaid DSL only. Pick the semantically correct diagram keyword.
Use stable ASCII node IDs, short labels, and avoid reserved words as IDs. Prefer
top-to-bottom layout for explanations and left-to-right for short processes.
""",
            ),
            origin="core",
            validator=_text_validator("mermaid"),
        ),
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="chartjs",
                display_name="Chart.js",
                description="Standard quantitative charts rendered from strict JSON.",
                subjects=["statistics", "general"],
                intents=["compare", "trend", "distribution"],
                native_renderer="chartjs",
                payload_format="application/vnd.chartjs+json",
                payload_kind="json",
                language_tag="json",
                core=True,
                priority=30,
                prompt=_GENERAL
                + """

Return one strict JSON Chart.js configuration with type, data and options.
Never include functions, comments, undefined, single-quoted strings or trailing
commas. Choose a chart type that matches the comparison and label every series.
""",
            ),
            origin="core",
            validator=_json_visualization_validator("chartjs"),
        ),
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="html",
                display_name="Interactive HTML",
                description="Self-contained interactive lessons, steppers and simulations.",
                subjects=["general"],
                intents=["interact", "simulate", "practice"],
                native_renderer="html",
                payload_format="text/html",
                language_tag="html",
                core=True,
                priority=40,
                prompt=_GENERAL
                + """

Return a complete single-file HTML document. Put CSS and JavaScript inline.
It runs in a null-origin sandbox. Use responsive sizing and semantic controls;
do not navigate the parent. You may call sendPrompt(text) for a meaningful
learner follow-up. Include an explanatory state, reset control and accessible
labels for interactive elements.
""",
            ),
            origin="core",
            validator=_text_validator("html"),
        ),
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="manim_video",
                display_name="Manim animation",
                description="Server-rendered mathematical animation.",
                subjects=["mathematics"],
                intents=["animate", "derive"],
                render_target="artifact",
                native_renderer="math_animator",
                payload_format="video/mp4",
                language_tag="python",
                agentic=False,
                core=True,
                priority=200,
                prompt="Rendered by the dedicated Manim artifact pipeline.",
            ),
            origin="core",
        ),
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="manim_image",
                display_name="Manim storyboard",
                description="Server-rendered mathematical storyboard image.",
                subjects=["mathematics"],
                intents=["storyboard", "derive"],
                render_target="artifact",
                native_renderer="math_animator",
                payload_format="image/png",
                language_tag="python",
                agentic=False,
                core=True,
                priority=210,
                prompt="Rendered by the dedicated Manim artifact pipeline.",
            ),
            origin="core",
        ),
    )


def bundled_visualizers() -> tuple[VisualizerPlugin, ...]:
    return (
        VisualizerPlugin(
            manifest=VisualizerManifest(
                id="geogebra",
                display_name="GeoGebra",
                description=(
                    "Interactive geometry, functions, calculus, vectors and coordinate models."
                ),
                subjects=["mathematics", "physics"],
                intents=["construct", "explore", "prove", "graph"],
                native_renderer="geogebra",
                payload_format="application/vnd.geogebra.commands+json",
                payload_kind="json",
                language_tag="json",
                core=False,
                default_installed=False,
                priority=5,
                prompt=_GENERAL
                + """

Return strict JSON with this shape:
{"app_name":"geometry","commands":["A=(0,0)","..."],
 "view":{"x_min":-6,"x_max":6,"y_min":-4,"y_max":4}}

Use app_name geometry for constructions, graphing for functions, and 3d only
when three-dimensional manipulation is essential. Each command is one English
GeoGebra command with explicit labels. Build dependent objects from independent
draggable points so the construction remains mathematically meaningful when
manipulated. Include the requested givens, constraints, key derived objects,
measurements and concise captions. SetColor uses integer RGB components such as
SetColor[A,31,119,180], never CSS or hex colors. Use SetLineThickness,
SetPointSize, SetLabelVisible and SetLabelMode sparingly to make the teaching
focus obvious. Choose view bounds
that contain the whole construction with margin. Never fake a diagram with
unrelated fixed coordinates when a dependent construction is possible.
""",
            ),
            origin="bundled",
            validator=_geogebra_validator,
        ),
    )


__all__ = ["bundled_visualizers", "core_visualizers"]
