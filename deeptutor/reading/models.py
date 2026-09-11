"""Data model for immersive reading — materials, locators, annotations.

The central abstraction is the **locator**: a 1-indexed address into a material
that means "page" for a PDF, "chapter" for an EPUB, "slide" for a deck and
"section" for a flat text file. Every tool, API route and UI affordance speaks
locators, so nothing downstream branches on the source format; only
:mod:`deeptutor.reading.extract` knows how a format is cut into units, and the
manifest records which word to show the user (:attr:`MaterialManifest.unit`).

Rectangles on an annotation are stored **normalised** (0..1 of the unit's
width/height, origin top-left, y growing downwards). That is the browser's
coordinate space and also PyMuPDF's page space, so highlights survive zoom,
re-render and export without a second transform.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import time
from typing import Any, Literal

# What one locator addresses, per source format. Purely presentational for the
# model and the UI ("page 12" vs "chapter 3"); the addressing is identical.
UnitKind = Literal["page", "chapter", "slide", "section", "segment"]
RenderMode = Literal["text", "pdf", "epub", "video", "audio"]
ContentFormat = Literal["plain_text", "web_markdown"]

AnnotationKind = Literal["highlight", "underline", "note", "citation"]
TextSelectorType = Literal["TextQuoteSelector", "TextPositionSelector"]
MAX_TEXT_SELECTOR_CHARS = 2000

# Palette offered by the reader toolbar. Kept server-side too so an annotation
# arriving from an older client (or a tool call) can be validated rather than
# trusted, and so the PDF export can map a name to real ink.
ANNOTATION_COLORS: dict[str, tuple[float, float, float]] = {
    "yellow": (0.99, 0.87, 0.35),
    "green": (0.55, 0.86, 0.58),
    "blue": (0.48, 0.75, 0.98),
    "pink": (0.98, 0.63, 0.78),
    "purple": (0.78, 0.68, 0.98),
}

DEFAULT_ANNOTATION_COLOR = "yellow"


class ReadingError(RuntimeError):
    """A reading operation failed in a way the user should see.

    Carries a user-facing message; the API layer maps it to a 4xx and the tool
    layer returns it as a failed :class:`~deeptutor.core.tool_protocol.ToolResult`
    so the model can recover instead of the turn dying.
    """


class MaterialNotFound(ReadingError):
    """The requested material id does not exist in this user's store."""


class ReadingUpgradeConflict(ReadingError):
    """A source-faithful upgrade would invalidate existing annotations."""


@dataclass(frozen=True, slots=True)
class Rect:
    """A normalised rectangle within one unit: 0..1, origin top-left."""

    x0: float
    y0: float
    x1: float
    y1: float

    def clamped(self) -> "Rect":
        """Order the corners and clip to the unit box.

        A selection dragged past the page edge, or bottom-up, still yields a
        usable rectangle instead of an inverted or out-of-bounds one.
        """

        def clip(value: float) -> float:
            return min(1.0, max(0.0, float(value)))

        x0, x1 = sorted((clip(self.x0), clip(self.x1)))
        y0, y1 = sorted((clip(self.y0), clip(self.y1)))
        return Rect(x0=x0, y0=y0, x1=x1, y1=y1)

    @property
    def is_degenerate(self) -> bool:
        """Whether the rectangle encloses no area (a zero-width caret)."""
        return (self.x1 - self.x0) <= 0 or (self.y1 - self.y0) <= 0

    def to_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    @classmethod
    def from_any(cls, value: Any) -> "Rect | None":
        """Parse a rectangle from a list/tuple or a mapping, or return None.

        Tolerant by design: rectangles arrive from the browser, from stored
        JSON and (potentially) from a model tool call, and one malformed row
        must not discard an otherwise valid annotation.
        """
        if isinstance(value, Rect):
            return value.clamped()
        if isinstance(value, (list, tuple)) and len(value) == 4:
            try:
                return cls(*(float(v) for v in value)).clamped()
            except (TypeError, ValueError):
                return None
        if isinstance(value, dict):
            try:
                return cls(
                    x0=float(value["x0"]),
                    y0=float(value["y0"]),
                    x1=float(value["x1"]),
                    y1=float(value["y1"]),
                ).clamped()
            except (KeyError, TypeError, ValueError):
                return None
        return None


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    """One row of a material's outline.

    ``level`` is 1-based nesting depth. ``title`` is the document's own heading
    when the format carries one (PDF bookmarks, EPUB spine titles), otherwise a
    synthesised first-line label so the model can still navigate by meaning
    rather than by guessing locators.
    """

    locator: int
    title: str
    level: int = 1
    synthesised: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator": self.locator,
            "title": self.title,
            "level": self.level,
            "synthesised": self.synthesised,
        }


