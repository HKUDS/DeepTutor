"""Composition layer over the reading engine.

Everything a caller wants to *do* with a material lives here, so the two
callers — the capability's tools and the REST router — share one implementation
and stay dumb adapters. Nothing in this module knows about tools, HTTP, the
chat loop or the LLM; it takes a :class:`~deeptutor.reading.store.ReadingStore`
and returns plain data.

The locator grammar (``"12"``, ``"12-14"``, ``"3,12,17"``) is parsed here too:
it is the syntax the model types, so it needs one tolerant parser with one set
of rules rather than a regex per call site.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from deeptutor.reading.models import MaterialManifest, OutlineEntry, ReadingError
from deeptutor.reading.search import SearchResult, locate_quote, search_units
from deeptutor.reading.store import MAX_READ_CHARS, ReadingStore

# How many locators one read may request. Guards the context budget before any
# file is opened; the character ceiling in the store guards it afterwards.
MAX_LOCATORS_PER_READ = 24
# Outline rows rendered for the model in one go. A 900-page book's full outline
# would itself blow the prompt, so long outlines are summarised by level.
MAX_OUTLINE_ROWS = 120

_RANGE = re.compile(r"^\s*(\d+)\s*(?:[-–—:]\s*(\d+))?\s*$")


@dataclass(frozen=True, slots=True)
class RenderedUnits:
    """Unit text prepared for a model, with an explicit truncation signal."""

    text: str
    locators: tuple[int, ...]
    truncated: bool
    unit: str

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    """Whether a claimed quote really appears where it was claimed."""

    verified: bool
    locator: int
    quote: str
    found_locator: int | None = None

    @property
    def moved(self) -> bool:
        """True when the quote exists, but on a different locator."""
        return self.found_locator is not None and self.found_locator != self.locator


def parse_locators(spec: str | int | Sequence[int], unit_count: int) -> list[int]:
    """Parse a locator spec into an ascending, de-duplicated, in-range list.

    Accepts an int, a sequence of ints, or a string of comma-separated numbers
    and ranges. Out-of-range values are dropped rather than clamped — silently
    turning "page 900" into "page 12" would make the model cite text the user
    never asked about. Raises when the spec parses to nothing at all, so the
    tool can tell the model what it did wrong.
    """
    if unit_count <= 0:
        raise ReadingError("this material has no readable units")

    raw: list[int] = []
    if isinstance(spec, int):
        raw = [spec]
    elif isinstance(spec, str):
        for chunk in spec.replace("，", ",").split(","):
            if not chunk.strip():
                continue
            match = _RANGE.match(chunk)
            if not match:
                continue
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if end < start:
                start, end = end, start
            # Bound the expansion before allocating: "1-100000" must not
            # materialise a hundred thousand integers to then discard them.
            raw.extend(range(start, min(end, start + MAX_LOCATORS_PER_READ) + 1))
    else:
        for value in spec or []:
            try:
                raw.append(int(value))
            except (TypeError, ValueError):
                continue

    in_range = sorted({value for value in raw if 1 <= value <= unit_count})
    if not in_range:
        raise ReadingError(f"no valid locator in {spec!r} — this material has 1..{unit_count}.")
    return in_range[:MAX_LOCATORS_PER_READ]


def render_units(
    store: ReadingStore,
    material_id: str,
    spec: str | int | Sequence[int],
    *,
    max_chars: int = MAX_READ_CHARS,
) -> RenderedUnits:
    """Read the requested units and render them with locator headers.

    The header format matches what the shared text extractor already emits
    (``--- Page 12 ---``), so a model that has seen a DeepTutor attachment
    recognises the shape without being taught twice.
    """
    manifest = store.manifest(material_id)
    locators = parse_locators(spec, manifest.unit_count)
    rows, truncated = store.read_units(material_id, locators, max_chars=max_chars)

    label = manifest.unit.capitalize()
    blocks: list[str] = []
    for locator, text in rows:
        body = text.strip()
        blocks.append(
            f"--- {label} {locator} ---\n{body}" if body else f"--- {label} {locator} ---\n(empty)"
        )
    rendered = "\n\n".join(blocks)
    if truncated:
        rendered += (
            f"\n\n[truncated — the requested range exceeds the {max_chars}-character "
            f"read limit. Read fewer {manifest.unit}s at a time.]"
        )
    return RenderedUnits(
        text=rendered,
        locators=tuple(locator for locator, _ in rows),
        truncated=truncated,
        unit=manifest.unit,
    )


def search_material(
    store: ReadingStore,
    material_id: str,
    query: str,
    *,
    limit: int = 12,
) -> SearchResult:
    """Search one material, streaming its units through the matcher."""
    store.manifest(material_id)
    return search_units(store.iter_units(material_id), query, limit=limit)


def verify_quote(store: ReadingStore, material_id: str, locator: int, quote: str) -> QuoteCheck:
    """Check that *quote* appears on *locator*, and find it if it does not.

    This is the guard in front of ``reader_goto``: a hallucinated quote would
    otherwise yank the user's viewport to an arbitrary page. When the quote
    turns out to live elsewhere, the real locator is reported so the caller can
    correct the jump instead of cancelling it.
    """
    manifest = store.manifest(material_id)
    text = (quote or "").strip()
    if not text:
        return QuoteCheck(verified=False, locator=locator, quote="")
    if 1 <= locator <= manifest.unit_count:
        if locate_quote(store.unit_text(material_id, locator), text) >= 0:
            return QuoteCheck(verified=True, locator=locator, quote=text, found_locator=locator)
    found = search_units(store.iter_units(material_id), text, limit=1)
    if found.hits and found.mode in ("exact", "normalised"):
        hit = found.hits[0]
        return QuoteCheck(verified=True, locator=locator, quote=text, found_locator=hit.locator)
    return QuoteCheck(verified=False, locator=locator, quote=text)


def unit_timestamps(store: ReadingStore, manifest: MaterialManifest) -> dict[int, str]:
    """Locator → clock time, for timed media only. Empty for documents."""
    if manifest.render_mode not in {"video", "audio"}:
        return {}
    return {
        ref.locator: ref.title
        for ref in store.unit_references(manifest.material_id)
        if ref.title and ref.source_href.startswith("#t=")
    }


def render_outline(store: ReadingStore, material_id: str) -> str:
    """A compact outline for the model: one line per row, locator first."""
    manifest = store.manifest(material_id)
    entries = store.outline(material_id)
    label = manifest.unit
    header = (
        f"{manifest.filename} — {manifest.unit_count} {label}s"
        f"{f', titled “{manifest.title}”' if manifest.title else ''}"
    )
    if not entries:
        return f"{header}\n(no outline available; read {label}s directly)"

    trimmed, omitted = _trim_outline(entries)
    lines = [header, ""]
    for entry in trimmed:
        indent = "  " * max(0, entry.level - 1)
        title = entry.title or "(untitled)"
        lines.append(f"{indent}{label} {entry.locator}: {title}")
    if omitted:
        lines.append(f"… {omitted} more rows omitted; ask for a range to see them.")
    return "\n".join(lines)


def _trim_outline(entries: Sequence[OutlineEntry]) -> tuple[list[OutlineEntry], int]:
    """Bound an outline, preferring shallow rows when it must be cut.

    Dropping the deepest levels first keeps the document's shape legible; the
    alternative (a hard head-slice) would strand the model in chapter one.
    """
    if len(entries) <= MAX_OUTLINE_ROWS:
        return list(entries), 0
    for max_level in range(1, 7):
        kept = [entry for entry in entries if entry.level <= max_level]
        if len(kept) > MAX_OUTLINE_ROWS:
            shallower = [entry for entry in entries if entry.level < max_level]
            if shallower:
                return shallower[:MAX_OUTLINE_ROWS], len(entries) - len(
                    shallower[:MAX_OUTLINE_ROWS]
                )
            break
    return list(entries[:MAX_OUTLINE_ROWS]), len(entries) - MAX_OUTLINE_ROWS


def material_summary(manifest: MaterialManifest) -> str:
    """One line describing a material, for prompts and pickers."""
    size_kb = max(1, manifest.byte_size // 1024)
    return (
        f"{manifest.filename} ({manifest.unit_count} {manifest.unit}s, "
        f"{manifest.char_count} chars, {size_kb} KB)"
    )


__all__ = [
    "MAX_LOCATORS_PER_READ",
    "MAX_OUTLINE_ROWS",
    "QuoteCheck",
    "RenderedUnits",
    "material_summary",
    "parse_locators",
    "render_outline",
    "render_units",
    "search_material",
    "unit_timestamps",
    "verify_quote",
]
