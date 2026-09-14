"""Figure backfill for canonicalized textbooks (P5).

MinerU's parse product carries every figure (``*_content_list.json`` image
items with ``img_path`` / ``img_caption`` / ``page_idx`` / ``bbox``), but the
verbatim book import keeps prose only — the book's ``assets/`` dir stays
empty and references like “如图1.1-3” point at nothing.

This module builds a **backfill plan**: which image files land on which book
page, then (on request) applies it by copying the files into the book's
assets dir and inserting a verbatim ``reading`` block carrying the markdown
image — same zero-LLM canon channel as the textbook import itself.

Matching strategy:

1. **Caption first** — a figure label referenced in a page's prose
   (“图1.1-3”) is matched against content_list image captions containing the
   same label, wherever that image physically sits.
2. **Page alignment** — images without captions (or labels without caption
   matches) fall back to page order: content_list ``page_idx`` N ↔ the book
   page titled ``页N+1``; pages without numeric titles use their position in
   the spine order instead. ``page_offset`` absorbs a printed↔numeric page
   skew for imports that were numbered by 印刷页 (the ``printed_page``
   precedent in ``textbook_struct``).

Everything is pure/deterministic; the CLI is dry-run unless ``--apply``::

    python -m deeptutor.book.figure_backfill <book_id> [--parse-dir DIR] [--apply]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
import shutil
from typing import Any

logger = logging.getLogger(__name__)

# Figure labels need at least one separator (“图1.1-3”, “图2-7”, “图1.2.3”);
# a bare “图1” is too generic to anchor on.
FIG_LABEL_RE = re.compile(r"图\s*(\d+(?:[.\-–—]\d+)+)")
PAGE_TITLE_NUM_RE = re.compile(r"页\s*(\d+)")

#: Directory inside the book root that receives copied figure files.
FIGURES_DIR = "figures"


@dataclass
class FigureSource:
    """One image item from a MinerU content_list."""

    page_idx: int  # 0-based pdf page index as recorded by the parser
    img_path: str  # original path as written (may be relative to the parse dir)
    caption: str = ""
    bbox: list[float] | None = None


@dataclass
class PlanImage:
    source: FigureSource
    reason: str  # "caption" | "page"
    filename: str  # name the file gets inside the book's figures/ dir


@dataclass
class PlanEntry:
    page_id: str
    page_title: str
    images: list[PlanImage] = field(default_factory=list)


@dataclass
class FigurePlan:
    book_id: str
    entries: list[PlanEntry] = field(default_factory=list)
    #: labels referenced by prose but with no caption match
    unmatched_labels: list[str] = field(default_factory=list)
    #: images no page claimed
    unplaced_images: list[FigureSource] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return sum(len(e.images) for e in self.entries)


# ── Parsing the content_list ────────────────────────────────────────────────


def collect_images(content_list: list[dict[str, Any]]) -> list[FigureSource]:
    """Extract image items (in reading order) from a MinerU content_list."""
    images: list[FigureSource] = []
    for item in content_list:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        img_path = item.get("img_path")
        if not isinstance(img_path, str) or not img_path:
            continue
        # MinerU emits both spellings across versions; prefer whichever exists.
        caption_parts = item.get("img_caption")
        if caption_parts is None:
            caption_parts = item.get("image_caption")
        caption = ""
        if isinstance(caption_parts, list):
            caption = "".join(str(p) for p in caption_parts if isinstance(p, str)).strip()
        bbox = item.get("bbox") if isinstance(item.get("bbox"), list) else None
        page_idx = item.get("page_idx")
        images.append(
            FigureSource(
                page_idx=int(page_idx) if isinstance(page_idx, (int, float)) else -1,
                img_path=img_path,
                caption=caption,
                bbox=bbox,
            )
        )
    return images


def load_content_lists(parse_dir: Path) -> tuple[list[dict[str, Any]], Path]:
    """Merge the parse product's content lists (skip ``_v2``), returning the
    merged items plus the dir relative ``img_path`` values resolve against."""
    parse_dir = Path(parse_dir)
    files = sorted(
        p for p in parse_dir.glob("*_content_list.json") if not p.name.endswith("_v2.json")
    )
    if not files:
        return [], parse_dir
    items: list[dict[str, Any]] = []
    # Part splits (大部头) each carry their own 0-based page_idx — renumber
    # into one sequence the same way the layout merge does.
    page_offset = 0
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("unreadable content_list: %s", path)
            continue
        if not isinstance(payload, list):
            continue
        max_idx = page_offset
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "image":
                item = {**item}
                idx = item.get("page_idx")
                if isinstance(idx, (int, float)):
                    item["page_idx"] = int(idx) + page_offset
                    max_idx = max(max_idx, item["page_idx"])
            items.append(item)
        page_offset = max_idx + 1
    return items, files[0].parent


# ── Matching ────────────────────────────────────────────────────────────────


def extract_fig_labels(text: str) -> list[str]:
    """Figure labels referenced by prose, deduplicated in reading order."""
    seen: set[str] = set()
    labels: list[str] = []
    for m in FIG_LABEL_RE.finditer(text):
        label = m.group(1)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _caption_label(source: FigureSource) -> str | None:
    m = FIG_LABEL_RE.search(source.caption)
    return m.group(1) if m else None


def _page_prose(page: Any) -> str:
    parts: list[str] = []
    for block in page.blocks:
        if block.type.value != "reading":
            continue
        body = block.params.get("body")
        if isinstance(body, str):
            parts.append(body)
    return "\n".join(parts)


def _unique_filename(filename: str, taken: set[str]) -> str:
    base = Path(filename).name or "figure"
    stem, suffix = Path(base).stem, Path(base).suffix or ".png"
    candidate = base
    i = 1
    while candidate in taken:
        candidate = f"{stem}_{i}{suffix}"
        i += 1
    taken.add(candidate)
    return candidate


def build_figure_plan(
    book_id: str,
    pages: list[Any],
    content_list: list[dict[str, Any]],
    *,
    page_offset: int = 0,
) -> FigurePlan:
    """Match content_list images onto book pages.

    ``pages`` must be in reader order (``storage.list_pages`` order works).
    ``page_offset`` shifts content_list page numbers when the book's 页N
    titles were numbered from 印刷页 rather than the pdf page index.
    """
    images = collect_images(content_list)
    label_to_image: dict[str, FigureSource] = {}
    for src in images:
        label = _caption_label(src)
        if label and label not in label_to_image:
            label_to_image[label] = src
    by_page: dict[int, list[FigureSource]] = {}
    for src in images:
        by_page.setdefault(src.page_idx, []).append(src)

    used: set[int] = set()  # id() of claimed FigureSources
    taken_names: set[str] = set()
    plan = FigurePlan(book_id=book_id)
    # Spine-order position for pages without 页N titles.
    for position, page in enumerate(pages):
        numeric = PAGE_TITLE_NUM_RE.search(page.title or "")
        aligned_idx = (int(numeric.group(1)) - 1 + page_offset) if numeric else position
        entry = PlanEntry(page_id=page.id, page_title=page.title or "")

        # 1) caption match wins, regardless of where the image physically sits
        for label in extract_fig_labels(_page_prose(page)):
            src = label_to_image.get(label)
            if src is None:
                plan.unmatched_labels.append(label)
                continue
            if id(src) in used:
                continue
            used.add(id(src))
            entry.images.append(
                PlanImage(
                    source=src,
                    reason="caption",
                    filename=_unique_filename(Path(src.img_path).name, taken_names),
                )
            )

        # 2) page-order fallback for the remaining images on this pdf page
        for src in by_page.get(aligned_idx, []):
            if id(src) in used:
                continue
            used.add(id(src))
            entry.images.append(
                PlanImage(
                    source=src,
                    reason="page",
                    filename=_unique_filename(Path(src.img_path).name, taken_names),
                )
            )

        if entry.images:
            plan.entries.append(entry)

    plan.unplaced_images = [src for src in images if id(src) not in used]
    return plan


def plan_from_parse_dir(
    book_id: str, pages: list[Any], parse_dir: Path, *, page_offset: int = 0
) -> FigurePlan:
    items, _ = load_content_lists(parse_dir)
    return build_figure_plan(book_id, pages, items, page_offset=page_offset)


# ── Applying the plan ───────────────────────────────────────────────────────


def _resolve_source_file(source: FigureSource, content_dir: Path) -> Path | None:
    """Locate the image file: absolute, content-dir-relative, or images/."""
    candidates = [Path(source.img_path)]
    if not Path(source.img_path).is_absolute():
        candidates.append(content_dir / source.img_path)
        candidates.append(content_dir / "images" / Path(source.img_path).name)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


async def _insert_reading_block(engine: Any, book_id: str, page_id: str, body: str) -> Any:
    from .models import BlockType

    return await engine.insert_block(
        book_id=book_id,
        page_id=page_id,
        block_type=BlockType.READING,
        params={"body": body, "variant": "prose", "source_label": "figure-backfill"},
        compile_now=False,
    )


async def apply_plan(
    engine: Any,
    book_id: str,
    plan: FigurePlan,
    *,
    content_dir: Path,
    storage: Any | None = None,
) -> dict[str, Any]:
    """Copy each planned image into the book's assets dir and insert a
    verbatim reading block referencing it.

    ``engine`` is the BookEngine (its storage is used unless ``storage`` is
    given). Returns a summary; never executes on a dry-run plan — callers
    decide that.
    """
    store = storage if storage is not None else engine.storage
    figures_dir = store.ensure_book_root(book_id) / "assets" / FIGURES_DIR
    figures_dir.mkdir(parents=True, exist_ok=True)

    inserted_blocks = 0
    copied_files: list[str] = []
    for entry in plan.entries:
        lines: list[str] = []
        for image in entry.images:
            src_file = _resolve_source_file(image.source, content_dir)
            if src_file is None:
                logger.warning("figure backfill: source file missing for %s", image.source.img_path)
                continue
            dest = figures_dir / image.filename
            if src_file.resolve() != dest.resolve():
                shutil.copyfile(src_file, dest)
            rel = f"{FIGURES_DIR}/{image.filename}"
            copied_files.append(rel)
            caption = image.source.caption or f"图{Path(image.filename).stem}"
            lines.append(f"![{caption}](/api/books/{book_id}/assets/{rel})")
        if not lines:
            continue
        block = await _insert_reading_block(engine, book_id, entry.page_id, "\n\n".join(lines))
        if block is not None:
            inserted_blocks += 1
    return {
        "book_id": book_id,
        "pages": len(plan.entries),
        "blocks_inserted": inserted_blocks,
        "images_copied": len(copied_files),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def _print_plan(plan: FigurePlan) -> None:
    print(f"book {plan.book_id}: {plan.image_count} images planned")
    for entry in plan.entries:
        names = ", ".join(f"{i.filename}({i.reason})" for i in entry.images)
        print(f"  {entry.page_title} [{entry.page_id}]: {names}")
    if plan.unmatched_labels:
        print(f"  unmatched labels: {', '.join(plan.unmatched_labels)}")
    if plan.unplaced_images:
        print(f"  unplaced images: {len(plan.unplaced_images)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m deeptutor.book.figure_backfill",
        description="Plan (and optionally apply) textbook figure backfill",
    )
    parser.add_argument("book_id")
    parser.add_argument(
        "--parse-dir", help="MinerU parse product dir (defaults to book.metadata[parse_dir])"
    )
    parser.add_argument(
        "--page-offset", type=int, default=0, help="shift content_list page numbers (印刷页偏移)"
    )
    parser.add_argument("--apply", action="store_true", help="execute the plan (default: dry-run)")
    args = parser.parse_args(argv)

    from .storage import get_book_storage

    storage = get_book_storage()
    book = storage.load_book(args.book_id)
    if book is None:
        raise ValueError(f"book not found: {args.book_id}")
    parse_dir = args.parse_dir or (book.metadata or {}).get("parse_dir")
    if not parse_dir:
        parser.error("no parse dir: pass --parse-dir or import with metadata[parse_dir]")

    pages = storage.list_pages(args.book_id)
    plan = plan_from_parse_dir(args.book_id, pages, Path(parse_dir), page_offset=args.page_offset)
    _print_plan(plan)

    if not args.apply:
        return 0

    import asyncio

    from .engine import BookEngine

    engine = BookEngine(storage=storage)
    items, content_dir = load_content_lists(Path(parse_dir))
    full_plan = build_figure_plan(args.book_id, pages, items, page_offset=args.page_offset)
    summary = asyncio.run(
        apply_plan(engine, args.book_id, full_plan, content_dir=content_dir, storage=storage)
    )
    print(
        f"applied: blocks_inserted={summary['blocks_inserted']} "
        f"images_copied={summary['images_copied']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
