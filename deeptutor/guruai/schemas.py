from typing import Any, Literal

from pydantic import BaseModel, Field

Language = Literal["si", "en", "mixed"]


class Citation(BaseModel):
    book: str
    page: int
    chapter: str | None = None
    source_id: str | None = None


class Step(BaseModel):
    number: int
    title_si: str
    title_en: str
    explanation_si: str
    explanation_en: str
    latex: str | None = None
    canvas: dict[str, Any] | None = None
    citation: Citation | None = None


class GuruAnswer(BaseModel):
    language: Language
    summary_si: str
    summary_en: str
    steps: list[Step] = Field(default_factory=list)
    final_answer_si: str = ""
    final_answer_en: str = ""
    sources: list[Citation] = Field(default_factory=list)
    out_of_syllabus: bool = False
    confidence: float = 0.0


class MarkPoint(BaseModel):
    point: str
    marks: int
    earned: bool
    feedback_si: str
    feedback_en: str


class GradeResult(BaseModel):
    marks_awarded: int
    marks_total: int
    breakdown: list[MarkPoint] = Field(default_factory=list)
    what_went_well_si: str
    biggest_fix_si: str
    revise_topic: str
    revise_citation: Citation | None = None
    model_answer_steps: list[Step] = Field(default_factory=list)
