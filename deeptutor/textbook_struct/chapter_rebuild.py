"""Four-layer chapter rebuild from MinerU ``layout.json``.

Layers (all deterministic, no LLM):
  0. column blacklist   — 栏目名 never chapters (closed vocabulary)
  1. regex              — ``第X课/章/节/单元`` headings (works regardless of height)
  2. position filter    — heading must sit in the page-top band (y0 < top)
  3. adjacent merge     — same-page title blocks split by line-wrap rejoin
  4. TOC cross-check    — printed TOC page entries validate hit rate

Input is the MinerU layout dict (``layout["pdf_info"]``), one page object per
page with ``page_idx`` / ``para_blocks``; blocks carry ``type`` / ``bbox`` /
``lines[].spans[].content``. Spec: P0-章节重建引擎实施方案 §4.
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
    level: int = 1  # reserved: 1=课/章, 2=框/节 (from TOC cross-check)
    meta: dict = field(default_factory=dict)


def block_text(block: dict) -> str:
    return "".join(
        span.get("content", "") for line in block.get("lines", []) for span in line.get("spans", [])
    ).strip()


def merge_adjacent(blocks: list[dict], gap: float = 40.0) -> list[dict]:
    """Rejoin same-page title blocks split by line-wrap (counterexample #1).

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
    """Run the four-layer pipeline over ``layout`` and return chapter starts."""
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
    chapters = _dedupe_keep_last(chapters)  # counterexample #4: TOC page duplicates body
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


# ── v0.3: 框级/综合探究检测（页中 title 块，无页顶带约束）────────────────
# 实测（必修1）：框标题 h=22-24，综合探究 h≈27，小节行 h≈21，课标题残留 h≈28。
# 栏目名走黑名单；出版社页眉漏网走 PUBLISHER_NOISE。

PUBLISHER_NOISE = frozenset({"人民教育出版社", "出版社", "思想政治", "目录", "后记"})


def detect_frames(
    layout: dict,
    *,
    height_range: tuple[float, float] = (20.0, 25.0),
    extras_range: tuple[float, float] = (26.0, 29.0),
    first_lesson_page_idx: int | None = None,
    lesson_titles: list[str] = (),
) -> tuple[list[dict], list[dict]]:
    """Detect 框-level headings (and chapter-level extras like 综合探究).

    Returns ``(frames, extras)`` — each item ``{title, page_idx, bbox, height}``.
    框 = mid-page title blocks in the frame height band; extras (综合探究/后记)
    sit in the slightly taller band. Blacklist + publisher noise + 课 regex
    filtered out.
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
                continue  # 课级走页脚法
            height = block["bbox"][3] - block["bbox"][1]
            item = {
                "title": text,
                "page_idx": page["page_idx"],
                "bbox": list(block["bbox"]),
                "height": round(height, 1),
            }
            if height_range[0] <= height <= height_range[1]:
                if len(text) >= 6:
                    # 封面/前置页噪音 + 课标题换行残留（是某课标题的子串）
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


# ── v0.4: 级别感知边界 + 偏移恒定校验（P0 方案 §4.5/§6）────────────────
from .page_headers import page_facts

UNIT_RE_MAP = {
    "课": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*课"),
    "章": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*章"),
    "节": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*节"),
    "单元": re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*单元"),
}


def rebuild_from_headers_level(layout: dict, unit: str = "课") -> list[Chapter]:
    """级别感知页脚法：只认目标级别（如"课"）的页眉变化为章界。

    双级页眉教材（地理"第X章/第Y节"同页眉轮换）中，非目标级别的页眉变化
    不构成边界——否则会误切出伪章节（P0 方案反例 #7）。
    """
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
    """偏移恒定校验：物理页(1-based) − 印刷页码 应全书恒定。

    偏移不一致 = 页脚法误判了章节边界（P0 方案 §6 校验逻辑）。
    """
    offsets = sorted(
        {c.page_idx + 1 - c.meta["printed_page"] for c in chapters if c.meta.get("printed_page")}
    )
    return {
        "offsets": offsets,
        "consistent": len(offsets) <= 1,
        "ok": bool(offsets) and len(offsets) == 1,
    }


# ── v0.5: 三通道 fallback 链（页脚法 → 页眉法 → 概述锚定法）────────────────
# 页脚法+页眉法同源 page_facts（footer 原文 + header 嵌章 token），合并为一
# 通道，0 章时不再各自空转。第三通道概述锚定法只服务英语书（版式语言 en 或
# 书名含「英语」），中文书 0 章时保持原语义 —— 返回空 list 由调用方走降级表。

_OVERVIEW_GUARD_TITLE_HINT = ("英语", "english")


def rebuild_with_fallback(
    layout: dict,
    *,
    language: str = "zh",
    title: str = "",
) -> list[Chapter]:
    """页脚法/页眉法 0 章 → 概述锚定法（仅英语书启用）.

    第三通道 guard：仅当 ``language`` 为 ``en`` 或 ``title`` 含「英语」/
    ``english`` 时启用，防误伤中文书（中文版式 0 章时返回空 list，语义与
    旧链一致 —— 由调用方走 enrich 树转 toc 降级表）。
    """
    from .overview_anchor import rebuild_from_overview
    from .page_headers import rebuild_from_headers

    chapters = rebuild_from_headers(layout)
    if chapters:
        return chapters
    lang = (language or "").lower()
    name = (title or "").lower()
    is_english = lang == "en" or any(hint in name for hint in _OVERVIEW_GUARD_TITLE_HINT)
    if not is_english:
        return []
    return rebuild_from_overview(layout)
