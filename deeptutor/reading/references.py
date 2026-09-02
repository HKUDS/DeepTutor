"""Stable, revision-bound reading-unit references for ordinary chat turns.

The browser sends only material_id, content revision, and numeric locators.
Text, titles and source labels are always re-resolved from the current user's
ReadingStore at turn start. This keeps a persisted chat reference small,
prevents a client from smuggling arbitrary text through a trusted source field,
and makes deleted materials or unknown revisions fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from deeptutor.reading.store import MAX_READ_CHARS, ReadingStore

MAX_READING_REFERENCE_MATERIALS = 8
MAX_READING_REFERENCE_UNITS = 24
_MATERIAL_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")


@dataclass(frozen=True, slots=True)
class ResolvedReadingSource:
    """One source-index row resolved from a stored reading unit."""

    source_id: str
    name: str
    full_text: str


def normalize_reading_references(value: Any) -> list[dict[str, Any]]:
    """Return a bounded, deduplicated wire representation.

    Malformed rows are ignored rather than partially trusted. Repeated rows for
    the same material are merged in first-seen order.
    """

    if not isinstance(value, list):
        return []

    by_reference: dict[tuple[str, int], list[int]] = {}
    material_ids: set[str] = set()
    total = 0
    for raw in value:
        if not isinstance(raw, dict):
            continue
        material_id = str(raw.get("material_id") or "").strip().lower()
        if not _MATERIAL_ID_RE.fullmatch(material_id):
            continue
        revision = _positive_integer(raw.get("revision"))
        if revision is None:
            continue
        locators = raw.get("locators")
        if not isinstance(locators, list):
            continue
        key = (material_id, revision)
        target = by_reference.get(key)
        if target is None and (
            material_id not in material_ids and len(material_ids) >= MAX_READING_REFERENCE_MATERIALS
        ):
            continue
        for candidate in locators:
            locator = _positive_integer(candidate)
            if locator is None or (target is not None and locator in target):
                continue
            if total >= MAX_READING_REFERENCE_UNITS:
                break
            if target is None:
                target = []
                by_reference[key] = target
                material_ids.add(material_id)
            target.append(locator)
            total += 1

    return [
        {"material_id": material_id, "revision": revision, "locators": locators}
        for (material_id, revision), locators in by_reference.items()
        if locators
    ]


def resolve_reading_sources(
    value: Any,
    *,
    store: ReadingStore | None = None,
) -> list[ResolvedReadingSource]:
    """Resolve canonical references against the active user's reading store."""

    active_store = store or ReadingStore()
    resolved: list[ResolvedReadingSource] = []
    for reference in normalize_reading_references(value):
        material_id = reference["material_id"]
        revision = reference["revision"]
        try:
            current_manifest = active_store.manifest(material_id)
            if revision == current_manifest.revision:
                manifest = current_manifest
                outline = active_store.outline(material_id)
                unit_refs = active_store.unit_references(material_id)
                read_unit = active_store.unit_text
            else:
                manifest = next(
                    row for row in active_store.revisions(material_id) if row.revision == revision
                )
                outline = []
                unit_refs = []
                read_unit = lambda material_id, locator: active_store.revision_unit_text(  # noqa: E731
                    material_id, revision, locator
                )
        except Exception:
            # Missing, deleted, corrupt, or unknown revisions are not sources.
            continue

        headings: dict[int, str] = {}
        for row in outline:
            title = row.title.strip()
            if title:
                headings.setdefault(row.locator, title)
        native_titles = {row.locator: row.title.strip() for row in unit_refs if row.title.strip()}
        material_title = (manifest.title or manifest.filename or material_id).strip()

        for locator in reference["locators"]:
            if not 1 <= locator <= manifest.unit_count:
                continue
            try:
                body = read_unit(material_id, locator).strip()
            except Exception:
                continue
            if not body:
                continue
            heading = headings.get(locator) or native_titles.get(locator) or ""
            unit_label = f"{manifest.unit.capitalize()} {locator}"
            source_name = f"{material_title} — {unit_label}"
            if heading and heading.casefold() not in source_name.casefold():
                source_name += f": {heading}"
            if len(body) > MAX_READ_CHARS:
                body = (
                    body[:MAX_READ_CHARS].rstrip()
                    + f"\n… [reading unit truncated at {MAX_READ_CHARS:,} characters]"
                )
            header = (
                f"# Reading source: {material_title}\n"
                f"Material ID: {material_id}\n"
                f"Content revision: {revision}\n"
                f"Source file: {manifest.filename}\n"
                f"{unit_label}{f': {heading}' if heading else ''}"
            )
            resolved.append(
                ResolvedReadingSource(
                    source_id=f"rd-{material_id}-r{revision}-{locator}",
                    name=source_name,
                    full_text=f"{header}\n\n{body}",
                )
            )
    return resolved


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


__all__ = [
    "MAX_READING_REFERENCE_MATERIALS",
    "MAX_READING_REFERENCE_UNITS",
    "ResolvedReadingSource",
    "normalize_reading_references",
    "resolve_reading_sources",
]
