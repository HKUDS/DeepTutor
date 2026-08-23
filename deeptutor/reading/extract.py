"""Cut a source file into addressable units (the locator space).

One job, no I/O beyond reading the source: given a path, return the unit texts
plus what a unit *is* for that format. Everything else in the reading engine
consumes :class:`Extraction` and never looks at the original bytes again —
which is what keeps store, search, outline and export format-agnostic.

Per-format strategy, and why:

* **PDF** — PyMuPDF, one unit per physical page. Done here rather than through
  the shared text extractor because that one joins the pages into a single
  string; we need them apart. Physical pages are also the only unit that lines
  up with what the reader renders, so PDFs are the one format with a faithful
  raw view.
* **PPTX** — the shared extractor already emits ``--- Slide N ---`` separators,
  so we split on those instead of re-implementing python-pptx handling.
* **everything else** (EPUB, DOCX, XLSX, TXT, MD, code, …) — the shared
  extractor's plain text, cut into fixed-size *sections* on paragraph
  boundaries.

The last bullet is a deliberate trade-off for EPUB: chapter-accurate cutting
would mean reaching into the extractor's private per-chapter helpers, coupling
this module to their internals. Since a non-PDF material is read from extracted
text anyway (no faithful raw view), a section is nearly as good a handle as a
chapter, and the seam stays clean. Chapter cutting can be added later as one
more branch here without touching a single consumer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re

from deeptutor.reading.models import OutlineEntry, ReadingError, RenderMode, UnitKind, UnitReference

logger = logging.getLogger(__name__)

# Target size of a synthesised "section". Chosen to land near the character
# count of one dense printed page (~3k), so a section feels like a page to the
# reader and to the model's sense of "how much is this".
SECTION_TARGET_CHARS = 2800
# Never emit a section longer than this even if no paragraph break was found —
# a minified file or a single 200k-character line must still be addressable.
SECTION_HARD_CHARS = 4200

_SLIDE_SEPARATOR = re.compile(r"^--- Slide \d+ ---$", re.MULTILINE)
# Title candidates: a markdown heading, or the first non-trivial line.
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$")

# Formats whose original bytes the browser can render faithfully next to the
# extracted text. Only PDF today; adding one means teaching the reader pane to
# render it, not changing this engine.
RAW_VIEW_EXTENSIONS = frozenset({".pdf"})


@dataclass(frozen=True, slots=True)
class Extraction:
    """The result of cutting one source file into units."""

    units: tuple[str, ...]
    unit: UnitKind
    extractor: str
    has_raw_view: bool = False
    title: str = ""
    # Only populated when the format carries its own structure (PDF bookmarks).
    # Otherwise the outline is synthesised later from unit first lines, so that
    # a material without bookmarks is still navigable by meaning.
    outline: tuple[OutlineEntry, ...] = field(default_factory=tuple)
    render_mode: RenderMode = "text"
    unit_refs: tuple[UnitReference, ...] = field(default_factory=tuple)

    @property
    def char_count(self) -> int:
        return sum(len(u) for u in self.units)


def extract_material(path: str | Path) -> Extraction:
    """Cut *path* into units, dispatching on its extension.

    Raises :class:`ReadingError` when the file cannot be read at all, or when
    it yields no text — an image-only scan, for instance, which the reader
    would otherwise present as an empty document with no explanation.
    """
    source = Path(path)
    if not source.is_file():
        raise ReadingError(f"{source.name}: file not found")

    suffix = source.suffix.lower()
    if suffix == ".pdf":
        extraction = _extract_pdf(source)
    elif suffix == ".epub":
        extraction = _extract_epub(source)
    elif suffix == ".pptx":
        extraction = _extract_slides(source)
    else:
        extraction = _extract_sections(source)

    if not any(unit.strip() for unit in extraction.units):
        raise ReadingError(
            f"{source.name}: no readable text could be extracted. "
            "A scanned document needs OCR before it can be read here."
        )
    return extraction


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _extract_pdf(source: Path) -> Extraction:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - pymupdf is a core dep
        raise ReadingError("PDF reading needs PyMuPDF (pip install pymupdf)") from exc

    try:
        with pymupdf.open(source) as doc:
            if doc.is_encrypted and not doc.authenticate(""):
                raise ReadingError(f"{source.name} is encrypted and cannot be read")
            units = tuple((page.get_text() or "") for page in doc)
            outline = _pdf_outline(doc, page_count=len(units))
            title = str((doc.metadata or {}).get("title") or "").strip()
    except ReadingError:
        raise
    except Exception as exc:
        raise ReadingError(f"{source.name}: failed to read PDF ({exc})") from exc

    return Extraction(
        units=units,
        unit="page",
        extractor="pymupdf",
        has_raw_view=True,
        title=title,
        outline=outline,
        render_mode="pdf",
    )


def _extract_epub(source: Path) -> Extraction:
    """Preserve EPUB spine order so browser and assistant locators agree."""
    from deeptutor.utils.document_extractor import DocumentExtractionError, extract_epub_spine

    try:
        units, navigation = extract_epub_spine(source.read_bytes(), source.name)
    except (OSError, DocumentExtractionError) as exc:
        raise ReadingError(f"{source.name}: failed to read EPUB ({exc})") from exc

    refs = tuple(
        UnitReference(locator=index, source_href=unit.href, title=unit.title)
        for index, unit in enumerate(units, start=1)
    )
    outline = tuple(
        OutlineEntry(locator=row.locator, title=row.title, level=row.level) for row in navigation
    )
    if not outline:
        outline = tuple(
            OutlineEntry(
                locator=ref.locator,
                title=ref.title or Path(ref.source_href).stem,
                synthesised=not bool(ref.title),
            )
            for ref in refs
        )
    return Extraction(
        units=tuple(unit.text for unit in units),
        unit="chapter",
        extractor="epub-spine",
        outline=outline,
        render_mode="epub",
        unit_refs=refs,
    )


def _pdf_outline(doc: object, *, page_count: int) -> tuple[OutlineEntry, ...]:
    """Map the PDF's bookmark tree to outline rows, dropping unusable ones.

    A bookmark pointing outside the page range (some generators emit 0 or a
    stale page) is skipped rather than clamped, so the model is never sent to a
    locator that does not correspond to the heading it asked for.
    """
    try:
        toc = doc.get_toc()  # type: ignore[attr-defined]
    except Exception:
        logger.debug("PDF has no readable table of contents", exc_info=True)
        return ()

    entries: list[OutlineEntry] = []
    for row in toc or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            level, title, page = int(row[0]), str(row[1]).strip(), int(row[2])
        except (TypeError, ValueError):
            continue
        if not title or not (1 <= page <= page_count):
            continue
        entries.append(OutlineEntry(locator=page, title=title, level=max(1, level)))
    return tuple(entries)


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------


def _extract_slides(source: Path) -> Extraction:
    text = _shared_extract(source)
    parts = [part.strip() for part in _SLIDE_SEPARATOR.split(text)]
    units = tuple(part for part in parts if part)
    if not units:
        # The extractor found text but no slide separators (legacy .ppt via the
        # raw-OOXML fallback). Treat it as flat text rather than losing it.
        return _sections_from_text(text, extractor="pptx-text")
    return Extraction(units=units, unit="slide", extractor="pptx")


# ---------------------------------------------------------------------------
# Flat text → sections
# ---------------------------------------------------------------------------


def _extract_sections(source: Path) -> Extraction:
    return _sections_from_text(_shared_extract(source), extractor="text")


def _sections_from_text(text: str, *, extractor: str) -> Extraction:
    return Extraction(units=split_into_sections(text), unit="section", extractor=extractor)


def split_into_sections(text: str) -> tuple[str, ...]:
    """Cut flat text into sections, preferring paragraph boundaries.

    Greedy accumulation up to :data:`SECTION_TARGET_CHARS`, flushing at the
    paragraph that crosses it. A single paragraph longer than
    :data:`SECTION_HARD_CHARS` is hard-split so that pathological input (one
    enormous line) stays addressable.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalised:
        return ()

    sections: list[str] = []
    buffer: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal size
        if buffer:
            joined = "\n\n".join(buffer).strip()
            if joined:
                sections.append(joined)
            buffer.clear()
            size = 0

    for paragraph in normalised.split("\n\n"):
        block = paragraph.strip()
        if not block:
            continue
        for piece in _hard_split(block, SECTION_HARD_CHARS):
            buffer.append(piece)
            size += len(piece)
            if size >= SECTION_TARGET_CHARS:
                flush()
    flush()
    return tuple(sections)


