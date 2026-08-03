"""Utility functions shared by the partner channel layer."""

from datetime import datetime
from pathlib import Path
import re


def detect_image_mime(data: bytes) -> str | None:
    """Detect image MIME type from magic bytes, ignoring file extension."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """Current ISO timestamp."""
    return datetime.now().isoformat()


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_filename(name: str) -> str:
    """Replace unsafe path / control characters; ``.`` / ``..`` become empty."""
    cleaned = _CONTROL_CHARS.sub("", _UNSAFE_CHARS.sub("_", name or "")).strip().strip(".")
    return cleaned


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    # Non-positive max_len cannot advance the cut pointer; return unsplit.
    if max_len <= 0:
        return [content]
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def split_markdown_table_row(line: str) -> list[str]:
    """Split one Markdown pipe-table row into stripped cells.

    Strips exactly one leading and one trailing pipe so leading/trailing empty
    cells (``|| a |`` / ``| a ||``) survive — ``str.strip("|")`` would collapse
    them and shift every column.
    """
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def is_markdown_table_separator_row(cells: list[str]) -> bool:
    """True if *cells* look like a markdown table separator row.

    An all-empty row is not a separator (`all([])` would otherwise be True).
    """
    return bool(any(c for c in cells)) and all(re.match(r"^:?-+:?$", c) for c in cells if c)


def convert_markdown_table_to_labeled_rows(table_text: str) -> str:
    """Convert a Markdown pipe table to labeled rows (for Slack-style text).

    Empty cells are kept so blank columns are not dropped.
    """
    lines = [ln.strip() for ln in table_text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return table_text
    headers = split_markdown_table_row(lines[0])
    start = 2 if is_markdown_table_separator_row(split_markdown_table_row(lines[1])) else 1
    rows: list[str] = []
    for line in lines[start:]:
        cells = split_markdown_table_row(line)
        cells = (cells + [""] * len(headers))[: len(headers)]
        parts = [f"**{headers[i]}**: {cells[i]}" for i in range(len(headers))]
        if parts:
            rows.append(" · ".join(parts))
    return "\n".join(rows)
