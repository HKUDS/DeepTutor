"""Header-driven chapter rebuild (v0.2) — running headers never lie.

MinerU discards page furniture into ``page["discarded_blocks"]``, but for K12
textbooks that furniture is gold:
  - ``footer`` blocks repeat the current chapter title (running header)
  - ``page_number`` blocks carry the PRINTED page number

A chapter starts where its running header first appears; the printed page
number comes free on the very same page. This fixes the TOC-page false
positives of the title-block path (v0.1), and measures the printed-vs-
physical page offset per chapter instead of guessing it.
"""

from __future__ import annotations

import re

from .chapter_rebuild import CHAPTER_RE, Chapter, assign_page_ranges


def _block_text(block: dict) -> str:
    return "".join(
        span.get("content", "") for line in block.get("lines", []) for span in line.get("spans", [])
    ).strip()


#: Running-header variants that embed the chapter token mid-text — some
#: publishers print the chapter name in the running *header* (embedded
#: mid-text, e.g. “集合第1章”, “空间向量与立体几何 第6章”), often without a
#: leading “第”; others print it in the footer. Header variants are extracted
#: and normalized to the canonical “第N章 章名” shape so the level filter and
#: dedupe see the same vocabulary the footer path produces.
HEADER_CHAPTER_RE = re.compile(
    r"^(?P<pre>.{0,20}?)\s*第\s*(?P<num>[一二三四五六七八九十百\d]+)\s*"
    r"(?P<unit>[课章节单元])\s*(?P<post>.{0,30}?)\s*$"
)


def normalize_header_chapter(text: str) -> str | None:
    """Normalize a mid-text chapter header to “第N单元 章名” (None = no match)."""
    m = HEADER_CHAPTER_RE.match(text)
    if not m:
        return None
    name = (m.group("pre") or m.group("post") or "").strip()
    token = f"第{m.group('num')}{m.group('unit')}"
    return f"{token} {name}" if name else token


def page_facts(page: dict) -> tuple[list[str], str]:
    """Return ``(chapter_shaped_footers, printed_page_number)`` for one page.

    Chapter-shaped furniture is read from *both* running-header positions:
    footer blocks matching ``CHAPTER_RE`` verbatim (publishers that print the
    chapter name in the footer) and header blocks whose chapter token sits
    mid-text (publishers that embed it in the header, normalized via
    :func:`normalize_header_chapter`).
    """
    footers: list[str] = []
    printed = ""
    for block in page.get("discarded_blocks", []):
        text = _block_text(block)
        if not text:
            continue
        btype = block.get("type")
        if btype == "footer" and CHAPTER_RE.match(text):
            footers.append(text)
        elif btype == "header":
            normalized = normalize_header_chapter(text)
            if normalized is not None:
                footers.append(normalized)
        elif btype == "page_number" and text.isdigit():
            printed = text
    return footers, printed


def rebuild_from_headers(layout: dict) -> list[Chapter]:
    """Chapter starts = first page where each new running header appears.

    Titles are taken verbatim from the running header; ``meta`` carries the
    printed page number of the start page (the display layer decides which
    base to show — the fix is data, not guesswork).
    """
    chapters: list[Chapter] = []
    seen: set[str] = set()
    page_count = len(layout.get("pdf_info", []))
    for page in layout.get("pdf_info", []):
        footers, printed = page_facts(page)
        for title in footers:
            if title in seen:
                continue
            seen.add(title)
            chapters.append(
                Chapter(
                    title=title,
                    page_idx=page["page_idx"],
                    bbox=[],
                    meta={"printed_page": int(printed) if printed.isdigit() else None},
                )
            )
    return assign_page_ranges(chapters, page_count=page_count)
