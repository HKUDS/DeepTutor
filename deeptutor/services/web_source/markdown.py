"""Markdown cleanup shared by web-source persistence and reading ingestion."""

from __future__ import annotations

import re

_LEADING_SOURCE_COMMENT = re.compile(
    r"^<!--\s*source:\s*https?://[^>\r\n]+?-->\s*$",
    re.IGNORECASE,
)


def strip_leading_snapshot_provenance(markdown: str) -> str:
    """Remove only crawler provenance comments from a snapshot's preamble."""
    lines = markdown.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if not _LEADING_SOURCE_COMMENT.fullmatch(stripped):
            break
        index += 1
    return "".join(lines[index:]).lstrip("\r\n")


__all__ = ["strip_leading_snapshot_provenance"]
