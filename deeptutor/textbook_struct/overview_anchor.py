"""Overview-anchored chapter rebuild (v0.5) — English textbooks' "Unit N" spine.

English K12 textbooks (译林 学程×3 + 教师用书×7) open each unit with a
title line + 「一、单元概述」 page. The running-header channels (页脚法/页眉
法) anchor on Chinese layout marks and return 0 chapters on these books —
CHAPTERS 0, batch book-building idles. This third channel anchors on the
「一、单元概述」 marker instead:

  1. 单元起始锚 — a page whose para text contains 「一、单元概述」 is a Unit
     home candidate (the 使用说明 page's 「1. 单元概述」 is a digit-prefixed
     *text* block and never matches the literal 「一、」 anchor).
  2. Unit 标题对位 — the title line on that page (or the page before) matches
     ``Unit\\s*\\d+`` (case / full-width insensitive); the unit number is
     taken from it. The number may sit in a ``discarded_blocks`` header
     (MinerU splits "UNIT 4" off the theme title). Anchor pages without a
     number inherit the smallest missing unit number in scan order.
  3. 章界 — consecutive Unit home pages bound chapters; pages before the
     first unit go to a 「导览」 chapter, pages after the last to 「附录」
     (both names configurable).

Signature mirrors ``page_headers.rebuild_from_headers``: layout dict in,
``list[Chapter]`` out. Deterministic, no LLM.
"""

from __future__ import annotations

import re

from .chapter_rebuild import Chapter, assign_page_ranges, block_text

#: 单元起始锚：页面文本含此字面即 Unit 首页候选。「1. 单元概述」（使用说明页
#: 数字前缀）不会命中「一、」全角序数，天然防误报。
OVERVIEW_ANCHOR = "一、单元概述"

#: Unit 标题行：``UNIT 2`` / ``unit2`` / ``Unit ２``（大小写/全半角不敏感）。
#: 全半角在匹配前统一归一化。
_UNIT_NO_RE = re.compile(r"unit\s*([0-9]+)", re.IGNORECASE)

#: 栏目标题序号（「一、单元概述」「二、单元教学内容」…）——这些 title 块是
#: 单元内的栏目名，不是单元名本体。
_CN_ORDINAL_LEAD = re.compile(r"^[一二三四五六七八九十百]、")

#: 全角 → 半角（数字、大小写字母、空格）。MinerU OCR 偶发全角输出。
_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_FW_LETTERS = str.maketrans(
    "".join(chr(0xFF21 + i) for i in range(26)) + "".join(chr(0xFF41 + i) for i in range(26)),
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)
_FW_SPACE = str.maketrans({"　": " "})


def _normalize_text(text: str) -> str:
    return text.translate(_FW_DIGITS).translate(_FW_LETTERS).translate(_FW_SPACE)


def _has_overview_anchor(page: dict) -> bool:
    """判据 1 — 单元起始锚：页面 para 文本含「一、单元概述」."""
    return any(
        OVERVIEW_ANCHOR in block_text(block)
        for block in page.get("para_blocks", [])
        if block.get("type") in {"title", "text"}
    )


def _title_blocks(page: dict) -> list[dict]:
    """Anchor-page title lines: para ``title`` blocks + discarded ``header``s.

    MinerU often pushes the bare "UNIT 4" into ``discarded_blocks`` while the
    theme title (e.g. ``Living with technology``) stays a para title block —
    both must be scanned to pair number ↔ name (判据 2).
    """
    blocks = [b for b in page.get("para_blocks", []) if b.get("type") == "title"]
    blocks += [b for b in page.get("discarded_blocks", []) if b.get("type") == "header"]
    return sorted(blocks, key=lambda b: b["bbox"][1] if b.get("bbox") else 0.0)


def _unit_info(page: dict, prev_page: dict | None) -> tuple[int | None, str | None]:
    """Extract ``(unit_no, name)`` from an anchor page (+ its predecessor).

    ``unit_no`` — first ``Unit N`` match across the page's title/header blocks,
    falling back to the *preceding* page's title/header blocks (判据 2: 首页或
    其前 1 页). ``name`` — the anchor page's top non-「N、」 title block; when
    that block itself carries the ``UNIT N`` token, the text after it is the
    name ("UNIT 2 Sports culture" → "Sports culture"). The predecessor page
    only supplies the number — its titles belong to the previous unit's tail.
    """
    no: int | None = None
    name: str | None = None
    for block in _title_blocks(page):
        text = block_text(block)
        if not text or text == OVERVIEW_ANCHOR or _CN_ORDINAL_LEAD.match(text):
            continue  # 栏目名（一、单元概述 / 二、单元教学内容…）不是单元名
        match = _UNIT_NO_RE.search(_normalize_text(text))
        if match:
            no = int(match.group(1))
            rest = text[match.end() :].strip(" :-–—")
            if rest and name is None:
                name = rest
            continue
        if name is None:
            name = text  # 无 UNIT 序号的 title 块 = 单元主题名（"The mass media"）
    if no is None and prev_page is not None:
        for block in _title_blocks(prev_page):
            match = _UNIT_NO_RE.search(_normalize_text(block_text(block)))
            if match:
                no = int(match.group(1))
                break
    return no, name


