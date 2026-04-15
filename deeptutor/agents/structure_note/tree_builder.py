from __future__ import annotations

from collections import defaultdict
import re

from deeptutor.services.llm import complete as llm_complete
from deeptutor.utils.json_parser import parse_json_response

from .models import PageIndexPage, SectionTreeNode


def _collect_heading_candidates(pages: list[PageIndexPage]) -> list[dict[str, object]]:
    grouped: dict[tuple[int, str], dict[str, object]] = {}
    for page in pages:
        for candidate in page.title_candidates:
            key = (candidate.page_number, candidate.text.strip())
            current = grouped.get(key)
            payload = {
                "page_number": candidate.page_number,
                "text": candidate.text.strip(),
                "font_size": candidate.font_size,
                "score": candidate.score,
            }
            if current is None or float(payload["score"] or 0.0) > float(
                current.get("score") or 0.0
            ):
                grouped[key] = payload
    candidates = list(grouped.values())
    candidates.sort(key=lambda item: (int(item["page_number"]), -float(item.get("score") or 0.0)))
    return candidates[:60]


def _clean_excerpt(text: str, limit: int = 520) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit].rstrip()}..."


def _page_overviews(pages: list[PageIndexPage], limit: int = 36) -> list[dict[str, object]]:
    overviews: list[dict[str, object]] = []
    for page in pages[:limit]:
        overviews.append(
            {
                "page_number": page.page_number,
                "heading_candidates": [candidate.text for candidate in page.title_candidates[:5]],
                "excerpt": _clean_excerpt(page.text, 480),
                "image_count": len(page.image_candidates),
            }
        )
    return overviews


def _summary_from_pages(pages: list[PageIndexPage], page_start: int, page_end: int) -> str:
    snippets: list[str] = []
    for page in pages:
        if page_start <= page.page_number <= page_end and page.text.strip():
            snippets.append(_clean_excerpt(page.text, 180))
        if len(snippets) >= 2:
            break
    return " ".join(snippets)


def _fallback_sections(pages: list[PageIndexPage], page_window: int) -> list[SectionTreeNode]:
    nodes: list[SectionTreeNode] = []
    for index, start in enumerate(range(1, len(pages) + 1, page_window), start=1):
        end = min(start + page_window - 1, len(pages))
        title = f"Pages {start}-{end}" if start != end else f"Page {start}"
        nodes.append(
            SectionTreeNode(
                section_id=f"fallback-{index:03d}",
                title=title,
                level=2,
                page_start=start,
                page_end=end,
                summary=_summary_from_pages(pages, start, end),
                path=[title],
            )
        )
    return nodes


def _coerce_sections(
    raw_sections: list[dict[str, object]], total_pages: int
) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()
    for raw in raw_sections:
        title = str(raw.get("title", "")).strip()
        if not title:
            continue
        try:
            page_start = int(raw.get("page_start", 0))
        except Exception:
            continue
        if page_start < 1 or page_start > total_pages:
            continue
        try:
            level = int(raw.get("level", 2))
        except Exception:
            level = 2
        level = max(2, min(level, 5))
        summary = str(raw.get("summary", "")).strip()
        key = (page_start, title)
        if key in seen:
            continue
        seen.add(key)
        sections.append(
            {"title": title, "page_start": page_start, "level": level, "summary": summary}
        )
    sections.sort(
        key=lambda item: (int(item["page_start"]), int(item["level"]), str(item["title"]))
    )
    return sections


async def build_section_tree(
    pages: list[PageIndexPage],
    page_window: int,
    language: str = "en",
) -> list[SectionTreeNode]:
    total_pages = len(pages)
    candidates = _collect_heading_candidates(pages)
    if len(candidates) < 2:
        return _fallback_sections(pages, page_window)

    prompt = (
        "You are building a PageIndex-style document tree for Structure Note only.\n"
        "PageIndex uses a table-of-contents-like hierarchy first, then retrieves by reasoning over that tree. "
        "Your task is to infer a stable document-level outline, not page-by-page notes.\n"
        "Return JSON only with shape "
        '{"sections": [{"title": str, "level": 2-5, "page_start": int, "summary": str}]}\n'
        "Rules:\n"
        "- Keep the sections in reading order.\n"
        "- Use only headings that are strongly supported by the candidates.\n"
        "- Use levels 2-5 only.\n"
        "- Do not invent page numbers outside the document.\n"
        "- Include 3-20 sections depending on the material.\n"
        "- Merge repeated slide headers into one section when they represent the same topic.\n"
        "- Summaries should describe the section topic in one short sentence.\n"
        f"- Output language: {'Chinese' if language == 'zh' else 'English'}.\n\n"
        f"Total pages: {total_pages}\n"
        f"Heading candidates: {candidates}\n"
        f"Page overviews: {_page_overviews(pages)}"
    )

    try:
        raw_response = await llm_complete(
            prompt=prompt,
            system_prompt="You convert page heading candidates into structured JSON.",
            temperature=0.1,
        )
        parsed = parse_json_response(raw_response, fallback={})
        raw_sections = parsed.get("sections") if isinstance(parsed, dict) else None
        if not isinstance(raw_sections, list):
            raise ValueError("Missing sections array")
        sections = _coerce_sections(raw_sections, total_pages)
    except Exception:
        sections = []

    if not sections:
        return _fallback_sections(pages, page_window)

    nodes: list[SectionTreeNode] = []
    stack: list[SectionTreeNode] = []
    child_map: dict[str, list[str]] = defaultdict(list)

    for index, section in enumerate(sections):
        title = str(section["title"])
        page_start = int(section["page_start"])
        level = int(section["level"])

        while stack and stack[-1].level >= level:
            stack.pop()

        parent_id = stack[-1].section_id if stack else None
        path = [*stack[-1].path, title] if stack else [title]
        node = SectionTreeNode(
            section_id=f"section-{index + 1:03d}",
            title=title,
            level=level,
            page_start=page_start,
            page_end=page_start,
            summary=str(section.get("summary") or ""),
            parent_id=parent_id,
            path=path,
        )
        if parent_id:
            child_map[parent_id].append(node.section_id)
        nodes.append(node)
        stack.append(node)

    for index, node in enumerate(nodes):
        next_boundary = total_pages + 1
        for later in nodes[index + 1 :]:
            if later.level <= node.level:
                next_boundary = later.page_start
                break
        node.page_end = max(node.page_start, min(total_pages, next_boundary - 1))
        if not node.summary:
            node.summary = _summary_from_pages(pages, node.page_start, node.page_end)

    for node in nodes:
        node.child_ids = child_map.get(node.section_id, [])
    return nodes
