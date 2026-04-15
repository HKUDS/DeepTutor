from __future__ import annotations

import re

from .models import DocumentPlan, PageIndexPage, SectionEvidence, SectionPlan, SectionTreeNode


def _clean_text(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _page_lookup(pages: list[PageIndexPage]) -> dict[int, PageIndexPage]:
    return {page.page_number: page for page in pages}


def _section_evidence(
    pages: list[PageIndexPage],
    page_numbers: list[int],
    *,
    excerpt_limit: int = 900,
) -> list[SectionEvidence]:
    lookup = _page_lookup(pages)
    evidence: list[SectionEvidence] = []
    for page_number in page_numbers:
        page = lookup.get(page_number)
        if not page:
            continue
        excerpt = _clean_text(page.text, excerpt_limit)
        if not excerpt and not page.image_candidates and not page.title_candidates:
            continue
        evidence.append(
            SectionEvidence(
                page_number=page_number,
                excerpt=excerpt,
                title_candidates=[candidate.text for candidate in page.title_candidates[:5]],
                image_candidate_ids=[
                    candidate.candidate_id for candidate in page.image_candidates[:8]
                ],
            )
        )
    return evidence


def _fallback_summary(evidence: list[SectionEvidence]) -> str:
    for item in evidence:
        if item.excerpt:
            return _clean_text(item.excerpt, 220)
    return ""


def _build_page_to_sections(sections: list[SectionPlan]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for section in sections:
        for page_number in section.page_numbers:
            mapping.setdefault(str(page_number), []).append(section.section_id)
    return mapping


def _document_summary(sections: list[SectionPlan], language: str) -> str:
    titles = [section.title for section in sections[:8]]
    if not titles:
        return (
            "No extractable section structure was found."
            if language != "zh"
            else "未提取到可用章节结构。"
        )
    joined = " / ".join(titles)
    if language == "zh":
        return f"本讲义围绕 {joined} 等章节组织内容。"
    return f"This note is organized around {joined}."


def build_document_plan(
    pages: list[PageIndexPage],
    sections: list[SectionTreeNode],
    *,
    document_title: str,
    language: str = "en",
) -> DocumentPlan:
    """Create the Structure Note planning backbone from the PageIndex-style tree.

    This intentionally stays inside Structure Note. It uses the document tree as the
    retrieval surface, then attaches page-grounded evidence for section generation.
    """

    section_plans: list[SectionPlan] = []
    previous_section_id: str | None = None

    for node in sorted(sections, key=lambda item: (item.page_start, item.level, item.section_id)):
        page_numbers = list(range(node.page_start, node.page_end + 1))
        evidence = _section_evidence(pages, page_numbers)
        summary = node.summary.strip() or _fallback_summary(evidence)
        writing_goal = (
            f"Explain {node.title} as a coherent study-note section using pages {node.page_start}-{node.page_end}."
            if language != "zh"
            else f"基于第 {node.page_start}-{node.page_end} 页，把“{node.title}”写成连贯的学习讲义章节。"
        )
        dependencies = [previous_section_id] if previous_section_id else []
        section_plans.append(
            SectionPlan(
                section_id=node.section_id,
                title=node.title,
                level=node.level,
                section_path=node.path or [node.title],
                page_start=node.page_start,
                page_end=node.page_end,
                page_numbers=page_numbers,
                summary=summary,
                writing_goal=writing_goal,
                dependencies=dependencies,
                evidence=evidence,
            )
        )
        previous_section_id = node.section_id

    return DocumentPlan(
        document_title=document_title,
        document_summary=_document_summary(section_plans, language),
        outline=section_plans,
        section_order=[section.section_id for section in section_plans],
        page_to_sections=_build_page_to_sections(section_plans),
    )
