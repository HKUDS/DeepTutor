"""Shared data models for the math animator pipeline."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConceptAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    learning_goal: str = ""
    math_focus: list[str] = Field(default_factory=list)
    visual_targets: list[str] = Field(default_factory=list)
    narrative_steps: list[str] = Field(default_factory=list)
    reference_usage: str = ""
    output_intent: str = ""


class SceneDesign(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    scene_outline: list[str] = Field(default_factory=list)
    visual_style: str = ""
    animation_notes: list[str] = Field(default_factory=list)
    image_plan: list[str] = Field(default_factory=list)
    code_constraints: list[str] = Field(default_factory=list)


class GeneratedCode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = ""
    rationale: str = ""


class SummaryPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary_text: str = ""
    user_request: str = ""
    generated_output: str = ""
    key_points: list[str] = Field(default_factory=list)


class RenderedArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    url: str
    filename: str
    content_type: str = ""
    label: str = ""
    relative_path: str = ""


class RetryAttempt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attempt: int
    error: str


class VisualReviewResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    passed: bool = True
    summary: str = ""
    issues: list[str] = Field(default_factory=list)
    suggested_fix: str = ""
    reviewed_frames: int = 0


class RenderResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    output_mode: str
    artifacts: list[RenderedArtifact] = Field(default_factory=list)
    public_code_path: str = ""
    source_code_path: str = ""
    quality: str = ""
    retry_attempts: int = 0
    retry_history: list[RetryAttempt] = Field(default_factory=list)
    visual_review: VisualReviewResult | None = None
    workspace_items: list[dict] = Field(default_factory=list)


__all__ = [
    "ConceptAnalysis",
    "GeneratedCode",
    "RenderResult",
    "RenderedArtifact",
    "RetryAttempt",
    "SceneDesign",
    "SummaryPayload",
    "VisualReviewResult",
]
