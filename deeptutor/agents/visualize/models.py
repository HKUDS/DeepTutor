"""Data models for the visualize pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VisualizationAnalysis(BaseModel):
    """Output of the analysis stage."""

    render_type: Literal["svg", "chartjs", "mermaid"] = Field(
        description="Whether to render as raw SVG, a Chart.js configuration, or Mermaid diagram code.",
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
            "or Mermaid diagram type (flowchart, sequenceDiagram, mindmap, classDiagram, stateDiagram, etc.) "
            "when render_type is mermaid."
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
