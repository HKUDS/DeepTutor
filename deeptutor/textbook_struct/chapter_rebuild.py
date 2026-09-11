"""Layered chapter rebuild from MinerU ``layout.json``.

Layers (all deterministic, no LLM):
  0. column blacklist   — feature-column names are never chapters (closed vocabulary)
  1. regex              — ``第X课/章/节/单元`` headings (works regardless of height)
  2. position filter    — heading must sit in the page-top band (y0 < top)
  3. adjacent merge     — same-page title blocks split by line-wrap rejoin

Input is the MinerU layout dict (``layout["pdf_info"]``), one page object per
page with ``page_idx`` / ``para_blocks``; blocks carry ``type`` / ``bbox`` /
``lines[].spans[].content``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from .column_blacklist import COLUMN_BLACKLIST

CHAPTER_RE = re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*[课章节单元]")

# Title blocks whose text is shorter than this are layout noise (figure
# captions etc.) — never chapters even if they regex-match.
MIN_TITLE_CHARS = 4


@dataclass
class Chapter:
    """One rebuilt chapter: title + start page (0-based) + bbox on that page."""

    title: str
    page_idx: int
    bbox: list[float]
    end_page_idx: int | None = None  # filled by assign_page_ranges
    level: int = 1  # reserved: 1=lesson/chapter (课/章), 2=section (框/节)
    meta: dict = field(default_factory=dict)


def block_text(block: dict) -> str:
    return "".join(
        span.get("content", "") for line in block.get("lines", []) for span in line.get("spans", [])
    ).strip()


def merge_adjacent(blocks: list[dict], gap: float = 40.0) -> list[dict]:
    """Rejoin same-page title blocks split by line-wrap.

    Sort by y0; vertical gap < ``gap`` with x-overlap merges into the first
    block (bbox union, text concat). Mutates nothing — returns new dicts.
    """
    merged: list[dict] = []
    for block in sorted(blocks, key=lambda b: b["bbox"][1]):
        if merged:
            prev = merged[-1]
            vgap = block["bbox"][1] - prev["bbox"][3]
            x_overlap = min(block["bbox"][2], prev["bbox"][2]) - max(
                block["bbox"][0], prev["bbox"][0]
            )
            if vgap < gap and x_overlap > 0:
                prev["bbox"] = [
                    min(prev["bbox"][0], block["bbox"][0]),
                    min(prev["bbox"][1], block["bbox"][1]),
                    max(prev["bbox"][2], block["bbox"][2]),
                    max(prev["bbox"][3], block["bbox"][3]),
                ]
                prev["text"] = (prev.get("text", "") + block_text(block)).strip()
                continue
        item = dict(block)
        item["text"] = block_text(block)
        merged.append(item)
    return merged


def rebuild(
    layout: dict,
    *,
    top_band: float = 120.0,
    merge_gap: float = 40.0,
) -> list[Chapter]:
    """Run the layered pipeline over ``layout`` and return chapter starts."""
    chapters: list[Chapter] = []
    for page in layout.get("pdf_info", []):
        title_blocks = [b for b in page.get("para_blocks", []) if b.get("type") == "title"]
        for block in merge_adjacent(title_blocks, gap=merge_gap):
            text = block.get("text", "")
            if text in COLUMN_BLACKLIST:  # layer 0 — closed column names
                continue
            if not CHAPTER_RE.match(text):  # layer 1 — regex first
                continue
            if len(text.replace(" ", "")) < MIN_TITLE_CHARS:
                continue
            if block["bbox"][1] >= top_band:  # layer 2 — page-top band
                continue
            chapters.append(
                Chapter(
                    title=text,
                    page_idx=page["page_idx"],
                    bbox=list(block["bbox"]),
                )
            )
    chapters = _dedupe_keep_last(chapters)  # TOC page duplicates body hits — keep body
    return assign_page_ranges(chapters, page_count=len(layout.get("pdf_info", [])))


def _dedupe_keep_last(chapters: list[Chapter]) -> list[Chapter]:
    """Same title appearing on TOC page AND in the body: keep the body hit."""
    by_title: dict[str, Chapter] = {}
    order: list[str] = []
    for chapter in chapters:
        if chapter.title in by_title:
            by_title[chapter.title] = chapter  # later (higher page) wins
        else:
            by_title[chapter.title] = chapter
            order.append(chapter.title)
    return [by_title[t] for t in order]


def assign_page_ranges(chapters: list[Chapter], *, page_count: int) -> list[Chapter]:
    """Chapter i spans [start_i, start_{i+1}); the last runs to the last page."""
    for i, chapter in enumerate(chapters):
        chapter.end_page_idx = (
            chapters[i + 1].page_idx
            if i + 1 < len(chapters)
            else max(page_count - 1, chapter.page_idx)
        )
    return chapters


# ── Mid-page section-frame detection (no page-top band constraint) ─────────
# Measured heading heights: frame ~22-24, exploration ~27, body lines ~21,
# lesson-title wrap residue ~28. Column names go to the blacklist; stray
# publisher header lines go to PUBLISHER_NOISE.

PUBLISHER_NOISE = frozenset({"人民教育出版社", "出版社", "思想政治", "目录", "后记"})


def detect_frames(
    layout: dict,
    *,
    height_range: tuple[float, float] = (20.0, 25.0),
    extras_range: tuple[float, float] = (26.0, 29.0),
    first_lesson_page_idx: int | None = None,
    lesson_titles: list[str] = (),
) -> tuple[list[dict], list[dict]]:
    """Detect section-frame headings (and chapter-level extras like 综合探究).

    Returns ``(frames, extras)`` — each item ``{title, page_idx, bbox, height}``.
    Frames are mid-page title blocks in the frame height band; extras
    (exploration sections / afterword) sit in the slightly taller band.
    Blacklist + publisher noise + lesson-level regex filtered out.
    """
    frames: list[dict] = []
    extras: list[dict] = []
    for page in layout.get("pdf_info", []):
        for block in page.get("para_blocks", []):
            if block.get("type") != "title":
                continue
            text = block_text(block)
            if not text or text in COLUMN_BLACKLIST or text in PUBLISHER_NOISE:
                continue
            if CHAPTER_RE.match(text):
                continue  # lesson-level handled by the footer path
            height = block["bbox"][3] - block["bbox"][1]
            item = {
                "title": text,
                "page_idx": page["page_idx"],
                "bbox": list(block["bbox"]),
                "height": round(height, 1),
            }
            if height_range[0] <= height <= height_range[1]:
                if len(text) >= 6:
                    # front-matter noise + lesson-title wrap residue
                    # (substring of a lesson title)
                    if (
                        first_lesson_page_idx is not None
                        and item["page_idx"] < first_lesson_page_idx
                    ):
                        continue
                    if any(text in lt for lt in lesson_titles):
                        continue
                    frames.append(item)
            elif extras_range[0] <= height <= extras_range[1] and len(text) >= 3:
                extras.append(item)
    return frames, extras


# ── Level-aware boundaries + printed-offset consistency check ──────────────

UNIT_RE_MAP = {
    "课": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*课"),
    "章": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*章"),
    "节": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*节"),
    "单元": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*单元"),
}


def rebuild_from_headers_level(layout: dict, unit: str = "课") -> list[Chapter]:
    """Level-aware rebuild: only ``unit``-level running-header changes mark boundaries.

    In textbooks with two-level running headers (e.g. rotating
    "第X章/第Y节" pairs), a change at the other level must not start a
    chapter — otherwise pseudo-chapters get split out.
    """
    # Imported here to avoid a circular import (page_headers imports this
    # module's CHAPTER_RE / Chapter / assign_page_ranges at top level).
    from .page_headers import page_facts

    unit_re = UNIT_RE_MAP.get(unit)
    if unit_re is None:
        raise ValueError(f"unknown unit: {unit}")
    chapters: list[Chapter] = []
    seen: set[str] = set()
    page_count = len(layout.get("pdf_info", []))
    for page in layout.get("pdf_info", []):
        footers, printed = page_facts(page)
        for title in footers:
            if not unit_re.match(title):
                continue
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


def verify_offset(chapters: list[Chapter]) -> dict:
    """Printed-offset consistency: physical (1-based) − printed page number.

    An offset that varies across chapters means a chapter boundary was
    mis-detected.
    """
    offsets = sorted(
        {c.page_idx + 1 - c.meta["printed_page"] for c in chapters if c.meta.get("printed_page")}
    )
    return {
        "offsets": offsets,
        "consistent": len(offsets) <= 1,
        "ok": bool(offsets) and len(offsets) == 1,
    }
