"""Shared result shaping for literal conversation-history search."""

from __future__ import annotations

import re

MAX_SEARCH_QUERY_CHARS = 200
MAX_SEARCH_EXCERPT_CHARS = 320


def normalize_search_query(value: str) -> str:
    """Trim and bound a user-entered literal history query."""
    return str(value or "").strip()[:MAX_SEARCH_QUERY_CHARS]


def bounded_search_excerpt(content: str, query: str) -> str:
    """Return a short plain-text window around the first literal match."""
    text = str(content or "").strip()
    if not text:
        return ""
    match = re.search(re.escape(query), text, flags=re.IGNORECASE) if query else None
    if match is None:
        return text[:MAX_SEARCH_EXCERPT_CHARS]

    context_before = 96
    start = max(0, match.start() - context_before)
    end = min(len(text), start + MAX_SEARCH_EXCERPT_CHARS)
    if end - start < MAX_SEARCH_EXCERPT_CHARS:
        start = max(0, end - MAX_SEARCH_EXCERPT_CHARS)
    excerpt = text[start:end]
    if start:
        excerpt = f"…{excerpt}"
    if end < len(text):
        excerpt = f"{excerpt}…"
    if len(excerpt) > MAX_SEARCH_EXCERPT_CHARS:
        excerpt = f"{excerpt[: MAX_SEARCH_EXCERPT_CHARS - 1]}…"
    return excerpt


__all__ = [
    "MAX_SEARCH_EXCERPT_CHARS",
    "MAX_SEARCH_QUERY_CHARS",
    "bounded_search_excerpt",
    "normalize_search_query",
]
