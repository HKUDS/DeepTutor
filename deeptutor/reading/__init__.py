"""Immersive reading engine — materials, locators, annotations, export.

A *material* is a file the user reads: it is cut once into **units** and stored
per-unit, so every later operation addresses it by **locator** (a 1-indexed unit
number that means page / chapter / slide / section depending on the format).
That one abstraction is what lets a model cite "page 12" and the reader scroll
to page 12 without either side knowing the file is a PDF.

Layering, bottom-up — each layer depends only on the ones above it in this list:

* :mod:`.models` — dataclasses and errors. No I/O, no imports from siblings.
* :mod:`.extract` — file → units. The only module that knows about formats.
* :mod:`.search` — pure locator-addressed matching over ``(locator, text)``.
* :mod:`.store` — durable per-material layout, atomic writes, annotations.
* :mod:`.service` — the composition callers use (read / search / outline /
  quote verification).
* :mod:`.export` — the annotated artefacts a user can take away.

Nothing here imports the chat loop, the tool registry or FastAPI, so the engine
is testable on its own and the capability that drives it
(:mod:`deeptutor.capabilities.reading`) stays a thin shell.
"""

from __future__ import annotations

from deeptutor.reading.export import ExportFormat, ExportResult, export_material
from deeptutor.reading.extract import Extraction, extract_material
from deeptutor.reading.models import (
    ANNOTATION_COLORS,
    Annotation,
    AnnotationKind,
    BilingualGroup,
    ContentFormat,
    MaterialManifest,
    MaterialNotFound,
    OutlineEntry,
    ReadingError,
    ReadingPosition,
    ReadingUpgradeConflict,
    Rect,
    RenderMode,
    SearchHit,
    SourceType,
    TextPositionSelector,
    TextQuoteSelector,
    TextSelector,
    UnitKind,
    UnitReference,
)
from deeptutor.reading.search import SearchResult, search_units
from deeptutor.reading.service import (
    QuoteCheck,
    RenderedUnits,
    material_summary,
    parse_locators,
    render_outline,
    render_units,
    search_material,
    verify_quote,
)
from deeptutor.reading.sources import (
    FileSourceAdapter,
    ReadingSourceAdapter,
    ReadingSourcePayload,
    SnapshotAsset,
    localize_snapshot_images,
    markdown_payload,
    normalize_snapshot_links,
    sanitize_snapshot_markdown,
)
from deeptutor.reading.store import ReadingStore, content_hash

__all__ = [
    "ANNOTATION_COLORS",
    "Annotation",
    "AnnotationKind",
    "BilingualGroup",
    "ContentFormat",
    "ExportFormat",
    "ExportResult",
    "Extraction",
    "MaterialManifest",
    "MaterialNotFound",
    "OutlineEntry",
    "QuoteCheck",
    "ReadingError",
    "ReadingPosition",
    "ReadingUpgradeConflict",
    "ReadingStore",
    "Rect",
    "RenderedUnits",
    "SearchHit",
    "SearchResult",
    "RenderMode",
    "SourceType",
    "TextPositionSelector",
    "TextQuoteSelector",
    "TextSelector",
    "UnitKind",
    "UnitReference",
    "FileSourceAdapter",
    "ReadingSourceAdapter",
    "ReadingSourcePayload",
    "SnapshotAsset",
    "content_hash",
    "export_material",
    "extract_material",
    "material_summary",
    "localize_snapshot_images",
    "markdown_payload",
    "normalize_snapshot_links",
    "sanitize_snapshot_markdown",
    "parse_locators",
    "render_outline",
    "render_units",
    "search_material",
    "search_units",
    "verify_quote",
]
