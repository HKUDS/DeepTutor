"""Deterministic, conservation-safe exam-paper reordering and export."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html import escape
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from deeptutor.agents.question.artifact_guard import (
    ArtifactConservationError,
    validate_conservation,
)

from .paper_artifact import PaperArtifact, PaperQuestionArtifact


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperSectionFilter(_StrictModel):
    question_type: str | None = None
    difficulty: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)


class PaperSectionRule(_StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    filter: PaperSectionFilter = Field(default_factory=PaperSectionFilter)
    order: Literal["source", "easy_to_hard", "manual"] = "source"
    question_ids: list[str] = Field(default_factory=list)


class PaperReorderRules(_StrictModel):
    sections: list[PaperSectionRule] = Field(min_length=1)
    unassigned_policy: Literal["append", "reject"] = "append"


class PaperReorderRequest(_StrictModel):
    source_id: str = Field(min_length=1)
    rules: PaperReorderRules
    include_answer_sheet: bool = False


class ReorderedQuestion(_StrictModel):
    display_number: str
    source_question_id: str
    original_number: str
    original_index: int
    question_text: str
    images: list[str] = Field(default_factory=list)
    question_type: str
    difficulty: str
    knowledge_point_ids: list[str] = Field(default_factory=list)


class ReorderedSection(_StrictModel):
    id: str
    title: str
    questions: list[ReorderedQuestion] = Field(default_factory=list)


class AnswerSheetEntry(_StrictModel):
    display_number: str
    source_question_id: str
    original_number: str
    answer: str


class PaperAudit(_StrictModel):
    input_count: int
    output_count: int
    unassigned_ids: list[str] = Field(default_factory=list)
    duplicate_ids: list[str] = Field(default_factory=list)


class ReorderedPaper(_StrictModel):
    id: str
    source_id: str
    sections: list[ReorderedSection]
    answer_sheet: list[AnswerSheetEntry] | None = None
    audit: PaperAudit
    missing_image_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PaperReorderError(ValueError):
    """Raised when request rules cannot produce a safe reordered paper."""

    def __init__(self, message: str, *, audit: PaperAudit | None = None) -> None:
        super().__init__(message)
        self.audit = audit


class PaperExportError(ValueError):
    """Raised when an unsafe preview is sent to an export renderer."""


@dataclass(frozen=True, slots=True)
class _QuestionTraceRef:
    """Minimal adapter for the canonical agent-layer conservation guard."""

    question_id: str


def _matches(question: PaperQuestionArtifact, rule_filter: PaperSectionFilter) -> bool:
    parsed = question.parsed_question
    if rule_filter.question_type and parsed.question_type != rule_filter.question_type:
        return False
    if rule_filter.difficulty and parsed.difficulty != rule_filter.difficulty:
        return False
    if rule_filter.knowledge_point_ids and not (
        set(rule_filter.knowledge_point_ids) & set(question.knowledge_point_ids)
    ):
        return False
    return True


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _section_candidates(
    source_questions: tuple[PaperQuestionArtifact, ...],
    rule: PaperSectionRule,
    id_lookup: dict[str, PaperQuestionArtifact],
) -> list[PaperQuestionArtifact]:
    if rule.question_ids:
        candidates = [id_lookup[question_id] for question_id in rule.question_ids]
    else:
        candidates = list(source_questions)
    candidates = [question for question in candidates if _matches(question, rule.filter)]

    if rule.order == "manual":
        return candidates
    if rule.order == "easy_to_hard":
        difficulty_rank = {"easy": 0, "medium": 1, "hard": 2}
        return sorted(
            candidates,
            key=lambda question: (
                difficulty_rank.get(question.parsed_question.difficulty, 3),
                question.parsed_question.original_index,
            ),
        )
    return sorted(candidates, key=lambda question: question.parsed_question.original_index)


def _paper_id(request: PaperReorderRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return f"paper-{sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def reorder_paper(artifact: PaperArtifact, request: PaperReorderRequest) -> ReorderedPaper:
    """Apply section rules while retaining exactly one traceable source row per id.

    Repeated selections are recorded and skipped in the preview.  This keeps the
    output auditable and count-stable while still making the invalid rule set
    visible to an editor; :func:`ensure_exportable` blocks publication.
    """
    if artifact.source_id != request.source_id:
        raise PaperReorderError("Request source_id does not match the loaded paper artifact")

    source_ids = {question.stable_id for question in artifact.questions}
    requested_ids = {
        question_id for section in request.rules.sections for question_id in section.question_ids
    }
    unknown_ids = sorted(requested_ids - source_ids)
    if unknown_ids:
        raise PaperReorderError(f"Rules reference unknown question ids: {', '.join(unknown_ids)}")

    id_lookup: dict[str, PaperQuestionArtifact] = {}
    source_duplicate_ids: list[str] = []
    for question in artifact.questions:
        if question.stable_id in id_lookup:
            _append_once(source_duplicate_ids, question.stable_id)
        else:
            id_lookup[question.stable_id] = question

    assigned_ids: set[str] = set()
    duplicate_ids = list(source_duplicate_ids)
    selected_sections: list[tuple[str, str, list[PaperQuestionArtifact]]] = []
    for rule in request.rules.sections:
        selected: list[PaperQuestionArtifact] = []
        for question in _section_candidates(artifact.questions, rule, id_lookup):
            if question.stable_id in assigned_ids:
                _append_once(duplicate_ids, question.stable_id)
                continue
            assigned_ids.add(question.stable_id)
            selected.append(question)
        selected_sections.append((rule.id, rule.title, selected))

    unassigned = [
        question for question in artifact.questions if question.stable_id not in assigned_ids
    ]
    if unassigned and request.rules.unassigned_policy == "reject":
        audit = PaperAudit(
            input_count=len(artifact.questions),
            output_count=sum(len(section[2]) for section in selected_sections),
            unassigned_ids=[question.stable_id for question in unassigned],
            duplicate_ids=duplicate_ids,
        )
        raise PaperReorderError("Some source questions are unassigned", audit=audit)

    warnings: list[str] = []
    if unassigned:
        selected_sections.append(("unassigned", "未分组题目", unassigned))
        assigned_ids.update(question.stable_id for question in unassigned)
        warnings.append(f"{len(unassigned)} 道未匹配题目已追加到“未分组题目”")
    if duplicate_ids:
        warnings.append(f"发现 {len(duplicate_ids)} 个重复题目 ID；预览已去重，导出已禁用")
    if artifact.missing_image_refs:
        warnings.append(f"发现 {len(artifact.missing_image_refs)} 个丢失图片引用；导出已禁用")

    display_number = 0
    answer_sheet: list[AnswerSheetEntry] = []
    sections: list[ReorderedSection] = []
    for section_id, title, selected in selected_sections:
        output_questions: list[ReorderedQuestion] = []
        for question in selected:
            display_number += 1
            parsed = question.parsed_question
            rendered_number = str(display_number)
            output_questions.append(
                ReorderedQuestion(
                    display_number=rendered_number,
                    source_question_id=question.stable_id,
                    original_number=question.original_number,
                    original_index=parsed.original_index,
                    question_text=parsed.question_text,
                    images=list(question.images),
                    question_type=parsed.question_type,
                    difficulty=parsed.difficulty,
                    knowledge_point_ids=list(question.knowledge_point_ids),
                )
            )
            if request.include_answer_sheet:
                answer_sheet.append(
                    AnswerSheetEntry(
                        display_number=rendered_number,
                        source_question_id=question.stable_id,
                        original_number=question.original_number,
                        answer=parsed.answer or "",
                    )
                )
        sections.append(ReorderedSection(id=section_id, title=title, questions=output_questions))

    audit = PaperAudit(
        input_count=len(artifact.questions),
        output_count=display_number,
        unassigned_ids=[],
        duplicate_ids=duplicate_ids,
    )
    try:
        validate_conservation(
            [question.parsed_question for question in artifact.questions],
            [
                _QuestionTraceRef(question.source_question_id)
                for section in sections
                for question in section.questions
            ],
        )
    except ArtifactConservationError as exc:
        raise PaperReorderError(str(exc), audit=audit) from exc

    return ReorderedPaper(
        id=_paper_id(request),
        source_id=request.source_id,
        sections=sections,
        answer_sheet=answer_sheet if request.include_answer_sheet else None,
        audit=audit,
        missing_image_refs=list(artifact.missing_image_refs),
        warnings=warnings,
    )


def ensure_exportable(paper: ReorderedPaper) -> None:
    """Enforce conservation and media integrity at the publication boundary."""
    failures: list[str] = []
    if paper.audit.output_count != paper.audit.input_count:
        failures.append("input/output question counts differ")
    if paper.audit.unassigned_ids:
        failures.append("questions remain unassigned")
    if paper.audit.duplicate_ids:
        failures.append("duplicate question ids were selected")
    if paper.missing_image_refs:
        failures.append("image references are missing")
    if failures:
        raise PaperExportError("Paper cannot be exported: " + "; ".join(failures))


def _markdown_export(paper: ReorderedPaper) -> str:
    lines = ["# 重排试卷", ""]
    for section in paper.sections:
        lines.extend((f"## {section.title}", ""))
        for question in section.questions:
            lines.extend((f"{question.display_number}. {question.question_text}", ""))
            for image in question.images:
                lines.extend((f"![题目 {question.display_number} 图片]({image})", ""))
    if paper.answer_sheet is not None:
        lines.extend(("---", "", "# 教师答案页", ""))
        for answer in paper.answer_sheet:
            lines.extend(
                (
                    f"{answer.display_number}. {answer.answer or '（原卷未提供答案）'}",
                    f"   - 原题号：{answer.original_number}",
                    f"   - source_question_id：`{answer.source_question_id}`",
                    "",
                )
            )
    return "\n".join(lines).rstrip() + "\n"


def _html_export(paper: ReorderedPaper) -> str:
    sections: list[str] = []
    for section in paper.sections:
        questions: list[str] = []
        for question in section.questions:
            images = "".join(
                f'<figure><img src="{escape(image, quote=True)}" '
                f'alt="题目 {escape(question.display_number)} 图片"></figure>'
                for image in question.images
            )
            questions.append(
                '<article class="question">'
                f'<span class="number">{escape(question.display_number)}.</span>'
                f'<div><div class="stem">{escape(question.question_text)}</div>{images}</div>'
                "</article>"
            )
        sections.append(f"<section><h2>{escape(section.title)}</h2>{''.join(questions)}</section>")

    answer_page = ""
    if paper.answer_sheet is not None:
        answer_rows = "".join(
            "<tr>"
            f"<td>{escape(answer.display_number)}</td>"
            f"<td>{escape(answer.original_number)}</td>"
            f"<td>{escape(answer.answer or '（原卷未提供答案）')}</td>"
            f"<td><code>{escape(answer.source_question_id)}</code></td>"
            "</tr>"
            for answer in paper.answer_sheet
        )
        answer_page = (
            '<section class="answer-page"><h1>教师答案页</h1>'
            "<table><thead><tr><th>题号</th><th>原题号</th><th>答案</th>"
            f"<th>来源 ID</th></tr></thead><tbody>{answer_rows}</tbody></table></section>"
        )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>重排试卷</title>
<style>
body{{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;max-width:860px;margin:40px auto;padding:0 24px;color:#172033}}
h1{{font-size:28px}}h2{{font-size:20px;margin-top:32px;border-bottom:1px solid #d8dee9;padding-bottom:8px}}
.question{{display:grid;grid-template-columns:36px 1fr;gap:8px;margin:20px 0;break-inside:avoid}}.number{{font-weight:700}}
.stem{{white-space:pre-wrap;line-height:1.75}}img{{max-width:100%;height:auto}}figure{{margin:12px 0}}
table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #d8dee9;padding:8px;text-align:left;vertical-align:top}}
.answer-page{{break-before:page}}@media print{{body{{margin:0;max-width:none}}}}
</style></head><body><h1>重排试卷</h1>{"".join(sections)}{answer_page}</body></html>"""


def render_paper_export(paper: ReorderedPaper, export_format: Literal["html", "markdown"]) -> str:
    ensure_exportable(paper)
    if export_format == "html":
        return _html_export(paper)
    if export_format == "markdown":
        return _markdown_export(paper)
    raise PaperExportError(f"Unsupported export format: {export_format}")


__all__ = [
    "AnswerSheetEntry",
    "PaperAudit",
    "PaperExportError",
    "PaperReorderError",
    "PaperReorderRequest",
    "PaperReorderRules",
    "PaperSectionFilter",
    "PaperSectionRule",
    "ReorderedPaper",
    "ReorderedQuestion",
    "ReorderedSection",
    "ensure_exportable",
    "render_paper_export",
    "reorder_paper",
]
