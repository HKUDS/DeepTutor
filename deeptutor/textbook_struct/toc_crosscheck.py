"""Printed-TOC extraction and cross-check (判据第 4 层 — 补漏与报警)."""

from __future__ import annotations

import re

from .chapter_rebuild import Chapter, block_text

# 目录页正文行：「第一课 …… 3」/「1.1 某某 …… 12」（点线或空格引导 + 印刷页码）
_TOC_LINE_RE = re.compile(r"^(.{2,40}?)[\s.．·…]{1,}(\d{1,3})$")


def extract_toc_entries(layout: dict, *, toc_page_idxs: set[int] | None = None) -> list[tuple[str, int]]:
    """Pull ``(title, printed_page)`` rows from the 目录 page(s).

    ``toc_page_idxs`` given → scan only those pages; otherwise scan every page's
    non-title text blocks for TOC-shaped lines (title + dot leader + number).
    """
    entries: list[tuple[str, int]] = []
    for page in layout.get("pdf_info", []):
        if toc_page_idxs is not None and page["page_idx"] not in toc_page_idxs:
            continue
        for block in page.get("para_blocks", []):
            if block.get("type") == "title":
                continue  # 目录页标题本体「目录」不算条目
            for line in block.get("lines", []):
                text = "".join(
                    span.get("content", "") for span in line.get("spans", [])
                ).strip()
                match = _TOC_LINE_RE.match(text)
                if match:
                    entries.append((match.group(1).strip(), int(match.group(2))))
    return entries


def cross_check_with_toc(
    chapters: list[Chapter],
    toc_entries: list[tuple[str, int]],
    *,
    hit_threshold: float = 0.8,
) -> dict:
    """Compare rebuilt chapters against the printed TOC.

    Matching is prefix-based (rebuilt titles carry 「第一课 …」; TOC rows may be
    trimmed). Returns a report: hit rate below ``hit_threshold`` means the
    rebuild is suspicious — escalate to human review (spec §4 layer 4).
    """
    if not toc_entries:
        return {"hits": 0, "total": len(chapters), "hit_rate": None, "ok": None,
                "note": "no printed TOC entries found"}
    hits = 0
    for chapter in chapters:
        for title, _page in toc_entries:
            if chapter.title.startswith(title[:8]) or title.startswith(chapter.title[:8]):
                hits += 1
                break
    hit_rate = hits / len(chapters) if chapters else 0.0
    return {
        "hits": hits,
        "total": len(chapters),
        "hit_rate": round(hit_rate, 3),
        "ok": hit_rate >= hit_threshold,
        "note": "",
    }
