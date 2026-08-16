"""Data models for the visualize pipeline."""

from __future__ import annotations

import logging
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

RenderType = Literal[
    "svg",
    "chartjs",
    "mermaid",
    "html",
    "manim_video",
    "manim_image",
]

VisualGenre = Literal[
    "",
    "flowchart",
    "structural",
    "illustrative",
    "chart",
    "stepper",
    "interactive",
    "mockup",
    "art",
]


class VisualizationAnalysis(BaseModel):
    """Output of the analysis stage."""

    render_type: RenderType = Field(
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
    visual_genre: VisualGenre = Field(
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

    @model_validator(mode="before")
    @classmethod
    def _drop_off_enum_values(cls, data: Any) -> Any:
        """Degrade an invented enum value instead of failing the whole render.

        Models regularly answer with a genre or render type that is not in the
        prompt's list ("simulation", "diagram"). Both fields are enums, so
        validation used to abort generation over a label that no downstream
        stage strictly needs — the genre only selects a code-generation style,
        and svg is the universal fallback render.
        """
        if not isinstance(data, dict):
            return data
        genre = data.get("visual_genre")
        if genre is not None and genre not in get_args(VisualGenre):
            logger.warning("Discarding unknown visual_genre %r", genre)
            data = {**data, "visual_genre": ""}
        render_type = data.get("render_type")
        if render_type is not None and render_type not in get_args(RenderType):
            logger.warning("Falling back to svg for unknown render_type %r", render_type)
            data = {**data, "render_type": "svg"}
        return data


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
