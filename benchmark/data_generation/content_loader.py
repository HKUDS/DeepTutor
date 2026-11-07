#!/usr/bin/env python
"""
Content List Loader - Load and extract page content from KB content_list

Used for page-grounded gap generation: randomly select N pages and extract
text content for LLM-based gap generation and evaluator source alignment.
"""

import json
import logging
import random
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("benchmark.content_loader")


def load_content_list(kb_base_dir: str | Path, kb_name: str) -> list[dict] | None:
    """
    Load content list JSON for a knowledge base.

    Args:
        kb_base_dir: Base directory for knowledge bases
        kb_name: KB name (e.g. calc1)

    Returns:
        List of content items (type, text, page_idx, ...) or None if not found
    """
    base = Path(kb_base_dir)
    content_list_dir = base / kb_name / "content_list"
    if not content_list_dir.exists():
        logger.warning(f"Content list dir not found: {content_list_dir}")
        return None

    json_files = sorted(content_list_dir.glob("*.json"))
    if not json_files:
        logger.warning(f"No JSON files in {content_list_dir}")
        return None

    with open(json_files[0], encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list):
        logger.warning(f"Content list is not a list: {type(items)}")
        return None

    return items


def extract_page_content(
    content_items: list[dict],
    page_indices: list[int] | None = None,
) -> dict[int, str]:
    """
    Extract text content grouped by page_idx.

    Args:
        content_items: List of items from content_list (each has type, text?, page_idx?)
        page_indices: If provided, only extract these pages. If None, use all pages.

    Returns:
        Dict mapping page_idx -> concatenated text content
    """
    text_by_page: dict[int, list[str]] = defaultdict(list)

    for item in content_items:
        if item.get("type") != "text":
            continue
        text = item.get("text", "").strip()
        if not text:
            continue
        page_idx = item.get("page_idx", 0)
        if page_indices is not None and page_idx not in page_indices:
            continue
        text_by_page[page_idx].append(text)

    return {p: "\n".join(text_by_page[p]) for p in sorted(text_by_page.keys())}


def select_random_pages(
    content_items: list[dict],
    num_pages: int = 10,
    seed: int | None = None,
) -> list[int]:
    """
    Select N consecutive pages with random start position.

    Args:
        content_items: Content list items
        num_pages: Number of consecutive pages to select
        seed: Optional random seed for reproducibility

    Returns:
        List of consecutive page_idx values
    """
    all_pages = sorted(
        set(item["page_idx"] for item in content_items if "page_idx" in item)
    )
    if not all_pages:
        return []

    n = min(num_pages, len(all_pages))
    max_start = len(all_pages) - n
    if max_start < 0:
        return all_pages

    if seed is not None:
        rng = random.Random(seed)
        start = rng.randint(0, max_start)
    else:
        start = random.randint(0, max_start)

    return all_pages[start : start + n]


def load_page_content_for_profile(
    kb_base_dir: str | Path,
    kb_name: str,
    num_pages: int = 10,
    profile_id: str | None = None,
) -> tuple[dict[int, str], list[int]] | None:
    """
    Load content list, select N random pages, extract text.

    Args:
        kb_base_dir: KB base directory
        kb_name: KB name
        num_pages: Number of pages to select
        profile_id: Optional, used as seed for reproducible page selection per profile

    Returns:
        (page_content dict, selected_page_indices) or None if content_list not found
    """
    items = load_content_list(kb_base_dir, kb_name)
    if not items:
        return None

    seed = hash(profile_id) % (2**32) if profile_id else None
    selected = select_random_pages(items, num_pages=num_pages, seed=seed)
    page_content = extract_page_content(items, page_indices=selected)

    logger.info(
        f"  Loaded {len(page_content)} pages for {profile_id or kb_name}: "
        f"page_indices={selected}"
    )
    return page_content, selected