def _assign_unit_numbers(
    anchors: list[tuple[int | None, int, str | None]],
) -> list[tuple[int, int, str]]:
    """Assign unit numbers to anchor pages, filling missing numbers in order.

    Anchors that carry an explicit ``Unit N`` keep it; numberless anchors
    inherit the smallest number not yet claimed (scan order). This keeps
    out-of-order scans correct (Unit 3 page before Unit 1) and lets a
    numberless Unit 1 fall back to 1.
    """
    seen: set[int] = set()  # 已确认的唯一 Unit 序号（页序最早者胜）
    units: list[tuple[int, int, str]] = []  # (unit_no, page_idx, title)
    for no, page_idx, name in anchors:
        if no is not None:
            if no in seen:
                continue  # 同 Unit 跨页续锚 —— 保留页序最早者
            seen.add(no)
        else:
            candidate = 1
            while candidate in seen:
                candidate += 1
            no = candidate
            seen.add(no)
        title = f"Unit {no}" + (f" {name}" if name else "")
        units.append((no, page_idx, title))
    return units


def rebuild_from_overview(
    layout: dict,
    *,
    overview_title: str = "导览",
    appendix_title: str = "附录",
) -> list[Chapter]:
    """Chapter starts = pages carrying the 「一、单元概述」 anchor.

    Consecutive Unit home pages bound chapters; pages before the first unit
    go to ``overview_title`` (导览), pages after the last to
    ``appendix_title`` (附录). Returns ``[]`` when no anchor page exists —
    Chinese books must never mis-report chapters here.
    """
    pages = layout.get("pdf_info", [])
    page_count = len(pages)
    # 用位置索引遍历 —— fixture/part-merge 的 page_idx 可能稀疏（跳号）.
    anchor_pos = [i for i, p in enumerate(pages) if _has_overview_anchor(p)]
    if not anchor_pos:
        return []

    # 判据 2 — Unit 序号提取 + 无号锚页补齐（页序缺口优先）.
    raw: list[tuple[int | None, int, str | None]] = []
    for pos in anchor_pos:
        page_idx = pages[pos]["page_idx"]
        # 前一页若是另一个 Unit 锚页，其标题属于上一单元 —— 不得提供序号.
        prev = pages[pos - 1] if pos > 0 and not _has_overview_anchor(pages[pos - 1]) else None
        no, name = _unit_info(pages[pos], prev)
        raw.append((no, page_idx, name))
    units = _assign_unit_numbers([(no, page_idx, name) for no, page_idx, name in raw])

    # 同序号多锚页（同 Unit 跨页）保留页序最早者；按序号排序 —— 扫描页序
    # 乱（Unit 3 在 Unit 1 前）仍按 1,2,3 输出（判据 3 的排序保证）。
    unique: dict[int, tuple[int, str]] = {}
    for no, page_idx, title in units:
        if no not in unique:
            unique[no] = (page_idx, title)
    unit_chapters = [
        Chapter(
            title=title,
            page_idx=page_idx,
            bbox=[],
            meta={"unit_no": no},
        )
        for no, (page_idx, title) in sorted(unique.items())
    ]

    # 判据 3 — 章界：首个 Unit 前归导览，末 Unit 后归附录.
    first_unit_page = min(page_idx for page_idx, _title in unique.values())
    last_unit_page = max(page_idx for page_idx, _title in unique.values())
    chapters: list[Chapter] = []
    if first_unit_page > 0:
        chapters.append(Chapter(title=overview_title, page_idx=0, bbox=[]))
    chapters.extend(unit_chapters)
    if last_unit_page + 1 < page_count:
        chapters.append(Chapter(title=appendix_title, page_idx=last_unit_page + 1, bbox=[]))
    return assign_page_ranges(chapters, page_count=page_count)
