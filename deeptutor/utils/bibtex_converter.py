"""Convert BibTeX source into readable Markdown for retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re

_ENTRY_START_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_+.-]*)\s*([({])")
_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+:-]*")
_WHITESPACE_RE = re.compile(r"\s+")

_DELIMITERS = {"{": "}", "(": ")"}
_METADATA_ENTRY_TYPES = {"comment", "string", "preamble"}
_DISPLAY_FIELDS = (
    "author",
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
_TYPE_LABELS = {
    "article": "Journal Article",
    "book": "Book",
    "booklet": "Booklet",
    "conference": "Conference Paper",
    "inbook": "Book Chapter",
    "incollection": "Book Chapter",
    "inproceedings": "Conference Paper",
    "manual": "Manual",
    "mastersthesis": "Master's Thesis",
    "misc": "Other",
    "phdthesis": "PhD Thesis",
    "proceedings": "Proceedings",
    "techreport": "Technical Report",
    "unpublished": "Unpublished",
}


@dataclass(frozen=True, slots=True)
class _Entry:
    entry_type: str
    key: str
    fields: dict[str, str]


def _clean_value(value: str) -> str:
    cleaned = value.replace("{", "").replace("}", "")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _format_authors(value: str) -> str:
    names: list[str] = []
    for raw_name in _clean_value(value).split(" and "):
        name = raw_name.strip()
        if "," in name:
            last, first = (part.strip() for part in name.split(",", 1))
            name = f"{first} {last}".strip()
        if name:
            names.append(name)
    return ", ".join(names)


def _field_label(field: str) -> str:
    labels = {
        "booktitle": "Book Title",
        "doi": "DOI",
        "author": "Authors",
        "url": "URL",
    }
    return labels.get(field, field.capitalize())


def _format_entry(entry: _Entry, index: int) -> str:
    entry_type = _TYPE_LABELS.get(
        entry.entry_type, entry.entry_type.replace("_", " ").title() or "Reference"
    )
    title = entry.fields.get("title") or "Untitled"
    lines = [f"## {index}. {title}", "", f"**Type:** {entry_type}"]
    citation_key = entry.key.replace("`", "'") or "unknown"
    lines.append(f"**Citation key:** `{citation_key}`")

    for field in _DISPLAY_FIELDS:
        value = entry.fields.get(field, "")
        if not value:
            continue
        if field == "author":
            value = _format_authors(value)
        lines.append(f"**{_field_label(field)}:** {value}")
    lines.append("")
    return "\n".join(lines)


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _read_braced(text: str, index: int) -> tuple[str, int]:
    depth = 1
    start = index + 1
    index += 1
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    raise ValueError("unterminated braced BibTeX value")


def _read_quoted(text: str, index: int) -> tuple[str, int]:
    start = index + 1
    index += 1
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return text[start:index], index + 1
        index += 1
    raise ValueError("unterminated quoted BibTeX value")


def _read_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    index = 0
    while index < len(body):
        index = _skip_whitespace(body, index)
        if index >= len(body):
            break
        match = _IDENTIFIER_RE.match(body, index)
        if match is None:
            break
        name = match.group(0).lower()
        index = _skip_whitespace(body, match.end())
        if index >= len(body) or body[index] != "=":
            break
        index = _skip_whitespace(body, index + 1)

        parts: list[str] = []
        while index < len(body):
            char = body[index]
            if char == "{":
                value, index = _read_braced(body, index)
            elif char == '"':
                value, index = _read_quoted(body, index)
            else:
                end = index
                while end < len(body) and body[end] not in {"#", ",", "}", ")"}:
                    if body[end].isspace():
                        break
                    end += 1
                if end == index:
                    raise ValueError("empty BibTeX value")
                value = body[index:end]
                index = end
            parts.append(value.strip())
            index = _skip_whitespace(body, index)
            if index < len(body) and body[index] == "#":
                index = _skip_whitespace(body, index + 1)
                continue
            break

        fields[name] = _clean_value("".join(parts))
        index = _skip_whitespace(body, index)
        if index < len(body) and body[index] == ",":
            index += 1
        elif index < len(body):
            break
    return fields


def _scan_entry(text: str, match: re.Match[str]) -> tuple[_Entry | None, int] | None:
    entry_type = match.group(1).lower()
    opener = match.group(2)
    closer = _DELIMITERS[opener]
    index = match.end()
    brace_depth = 1 if opener == "{" else 0
    paren_depth = 1 if opener == "(" else 0
    quoted = False
    escaped = False

    while index < len(text):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")":
            paren_depth -= 1

        if opener == "{" and brace_depth == 0:
            body_end = index
            return _make_entry(entry_type, text, match.end(), body_end), index + 1
        if opener == "(" and paren_depth == 0 and brace_depth <= 0:
            body_end = index
            return _make_entry(entry_type, text, match.end(), body_end), index + 1
        if brace_depth < 0 or paren_depth < 0:
            return None
        index += 1
    return None


def _make_entry(entry_type: str, text: str, start: int, end: int) -> _Entry | None:
    body = text[start:end]
    separator = body.find(",")
    if separator < 0:
        return None
    key = body[:separator].strip()
    try:
        fields = _read_fields(body[separator + 1 :])
    except ValueError:
        return None
    return _Entry(entry_type=entry_type, key=key, fields=fields)


def _parse_entries(text: str) -> list[_Entry]:
    entries: list[_Entry] = []
    index = 0
    while index < len(text):
        match = _ENTRY_START_RE.search(text, index)
        if match is None:
            break
        if match.group(1).lower() in _METADATA_ENTRY_TYPES:
            scanned = _scan_entry(text, match)
            index = scanned[1] if scanned is not None else match.start() + 1
            continue
        scanned = _scan_entry(text, match)
        if scanned is None:
            index = match.start() + 1
            continue
        entry, index = scanned
        if entry is not None:
            entries.append(entry)
    return entries


def bibtex_to_markdown(text: str, source_name: str = "bibliography") -> str:
    """Return structured Markdown, or the input when no BibTeX entry exists."""
    entries = _parse_entries(text or "")
    if not entries:
        return text or ""

    parts = [
        f"# Bibliography: {source_name}",
        "",
        f"Total entries: {len(entries)}",
        "",
    ]
    parts.extend(_format_entry(entry, index) for index, entry in enumerate(entries, 1))
    return "\n".join(parts)


__all__ = ["bibtex_to_markdown"]