@dataclass(frozen=True, slots=True)
class UnitReference:
    """Source address for one numeric locator in a faithful renderer."""

    locator: int
    source_href: str = ""
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator": self.locator,
            "source_href": self.source_href,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnitReference":
        return cls(
            locator=max(1, int(data.get("locator") or 1)),
            source_href=str(data.get("source_href") or ""),
            title=str(data.get("title") or ""),
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search match, addressed by locator with surrounding context."""

    locator: int
    snippet: str
    offset: int
    match: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator": self.locator,
            "snippet": self.snippet,
            "offset": self.offset,
            "match": self.match,
        }


@dataclass(frozen=True, slots=True)
class MaterialManifest:
    """Everything about a material except its text and its annotations."""

    material_id: str
    filename: str
    unit: UnitKind
    unit_count: int
    mime: str = ""
    title: str = ""
    source_hash: str = ""
    extractor: str = ""
    byte_size: int = 0
    char_count: int = 0
    created_at: float = field(default_factory=time.time)
    # Present only when the raw file can be rendered faithfully in the browser
    # (today: PDF). Other formats read from extracted text, so the reader shows
    # its text view and the export falls back to a Markdown excerpt.
    has_raw_view: bool = False
    # Selects the faithful renderer without overloading ``has_raw_view``.
    # The legacy boolean remains PDF-only until every client understands EPUB.
    render_mode: RenderMode = "text"
    # Uploaded Markdown remains literal source text; only captured web pages
    # opt into structured rendering.
    content_format: ContentFormat = "plain_text"
    source_type: str = "upload"
    source_url: str = ""
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "filename": self.filename,
            "unit": self.unit,
            "unit_count": self.unit_count,
            "mime": self.mime,
            "title": self.title,
            "source_hash": self.source_hash,
            "extractor": self.extractor,
            "byte_size": self.byte_size,
            "char_count": self.char_count,
            "created_at": self.created_at,
            "has_raw_view": self.has_raw_view,
            "render_mode": self.render_mode,
            "content_format": self.content_format,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaterialManifest":
        unit = str(data.get("unit") or "page")
        render_mode = str(data.get("render_mode") or "")
        if render_mode not in ("text", "pdf", "epub", "video", "audio"):
            render_mode = "pdf" if data.get("has_raw_view") else "text"
        content_format = str(data.get("content_format") or "")
        if content_format not in ("plain_text", "web_markdown"):
            content_format = "plain_text"
        return cls(
            material_id=str(data.get("material_id") or ""),
            filename=str(data.get("filename") or ""),
            unit=(unit if unit in ("page", "chapter", "slide", "section", "segment") else "page"),  # type: ignore[arg-type]
            unit_count=int(data.get("unit_count") or 0),
            mime=str(data.get("mime") or ""),
            title=str(data.get("title") or ""),
            source_hash=str(data.get("source_hash") or ""),
            extractor=str(data.get("extractor") or ""),
            byte_size=int(data.get("byte_size") or 0),
            char_count=int(data.get("char_count") or 0),
            created_at=float(data.get("created_at") or 0.0),
            has_raw_view=bool(data.get("has_raw_view")),
            render_mode=render_mode,  # type: ignore[arg-type]
            content_format=content_format,  # type: ignore[arg-type]
            source_type=str(data.get("source_type") or "upload"),
            source_url=str(data.get("source_url") or ""),
            revision=max(1, int(data.get("revision") or 1)),
        )


@dataclass(frozen=True, slots=True)
class TextQuoteSelector:
    """W3C TextQuoteSelector used to re-anchor text after content reflows."""

    exact: str
    prefix: str = ""
    suffix: str = ""
    type: Literal["TextQuoteSelector"] = "TextQuoteSelector"

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"type": self.type, "exact": self.exact}
        if self.prefix:
            row["prefix"] = self.prefix
        if self.suffix:
            row["suffix"] = self.suffix
        return row


@dataclass(frozen=True, slots=True)
class TextPositionSelector:
    """W3C TextPositionSelector in a rendered unit's text-content space."""

    start: int
    end: int
    type: Literal["TextPositionSelector"] = "TextPositionSelector"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "start": self.start, "end": self.end}


TextSelector = TextQuoteSelector | TextPositionSelector


def parse_text_selectors(value: Any) -> tuple[TextSelector, ...]:
    """Parse only the two bounded selector shapes supported by the reader."""

    if not isinstance(value, (list, tuple)):
        return ()
    parsed: list[TextSelector] = []
    for raw in value[:2]:
        if not isinstance(raw, dict):
            continue
        selector_type = str(raw.get("type") or "")
        if selector_type == "TextQuoteSelector":
            exact = str(raw.get("exact") or "")[:2000]
            if exact:
                parsed.append(
                    TextQuoteSelector(
                        exact=exact,
                        # W3C prefix is the text immediately before ``exact``;
                        # when legacy data exceeds the bound, its tail is the
                        # part that still touches the selection.
                        prefix=str(raw.get("prefix") or "")[-128:],
                        suffix=str(raw.get("suffix") or "")[:128],
                    )
                )
        elif selector_type == "TextPositionSelector":
            try:
                start = max(0, int(raw.get("start") or 0))
                end = max(start, int(raw.get("end") or 0))
            except (TypeError, ValueError):
                continue
            if end > start:
                parsed.append(TextPositionSelector(start=start, end=end))
    return tuple(parsed)


