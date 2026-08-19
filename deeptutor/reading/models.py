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
UnitKind = Literal["page", "chapter", "slide", "section"]

AnnotationKind = Literal["highlight", "underline", "note"]

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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaterialManifest":
        unit = str(data.get("unit") or "page")
        return cls(
            material_id=str(data.get("material_id") or ""),
            filename=str(data.get("filename") or ""),
            unit=unit if unit in ("page", "chapter", "slide", "section") else "page",  # type: ignore[arg-type]
            unit_count=int(data.get("unit_count") or 0),
            mime=str(data.get("mime") or ""),
            title=str(data.get("title") or ""),
            source_hash=str(data.get("source_hash") or ""),
            extractor=str(data.get("extractor") or ""),
            byte_size=int(data.get("byte_size") or 0),
            char_count=int(data.get("char_count") or 0),
            created_at=float(data.get("created_at") or 0.0),
            has_raw_view=bool(data.get("has_raw_view")),
        )


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
    kind: AnnotationKind = "highlight"
    color: str = DEFAULT_ANNOTATION_COLOR
    quote: str = ""
    note: str = ""
    rects: tuple[Rect, ...] = ()
    author: str = "user"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touched(self, **changes: Any) -> "Annotation":
        return replace(self, updated_at=time.time(), **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "locator": self.locator,
            "kind": self.kind,
            "color": self.color,
            "quote": self.quote,
            "note": self.note,
            "rects": [r.to_list() for r in self.rects],
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
            kind=kind if kind in ("highlight", "underline", "note") else "highlight",  # type: ignore[arg-type]
            color=color if color in ANNOTATION_COLORS else DEFAULT_ANNOTATION_COLOR,
            quote=str(data.get("quote") or ""),
            note=str(data.get("note") or ""),
            rects=rects,
            author=str(data.get("author") or "user"),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
        )


__all__ = [
    "ANNOTATION_COLORS",
    "DEFAULT_ANNOTATION_COLOR",
    "Annotation",
    "AnnotationKind",
    "MaterialManifest",
    "MaterialNotFound",
    "OutlineEntry",
    "ReadingError",
    "Rect",
    "SearchHit",
    "UnitKind",
]