def _hard_split(block: str, limit: int) -> list[str]:
    """Break an over-long paragraph at whitespace near *limit*, else mid-word."""
    if len(block) <= limit:
        return [block]
    pieces: list[str] = []
    remaining = block
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [piece for piece in pieces if piece]


def _shared_extract(source: Path) -> str:
    """Read *source* through the shared text extractor.

    Reuses the same code path chat attachments use, so a format that works as
    an attachment works as reading material — and gaining a format there gains
    it here for free. ``max_chars=None`` because the reading store keeps the
    full text on disk; the per-turn budget is enforced later, per unit read.
    ``max_bytes`` stays at the validator ceiling rather than ``None`` so a
    pathological upload still fails fast instead of being read into memory.
    """
    from deeptutor.utils.document_extractor import (
        DocumentExtractionError,
        extract_text_from_path,
    )
    from deeptutor.utils.document_validator import DocumentValidator

    try:
        return extract_text_from_path(
            source, max_bytes=DocumentValidator.MAX_FILE_SIZE, max_chars=None
        )
    except DocumentExtractionError as exc:
        raise ReadingError(f"{source.name}: {exc}") from exc
    except OSError as exc:
        raise ReadingError(f"{source.name}: could not be read ({exc})") from exc


def synthesise_outline(units: tuple[str, ...] | list[str]) -> tuple[OutlineEntry, ...]:
    """Build a fallback outline: one row per unit, labelled by its first line.

    Used for every material whose format carries no structure of its own. The
    label matters more than it looks: without it ``material_outline`` would
    return a bare count and the model would have to read units blindly to find
    anything.
    """
    entries: list[OutlineEntry] = []
    for index, unit in enumerate(units, start=1):
        entries.append(
            OutlineEntry(locator=index, title=first_line_label(unit), level=1, synthesised=True)
        )
    return tuple(entries)


def first_line_label(unit: str, *, limit: int = 90) -> str:
    """A short human label for a unit: its heading, else its first real line."""
    for raw_line in unit.splitlines():
        line = raw_line.strip()
        if len(line) < 2:
            continue
        heading = _MD_HEADING.match(line)
        if heading:
            line = heading.group("title").strip()
        if not line:
            continue
        return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return ""


__all__ = [
    "RAW_VIEW_EXTENSIONS",
    "SECTION_HARD_CHARS",
    "SECTION_TARGET_CHARS",
    "Extraction",
    "extract_material",
    "first_line_label",
    "split_into_sections",
    "synthesise_outline",
]
