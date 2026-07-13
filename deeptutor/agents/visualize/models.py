"""Data models for the visualize pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VisualizationAnalysis(BaseModel):
    """Output of the analysis stage."""

    render_type: Literal[
        "svg",
        "chartjs",
        "mermaid",
        "html",
        "manim_video",
        "manim_image",
    ] = Field(
        description=(
            "Render output: raw SVG, a Chart.js configuration, a Mermaid "
            "diagram, a self-contained interactive HTML page, or a Manim "
            "animation (video) / storyboard image."
        ),
    )
    description: str = Field(
        default="",
        description="High-level description of what the visualization should show.",
    )
    data_description: str = Field(
        default="",
        description="Description of the data or elements to be visualized.",
    )
    chart_type: str = Field(
        default="",
        description=(
            "Chart.js chart type (bar, line, pie, doughnut, radar, etc.) when render_type is chartjs, "
            "Mermaid diagram type (flowchart, sequenceDiagram, mindmap, classDiagram, stateDiagram, etc.) "
            "when render_type is mermaid, or a short interaction tag (e.g. 'interactive', 'animation', "
            "'walkthrough') when render_type is html."
        ),
    )
    visual_elements: list[str] = Field(
        default_factory=list,
        description="Key visual elements to include (shapes, labels, axes, colors, etc.).",
    )
    rationale: str = Field(
        default="",
        description="Why this render_type was chosen over the alternative.",
    )
    visual_genre: Literal[
        "",
        "flowchart",
        "structural",
        "illustrative",
        "chart",
        "stepper",
        "interactive",
        "mockup",
        "art",
    ] = Field(
        default="",
        description=(
            "Teaching-oriented sub-type that drives the code-generation style, "
            "routed on the user's intent (the verb), not the topic (the noun): "
            "'flowchart'/'structural' for reference maps, 'illustrative' for "
            "intuition/'how does X work' spatial metaphors, 'stepper' for "
            "cyclic or staged walkthroughs, 'chart' for quantitative data, "
            "'interactive'/'mockup'/'art' for the matching HTML/SVG experiences. "
            "Empty when no sub-type applies."
        ),
    )


class ReviewResult(BaseModel):
    """Output of the review / optimization stage."""

    optimized_code: str = Field(
        description="The final (potentially optimized) visualization code.",
    )
    changed: bool = Field(
        default=False,
        description="Whether the reviewer made modifications.",
    )
    review_notes: str = Field(
        default="",
        description="Notes on what was checked or changed.",
    )
