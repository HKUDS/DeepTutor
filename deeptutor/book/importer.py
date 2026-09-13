"""Textbook import: convert a real table-of-contents into Book structures.

The generated-book flow invents chapter titles from KB summary chunks; for
textbook-canonical books the spine must come from the textbook's own TOC
(verified against the live sample in ``yuedu-docs/proposal-textbook-import.md``).
Everything here is deterministic — no LLM in the loop.
"""

from __future__ import annotations

from typing import Any

from .models import Chapter, ContentType, Spine

# A 200-chapter cap mirrors the parse pipeline's per-document page limit and
# keeps a mis-shaped TOC from exploding into thousands of page shells.
MAX_CHAPTERS = 200


class TocImportError(ValueError):
    """Raised when a TOC cannot be turned into a valid spine."""


def _flatten_toc(nodes: list[dict[str, Any]], *, chapters: list[Chapter]) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            raise TocImportError("each TOC node must be an object")
        title = str(node.get("title") or "").strip()
        if not title:
            raise TocImportError("every TOC node needs a non-empty title")
        if len(chapters) >= MAX_CHAPTERS:
            raise TocImportError(f"TOC exceeds the {MAX_CHAPTERS}-chapter budget")
        content_type_raw = str(node.get("content_type") or "theory").strip().lower()
        try:
            content_type = ContentType(content_type_raw)
        except ValueError:
            content_type = ContentType.THEORY
        chapters.append(
            Chapter(
                title=title,
                content_type=content_type,
                summary=str(node.get("summary") or ""),
                learning_objectives=[str(o) for o in node.get("learning_objectives") or []],
                order=len(chapters),
            )
        )
        children = node.get("children") or []
        if children:
            _flatten_toc(children, chapters=chapters)


def toc_to_spine(book_id: str, toc: list[dict[str, Any]]) -> Spine:
    """Flatten a recursive TOC into a flat :class:`Spine` chapter list.

    Chapter ids are generated fresh; ``page_ids`` stay empty because pages are
    created by ``confirm_spine`` (page shells) or the bulk pages-import
    endpoint, not by the TOC itself.
    """
    if not isinstance(toc, list) or not toc:
        raise TocImportError("toc must be a non-empty list")
    chapters: list[Chapter] = []
    _flatten_toc(toc, chapters=chapters)
    return Spine(book_id=book_id, chapters=chapters)


def layout_to_spine(book_id: str, layout: dict, *, title: str = "") -> Spine:
    """Rebuild the chapter tree straight from a MinerU ``layout.json``.

    Natively DT: the running-header criteria (textbook_struct.page_headers)
    detect chapter starts — including the printed page number — with no
    external tooling and no LLM in the loop.
    """
    from ..textbook_struct.chapter_rebuild import rebuild_with_fallback

    if not isinstance(layout, dict) or not layout.get("pdf_info"):
        raise TocImportError("layout must be a MinerU layout dict with pdf_info")
    # 页脚/页眉法 0 章 → 概述锚定法兜底（仅 en/英语书启用）。
    chapters = rebuild_with_fallback(layout, title=title)
    if not chapters:
        raise TocImportError("no chapter headers found in layout (running headers empty?)")
    return Spine(
        book_id=book_id,
        chapters=[
            Chapter(
                title=c.title,
                content_type=ContentType.THEORY,
                summary="",
                order=i,
                meta={"printed_page": c.meta.get("printed_page")},
            )
            for i, c in enumerate(chapters)
        ],
    )