@dataclass(frozen=True, slots=True)
class Annotation:
    """One user (or model) mark on a material.

    ``quote`` is the text the mark covers — it is what makes an annotation
    portable: the Markdown export, the chat context and the "jump back to this
    mark" affordance all read the quote, not the geometry. ``rects`` is optional
    for exactly that reason; a note attached to a whole unit has none.
    """

    annotation_id: str
    locator: int
    # Content revision the verified locator/selectors were captured against.
    # Legacy rows predate revisioned web snapshots and therefore resolve to 1.
    material_revision: int = 1
    kind: AnnotationKind = "highlight"
    color: str = DEFAULT_ANNOTATION_COLOR
    quote: str = ""
    note: str = ""
    rects: tuple[Rect, ...] = ()
    # Opaque renderer-native position. EPUB clients store a CFI here.
    source_anchor: str = ""
    # Portable W3C selectors for reflowing text. Existing annotations omit
    # them and continue to resolve through ``quote`` and/or ``rects``.
    selectors: tuple[TextSelector, ...] = ()
    author: str = "user"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touched(self, **changes: Any) -> "Annotation":
        return replace(self, updated_at=time.time(), **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "locator": self.locator,
            "material_revision": self.material_revision,
            "kind": self.kind,
            "color": self.color,
            "quote": self.quote,
            "note": self.note,
            "rects": [r.to_list() for r in self.rects],
            "source_anchor": self.source_anchor,
            "selectors": [selector.to_dict() for selector in self.selectors],
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Annotation":
        kind = str(data.get("kind") or "highlight")
        color = str(data.get("color") or DEFAULT_ANNOTATION_COLOR)
        rects = tuple(
            rect
            for rect in (Rect.from_any(raw) for raw in (data.get("rects") or []))
            if rect is not None and not rect.is_degenerate
        )
        return cls(
            annotation_id=str(data.get("annotation_id") or ""),
            locator=max(1, int(data.get("locator") or 1)),
            material_revision=max(1, int(data.get("material_revision") or 1)),
            kind=(kind if kind in ("highlight", "underline", "note", "citation") else "highlight"),  # type: ignore[arg-type]
            color=color if color in ANNOTATION_COLORS else DEFAULT_ANNOTATION_COLOR,
            quote=str(data.get("quote") or ""),
            note=str(data.get("note") or ""),
            rects=rects,
            source_anchor=str(data.get("source_anchor") or ""),
            selectors=parse_text_selectors(data.get("selectors")),
            author=str(data.get("author") or "user"),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
        )


@dataclass(frozen=True, slots=True)
class ReadingBookmark:
    """A place in a material the reader chose to keep.

    Distinct from the reading position, which the reader never asks for: that
    is one automatically-updated "where I got to", overwritten every time they
    move. A bookmark is deliberate and plural — the three passages worth
    coming back to in a 400-page book — so it is addressed by its own id and
    carries a label.

    The label is optional. An empty one means "this page", and the reader sees
    the outline heading for that locator instead of a name they had to invent
    before they were allowed to save the spot.
    """

    bookmark_id: str
    locator: int
    label: str = ""
    # Opaque renderer-native position, for formats where the locator alone is
    # coarse. EPUB clients store a CFI here, exactly as annotations do.
    source_anchor: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bookmark_id": self.bookmark_id,
            "locator": self.locator,
            "label": self.label,
            "source_anchor": self.source_anchor,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReadingBookmark":
        return cls(
            bookmark_id=str(data.get("bookmark_id") or ""),
            locator=max(1, int(data.get("locator") or 1)),
            label=str(data.get("label") or ""),
            source_anchor=str(data.get("source_anchor") or ""),
            created_at=float(data.get("created_at") or 0.0),
        )


@dataclass(frozen=True, slots=True)
class ReadingPosition:
    """Last durable viewport for a material."""

    locator: int = 1
    source_anchor: str = ""
    percentage: float = 0.0
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "locator": self.locator,
            "source_anchor": self.source_anchor,
            "percentage": self.percentage,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReadingPosition":
        return cls(
            locator=max(1, int(data.get("locator") or 1)),
            source_anchor=str(data.get("source_anchor") or ""),
            percentage=min(1.0, max(0.0, float(data.get("percentage") or 0.0))),
            updated_at=float(data.get("updated_at") or 0.0),
        )


__all__ = [
    "ANNOTATION_COLORS",
    "DEFAULT_ANNOTATION_COLOR",
    "Annotation",
    "AnnotationKind",
    "ContentFormat",
    "MaterialManifest",
    "MaterialNotFound",
    "OutlineEntry",
    "ReadingBookmark",
    "ReadingError",
    "ReadingPosition",
    "ReadingUpgradeConflict",
    "RenderMode",
    "Rect",
    "SearchHit",
    "TextPositionSelector",
    "TextQuoteSelector",
    "TextSelector",
    "TextSelectorType",
    "UnitKind",
    "UnitReference",
]
