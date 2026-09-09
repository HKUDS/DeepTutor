"""Productized canonical-KP-tree → chapters converter (P7).

The book manifest's ``metadata.canonical_kp_tree`` (written by the doc_intel
auto-cache and the inline canonicalize rebuild) already describes the whole
textbook as a titled tree. Until now turning that tree into importable
chapters was a manual script — which is why a student with a fully parsed
book still saw an empty ``/mastery`` list. ``chapters_from_kp_tree`` makes
that conversion a first-class service call, and
``POST /progress/{book_id}/import-from-kp-tree`` exposes it as the one-click
"start from your textbook" entry.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from deeptutor.book.storage import BookStorage, get_book_storage

#: A chapter node: ``第X章`` with Arabic or Chinese numerals.
_CHAPTER_TITLE = re.compile(r"^第[0-9零一二三四五六七八九十百千两]+章")

#: A chapter's knowledge-point ceiling. A chapter subtree longer than this
#: makes the mechanical module unwieldy (and the diagnostic unanswerable);
#: the tail is dropped rather than shipping an unusable module.
MAX_CHAPTER_KPS = 60


class ChapterImport(BaseModel):
    title: str
    knowledge_points: list[str] = []
    # Textbook-tree bridge: the tree node this chapter was derived from.
    # Optional so pre-bridge callers (name-only imports) keep working.
    struct_path: str = ""
    textbook_node_id: str = ""


def _bridge_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _node_title(node: dict[str, Any]) -> str:
    title = node.get("title")
    return title.strip() if isinstance(title, str) else ""


def _collect_kps(node: dict[str, Any], out: list[str]) -> None:
    """Flatten a chapter subtree's titles into ``out``, capped."""
    if len(out) >= MAX_CHAPTER_KPS:
        return
    title = _node_title(node)
    if title:
        out.append(title)
    for child in node.get("children") or []:
        if not isinstance(child, dict) or len(out) >= MAX_CHAPTER_KPS:
            continue
        _collect_kps(child, out)


def chapters_from_kp_tree(
    book_id: str, *, storage: BookStorage | None = None
) -> list[ChapterImport]:
    """Derive importable chapters from the book's cached canonical KP tree.

    Every ``第X章`` node becomes one chapter; the titles of its whole subtree
    (节/目 and deeper) are the chapter's knowledge points, and the chapter
    keeps its own ``struct_path``/``node_id`` as the textbook-tree bridge.
    Nodes that are not chapter headings are only containers — their children
    keep being searched, so a 单元→章 nesting still finds every chapter, and
    a chapter consumes its own subtree so nested chapters cannot double-count.

    Books without a cached tree (or without a single chapter heading in it)
    return ``[]`` — the caller decides whether that is an error or whether a
    finer-grained source (the 目级 mu modules) can serve instead.
    """
    tree = (storage or get_book_storage()).load_canonical_kp_tree(book_id)
    if not isinstance(tree, dict):
        return []

    chapters: list[ChapterImport] = []

    def walk(node: dict[str, Any]) -> None:
        title = _node_title(node)
        if title and _CHAPTER_TITLE.match(title):
            kps: list[str] = []
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _collect_kps(child, kps)
            chapters.append(
                ChapterImport(
                    title=title,
                    knowledge_points=kps,
                    struct_path=_bridge_str(node.get("struct_path")),
                    textbook_node_id=_bridge_str(node.get("node_id")),
                )
            )
            return  # the chapter consumes its subtree
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(tree)
    return chapters
