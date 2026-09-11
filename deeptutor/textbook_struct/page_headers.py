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

from .chapter_rebuild import CHAPTER_RE, Chapter, assign_page_ranges


def _block_text(block: dict) -> str:
    return "".join(
        span.get("content", "") for line in block.get("lines", []) for span in line.get("spans", [])
    ).strip()


def page_facts(page: dict) -> tuple[list[str], str]:
    """Return ``(chapter_shaped_footers, printed_page_number)`` for one page."""
    footers: list[str] = []
    printed = ""
    for block in page.get("discarded_blocks", []):
        text = _block_text(block)
        if not text:
            continue
        btype = block.get("type")
        if btype == "footer" and CHAPTER_RE.match(text):
            footers.append(text)
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
