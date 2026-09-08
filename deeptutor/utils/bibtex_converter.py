"""Lightweight BibTeX-to-Markdown converter for KB ingestion.

Extracts structured fields (title, author, year, journal, doi, abstract)
from BibTeX entries into readable Markdown so retrieval quality matches
plain-text documents. Handles common entry types (article, inproceedings,
book, phdthesis, misc) without external dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

_ENTRY_RE = re.compile(
    r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.*?)\n\}",
    re.DOTALL | re.IGNORECASE,
)
_FIELD_RE = re.compile(
    r"(\w+)\s*=\s*(\{.*?\}|\".*?\"|\S+)",
    re.DOTALL,
)
_BRACE_RE = re.compile(r"[{}]")
_WHITESPACE_RE = re.compile(r"\s+")

# Fields worth surfacing, in display order.
_DISPLAY_FIELDS = (
    "title",
    "author",
    "editor",
    "year",
    "journal",
    "booktitle",
    "publisher",
    "doi",
    "url",
    "abstract",
    "keywords",
    "note",
)

# Acceptable BibTeX entry type aliases.
_TYPE_ALIASES = {
    "inproceedings": "Conference Paper",
    "article": "Journal Article",
    "book": "Book",
    "incollection": "Book Chapter",
    "phdthesis": "PhD Thesis",
    "mastersthesis": "Master's Thesis",
    "techreport": "Technical Report",
    "misc": "Other",
    "unpublished": "Unpublished",
}


def _clean_value(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = _BRACE_RE.sub("", stripped[1:-1])
    elif stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped


def _parse_entries(text: str) -> list[dict[str, str]]:
    """Parse BibTeX source text into a list of field dicts."""
    entries: list[dict[str, str]] = []
    for match in _ENTRY_RE.finditer(text):
        entry_type = match.group(1).lower()
        entry_key = match.group(2)
        body = match.group(3)
        fields: dict[str, str] = {"_type": entry_type, "_key": entry_key}
        for fm in _FIELD_RE.finditer(body):
            key = fm.group(1).lower()
            fields[key] = _clean_value(fm.group(2))
        entries.append(fields)
    return entries


def _format_entry(entry: dict[str, str], index: int) -> str:
    entry_type = _TYPE_ALIASES.get(entry.get("_type", ""), entry.get("_type", "Reference").replace("_", " ").title())
    title = entry.get("title", "Untitled")
    lines = [f"## {index}. {title}", ""]
    lines.append(f"**Type:** {entry_type}")
    lines.append(f"**Citation key:** `{entry.get('_key', 'unknown')}`")
    for field in _DISPLAY_FIELDS:
        value = entry.get(field, "").strip()
        if not value:
            continue
        if field == "abstract":
            lines.append(f"**Abstract:** {value}")
        elif field == "url":
            lines.append(f"**URL:** {value}")
        else:
            lines.append(f"**{field.capitalize()}:** {value}")
    lines.append("")
    return "\n".join(lines)


def bibtex_to_markdown(text: str, source_name: str = "bibliography") -> str:
    """Convert raw BibTeX text into structured Markdown for indexing."""
    entries = _parse_entries(text)
    if not entries:
        return text
    parts = [f"# Bibliography: {source_name}", "", f"Total entries: {len(entries)}", ""]
    for i, entry in enumerate(entries, 1):
        parts.append(_format_entry(entry, i))
    return "\n".join(parts)


def bibtex_file_to_markdown(path: Path) -> str:
    """Read a .bib file and return structured Markdown."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return bibtex_to_markdown(text, source_name=path.stem)


__all__ = [
    "bibtex_file_to_markdown",
    "bibtex_to_markdown",
]
