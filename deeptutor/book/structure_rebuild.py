"""书结构重组 (P6): 页标题语义化 + 节级目录写回 spine.

教材书 canonicalize 之后 spine.chapters 只有章标题、children 全空，阅读侧栏
按 PDF 物理页平铺（"页8/页9/…/页146"）。本模块把两层数据补齐：

P6-a 轻量：从每页 prose 首部提取节标题模式（``1.1 空间向量及其加减运算`` /
``第一章 空间向量与立体几何``），生成 ``Page.display_title``（同节多页追加
"（1/3）"序号）；无匹配保留原"页N"。

P6-b 节级聚合：用 ``manifest.metadata.canonical_kp_tree`` 的节节点（title
形如 ``1.1 …``）与页 display_title 匹配，建 节→页[] 归属写回
``spine.chapters[].children``；无节匹配的页保持章直挂。

存量书入口::

    python -m deeptutor.book.structure_rebuild <book_id> [--dry-run]

dry-run 只打印前后对照，不落盘。全程确定性，无 LLM。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import logging
import re
from typing import Any

from .models import Page, Spine

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 标题提取（P6-a）
# ─────────────────────────────────────────────────────────────────────────────

# 节标题: "1.1 空间向量及其加减运算"。任务书模式 ^\d+\.\d+\s*[^\d，。]{4,30} —
# 节号至少两级，标题体 4~30 个字符、不含数字/逗号/句号（页码残片与句子会被挡掉）。
_SECTION_TITLE_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\s*[^\d，。]{4,30}\s*$")

# 章/单元标题: "第一章 空间向量与立体几何" / "第3章" / "第二单元"。
_CHAPTER_TITLE_RE = re.compile(
    r"^\s*第\s*([0-9０-９一二三四五六七八九十百零两]+)\s*(单元|[章课讲篇])\s*[:：、.]?\s*(\S[^\d，。]{0,29})?\s*$"
)

#: prose 首部最多扫描的行数 — 标题在页首；再往下就是正文句子了。
_TITLE_SCAN_LINES = 6

# 同节多页的序号后缀: "1.1 空间向量及其加减运算（1/3）"
_MULTI_SUFFIX_RE = re.compile(r"（\d+/\d+）\s*$")


def extract_section_title(text: str) -> str | None:
    """Extract a section/chapter title from the head of a page's prose.

    Returns the cleaned title (节号/章号 + 节名, whitespace collapsed), or
    ``None`` when no head line matches either pattern.
    """
    for raw in (text or "").splitlines()[:_TITLE_SCAN_LINES]:
        line = raw.strip()
        if not line or len(line) > 40:
            continue
        match = _SECTION_TITLE_RE.match(line)
        if match:
            title = line
            # Collapse the whitespace run between 节号 and 节名.
            return re.sub(r"\s+", " ", title).strip()
        chapter = _CHAPTER_TITLE_RE.match(line)
        if chapter:
            num, unit, rest = chapter.groups()
            rest = (rest or "").strip()
            return f"第{num}{unit} {rest}".strip()
    return None


def page_prose(page: Page) -> str:
    """The page's leading prose text: the first block that carries a body.

    Textbook pages are verbatim reading blocks (``params.body``); generated
    prose blocks use the same slot, so this covers both without caring about
    the exact block type.
    """
    for block in page.blocks:
        body = (block.params or {}).get("body") or (block.payload or {}).get("body")
        if isinstance(body, str) and body.strip():
            return body
    return ""


def normalize_title(title: str) -> str:
    """Match key for title comparison: drop 序号后缀 and all whitespace."""
    stripped = _MULTI_SUFFIX_RE.sub("", (title or "").strip())
    return re.sub(r"\s+", "", stripped)


def assign_display_titles(pages: list[Page]) -> dict[str, str]:
    """Semantic display titles for each page id (P6-a).

    Pages whose prose opens with a 节/章标题 pattern get that title; the same
    title appearing on several consecutive pages gets a "（i/n）" 序号 — a
    section spanning 3 physical pages reads "1.1 空间向量及其加减运算（2/3）".
    Pages without a match keep their "页N" title (empty display title).
    """
    extracted: dict[str, str] = {}
    counts: dict[str, int] = {}
    for page in pages:
        title = extract_section_title(page_prose(page))
        if title is None:
            continue
        extracted[page.id] = title
        key = normalize_title(title)
        counts[key] = counts.get(key, 0) + 1

    seen: dict[str, int] = {}
    result: dict[str, str] = {}
    for page in pages:
        title = extracted.get(page.id)
        if title is None:
            continue
        key = normalize_title(title)
        if counts[key] > 1:
            seen[key] = seen.get(key, 0) + 1
            title = f"{title}（{seen[key]}/{counts[key]}）"
        result[page.id] = title
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 页 → 节归属（P6-b）
# ─────────────────────────────────────────────────────────────────────────────


def collect_section_nodes(tree: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The canonical KP tree's 节节点 (titles like "1.1 …"), in tree order.

    Only numbered-section nodes count — 章 nodes never take pages directly
    and unnumbered leaves (导语/章末小结) have nothing to match against.
    """
    nodes: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        title = str(node.get("title") or "").strip()
        if title and _SECTION_TITLE_RE.match(title):
            nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    if isinstance(tree, dict):
        walk(tree)
    return nodes


