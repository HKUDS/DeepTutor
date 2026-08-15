"""Build and merge navigation trees for web-source KBs.

Two responsibilities:
  1. Convert a flat list of crawled sidebar links into a nested node tree.
  2. Merge parallel EN/ZH navigation trees into one English-primary tree
     with ZH titles and page-class annotations.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.web_source.pairing import strip_lang_prefix_from_path

logger = logging.getLogger(__name__)


# -- flat-to-tree conversion -------------------------------------------


def flat_to_tree(
    links: list[dict],
    url_to_file: dict[str, str],
) -> list[dict]:
    """Convert a flat list of navigation links into a nested tree.

    Uses the ``depth`` field to determine nesting.  Links at depth N
    become children of the most recent link at depth N-1.
    """
    result: list[dict] = []
    stack: list[tuple[int, dict]] = []
    counter = 0

    for link in links:
        depth = link.get("depth", 0)
        title = link.get("title", "Untitled")
        url = link.get("url", "")
        file_path = url_to_file.get(url, "")

        node: dict[str, Any] = {
            "id": f"nav-{counter}",
            "title": title,
            "url": url,
            "file_path": file_path,
            "children": [],
        }
        counter += 1

        while stack and stack[-1][0] >= depth:
            stack.pop()

        if stack:
            stack[-1][1]["children"].append(node)
        else:
            result.append(node)

        stack.append((depth, node))

    return result


def build_navigation_manifest(
    nav_links: list[dict],
    nav_kind: str,
    page_urls: dict[str, str],
) -> dict:
    """Build a serializable navigation manifest from crawl output.

    Returns ``{"kind": str, "nodes": [...]}``.
    """
    if not nav_links:
        return {"kind": "", "nodes": []}

    url_to_file: dict[str, str] = {}
    for fname, url in page_urls.items():
        url_to_file[url] = fname

    nodes = flat_to_tree(nav_links, url_to_file)
    return {"kind": nav_kind or "inferred", "nodes": nodes}


# -- bilingual nav merge -----------------------------------------------


def merge_navigation(
    en_nav: dict,
    zh_nav: dict,
    zh_lang_prefix: str,
    pair_key: str,
) -> dict:
    """Merge EN and ZH navigation trees into one English-primary tree.

    Each EN node gets a ``title_zh`` from the matching ZH node, plus
    ``file_path_zh``, ``page_class``, and ``pair_key``.
    """
    en_nodes = en_nav.get("nodes", [])
    zh_nodes = zh_nav.get("nodes", [])

    zh_by_base: dict[str, dict] = {}
    _index_zh_nodes(zh_nodes, zh_lang_prefix, zh_by_base)

    merged_kind = en_nav.get("kind", "inferred")
    if zh_nav.get("kind") == "original":
        merged_kind = "original"

    merged_nodes = [_merge_node(n, zh_by_base, pair_key) for n in en_nodes]
    return {"kind": merged_kind, "nodes": merged_nodes}


def _index_zh_nodes(
    nodes: list[dict],
    zh_lang_prefix: str,
    out: dict[str, dict],
) -> None:
    """Index ZH navigation nodes by their base (stripped) file path."""
    for node in nodes:
        fp = node.get("file_path", "")
        if fp:
            base = strip_lang_prefix_from_path(fp, zh_lang_prefix)
            out[base] = node
        _index_zh_nodes(node.get("children", []), zh_lang_prefix, out)


def _merge_node(
    en_node: dict,
    zh_by_base: dict[str, dict],
    pair_key: str,
) -> dict:
    """Merge one EN node with its ZH counterpart."""
    en_fp = en_node.get("file_path", "")
    zh_node = zh_by_base.get(en_fp)

    page_class = "bilingual"
    if en_fp and not zh_node:
        page_class = "en_only"
    elif not en_fp and zh_node:
        page_class = "zh_only"
    elif not en_fp:
        page_class = ""

    return {
        "id": en_node.get("id", ""),
        "title": en_node.get("title", ""),
        "title_zh": zh_node.get("title", "") if zh_node else "",
        "url": en_node.get("url", ""),
        "file_path": en_fp,
        "file_path_zh": zh_node.get("file_path", "") if zh_node else "",
        "page_class": page_class,
        "pair_key": pair_key,
        "children": [_merge_node(c, zh_by_base, pair_key) for c in en_node.get("children", [])],
    }