@dataclass
class StructurePlan:
    """The rebuild's outcome, before anything is persisted."""

    #: page_id → semantic display title ("1.1 空间向量及其加减运算（1/3）")
    display_titles: dict[str, str] = field(default_factory=dict)
    #: chapter_id → spine children 写回（节层: 节标题 + 节下页 id）
    chapter_children: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: 节标题 → 页数（对照打印用）
    section_page_counts: dict[str, int] = field(default_factory=dict)


def build_structure_plan(
    spine: Spine, pages: list[Page], tree: dict[str, Any] | None
) -> StructurePlan:
    """Compute P6-a display titles and P6-b 节→页 归属 without persisting.

    Unmatched pages keep 章直挂 (they stay in ``chapter.page_ids``); a 节 lands
    under the chapter its pages already belong to, ordered by the tree.
    """
    plan = StructurePlan()
    plan.display_titles = assign_display_titles(pages)

    sections = collect_section_nodes(tree)
    if not sections:
        return plan

    by_normalized_title = {normalize_title(node["title"]): node for node in sections}
    matched: dict[str, str] = {}  # page_id → normalized 节 title
    for page in pages:
        display = plan.display_titles.get(page.id)
        if not display:
            continue
        key = normalize_title(display)
        if key in by_normalized_title:
            matched[page.id] = key

    if not matched:
        return plan

    # 节 → 页（保持页序）; 章 → 节（树序优先，章归属跟着页走）。
    section_pages: dict[str, list[str]] = {}
    for page in pages:
        key = matched.get(page.id)
        if key is not None:
            section_pages.setdefault(key, []).append(page.id)

    chapter_of_page = {page.id: page.chapter_id for page in pages}
    seen_sections: set[str] = set()
    for page in pages:  # chapter grouping follows page order
        key = matched.get(page.id)
        if key is None or key in seen_sections:
            continue
        seen_sections.add(key)
        chapter_id = chapter_of_page.get(section_pages[key][0], "")
        if not chapter_id:
            continue
        children = plan.chapter_children.setdefault(chapter_id, [])
        children.append(
            {"title": by_normalized_title[key]["title"], "page_ids": section_pages[key]}
        )

    for key, page_ids in section_pages.items():
        plan.section_page_counts[key] = len(page_ids)
    return plan


def apply_structure_plan(
    storage: Any,
    spine: Spine,
    pages: list[Page],
    plan: StructurePlan,
) -> int:
    """Persist the plan: display titles onto pages, 节层 onto the spine.

    Bumps the spine version (readers re-fetch). Returns the number of pages
    whose title actually changed.
    """
    changed = 0
    for page in pages:
        display = plan.display_titles.get(page.id)
        if display is not None and page.display_title != display:
            page.display_title = display
            storage.save_page(page)
            changed += 1

    touched_children = False
    for chapter in spine.chapters:
        children = plan.chapter_children.get(chapter.id)
        if children and children != chapter.children:
            chapter.children = children
            touched_children = True
    if touched_children:
        spine.version += 1
        storage.save_spine(spine)
    return changed


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────


def _print_diff(spine: Spine, pages: list[Page], plan: StructurePlan) -> None:
    titles_by_id = {page.id: page.title for page in pages}
    print(f"book {spine.book_id}: {len(pages)} pages, {len(spine.chapters)} chapters")
    if not plan.display_titles and not plan.chapter_children:
        print("  (no structure to apply — no 节标题 matched, spine unchanged)")
        return

    print("-- 页标题 (before → after)")
    for page in pages:
        display = plan.display_titles.get(page.id)
        if display:
            print(f"  {page.title} → {display}")
    unmatched = [p for p in pages if p.id not in plan.display_titles]
    if unmatched:
        names = "、".join(titles_by_id[p.id] for p in unmatched[:5])
        more = f" … 共 {len(unmatched)} 页" if len(unmatched) > 5 else ""
        print(f"  无匹配（保留页N）: {names}{more}")

    if plan.chapter_children:
        print("-- 节级归属 (spine.chapters[].children)")
        for chapter in spine.chapters:
            children = plan.chapter_children.get(chapter.id)
            if not children:
                continue
            print(f"  {chapter.title}")
            for child in children:
                count = plan.section_page_counts.get(normalize_title(child["title"]), 0)
                print(f"    {child['title']}  ←{count} 页")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m deeptutor.book.structure_rebuild",
        description="对存量书跑 P6 结构重组：页标题语义化 + 节级目录写回 spine.",
    )
    parser.add_argument("book_id", help="目标书 id，如 bk_7a519f7e6e")
    parser.add_argument("--dry-run", action="store_true", help="只打印前后对照，不写回 spine/页")
    args = parser.parse_args(argv)

    from .storage import get_book_storage

    storage = get_book_storage()
    spine = storage.load_spine(args.book_id)
    if spine is None:
        parser.error(f"no spine for book {args.book_id}")
    pages = storage.list_pages(args.book_id)
    tree = storage.load_canonical_kp_tree(args.book_id)
    if tree is None:
        logger.warning("no canonical KP tree cached for %s — 节级归属将跳过", args.book_id)

    plan = build_structure_plan(spine, pages, tree)
    _print_diff(spine, pages, plan)

    if args.dry_run:
        print("(dry-run — nothing written)")
        return 0

    changed = apply_structure_plan(storage, spine, pages, plan)
    print(f"written: {changed} page titles, {len(plan.chapter_children)} chapters with 节层")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
