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
from deeptutor.utils.document_images import (
    EmbeddedImage,
    build_marker,
    extract_docx_rich,
    extract_pdf_images,
    extract_pptx_rich,
    find_markers,
    reading_image_budget,
)

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
_MD_HEADING = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_MD_FENCE = re.compile(r"^\s{0,3}(?P<marker>`{3,}|~{3,})")

# Formats whose original bytes the browser can render faithfully next to the
# extracted text. Only PDF today; adding one means teaching the reader pane to
# render it, not changing this engine.
RAW_VIEW_EXTENSIONS = frozenset({".pdf"})


@dataclass(frozen=True, slots=True)
class MediaItem:
    """One embedded image pinned to the locator whose text references it."""

    name: str
    mime_type: str
    data: bytes
    locator: int


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
    # Embedded pictures (DOCX/PPTX) mapped to the unit that mentions them.
    media: tuple[MediaItem, ...] = field(default_factory=tuple)

    @property
    def char_count(self) -> int:
        return sum(len(u) for u in self.units)


def _media_for_units(
    units: tuple[str, ...], images: tuple[EmbeddedImage, ...]
) -> tuple[MediaItem, ...]:
    """Map ``[图片 N]`` markers in unit texts to their image bytes.

    A marker names the image it belongs to, so the mapping needs no position
    bookkeeping: scan each unit, look the name up, and pin the image to that
    locator. Repeated markers (the same figure floated into two sections) are
    kept once per locator; unknown names are skipped silently — the text still
    stands on its own.
    """
    by_name = {image.name: image for image in images}
    if not by_name:
        return ()
    items: list[MediaItem] = []
    seen: set[tuple[int, str]] = set()
    for locator, unit in enumerate(units, start=1):
        for _, name in find_markers(unit):
            image = by_name.get(name)
            if image is None or (locator, name) in seen:
                continue
            seen.add((locator, name))
            items.append(
                MediaItem(name=name, mime_type=image.mime_type, data=image.data, locator=locator)
            )
    return tuple(items)


def extract_material(path: str | Path, *, data: bytes | None = None) -> Extraction:
    """Cut *path* into units, dispatching on its extension.

    Raises :class:`ReadingError` when the file cannot be read at all, or when
    it yields no text — an image-only scan, for instance, which the reader
    would otherwise present as an empty document with no explanation. For an
    EPUB, ``data`` may contain already-normalized archive bytes so callers can
    extract and store exactly what they read.
    """
    source = Path(path)
    if not source.is_file():
        raise ReadingError(f"{source.name}: file not found")

    suffix = source.suffix.lower()
    if suffix == ".pdf":
        extraction = _extract_pdf(source)
    elif suffix == ".epub":
        if data is None:
            try:
                data = source.read_bytes()
            except OSError as exc:
                raise ReadingError(f"{source.name}: could not be read ({exc})") from exc
        extraction = _extract_epub(data, source.name)
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

    media: tuple[MediaItem, ...] = ()
    # Every page's figures ride along as locator-pinned media so the reader can
    # attach what the question is about. Mining them is best-effort: a quirk in
    # one image must never turn a readable PDF into a failed ingest.
    units, media = _pdf_pages_with_image_markers(units, source)

    return Extraction(
        units=units,
        unit="page",
        extractor="pymupdf",
        has_raw_view=True,
        title=title,
        outline=outline,
        render_mode="pdf",
        media=media,
    )


def _pdf_pages_with_image_markers(
    units: tuple[str, ...], source: Path
) -> tuple[tuple[str, ...], tuple[MediaItem, ...]]:
    """Append the page's ``[图片 N: name]`` markers to that page's text tail.

    Markers are appended only at the very end of each unit so the character
    offsets of the page's own prose never move — stored per-character
    annotations resolve against quotes lifted from this text, and shifting them
    would silently detach every highlight. The markers name the images, which
    :func:`_media_for_units` then resolves back into locator-pinned media via
    the same mapping DOCX/PPTX already use.

    Best-effort by contract: any failure or empty result returns the units and
    no media untouched, so an image quirk never turns a readable PDF into a
    failed ingest.
    """
    try:
        pdf_images = extract_pdf_images(source.read_bytes(), budget=reading_image_budget())
    except Exception:
        logger.warning("%s: PDF image extraction failed", source.name, exc_info=True)
        return units, ()
    if not pdf_images.collection.images:
        return units, ()

    marker_by_page: dict[int, list[str]] = {}
    for page_number, indices in pdf_images.page_map:
        marker_by_page[page_number] = [
            build_marker(pdf_images.collection.images[index]) for index in indices
        ]
    targeted = tuple(
        unit + ("\n" + "\n".join(marker_by_page[i]) if i in marker_by_page else "")
        for i, unit in enumerate(units, 1)
    )
    return targeted, _media_for_units(targeted, pdf_images.collection.images)


def _extract_epub(data: bytes, filename: str) -> Extraction:
    """Preserve EPUB spine order so browser and assistant locators agree."""
    from deeptutor.utils.document_extractor import DocumentExtractionError, extract_epub_spine

    try:
        units, navigation = extract_epub_spine(data, filename)
    except (OSError, DocumentExtractionError) as exc:
        raise ReadingError(f"{filename}: failed to read EPUB ({exc})") from exc

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
    text, images = _slides_text_and_images(source)
    parts = [part.strip() for part in _SLIDE_SEPARATOR.split(text)]
    units = tuple(part for part in parts if part)
    if not units:
        # The extractor found text but no slide separators (legacy .ppt via the
        # raw-OOXML fallback). Treat it as flat text rather than losing it.
        return _sections_from_text(text, extractor="pptx-text")
    return Extraction(
        units=units,
        unit="slide",
        extractor="pptx",
        media=_media_for_units(units, images),
    )


def _slides_text_and_images(source: Path) -> tuple[str, tuple[EmbeddedImage, ...]]:
    """Slide text with image markers, preferring the rich extraction.

    Falls back to the shared extractor (text only) when the rich path cannot
    read the deck, so ingest never fails on a picture quirk.
    """
    try:
        rich = extract_pptx_rich(source.read_bytes())
    except Exception:
        rich = None
    if rich is not None and any(slide.strip() for slide in rich.slides):
        parts = [
            f"--- Slide {index} ---\n{slide}".rstrip()
            for index, slide in enumerate(rich.slides, 1)
            if slide.strip()
        ]
        text = "\n\n".join(parts)
        note = rich.collection.summary_note()
        if note:
            text += f"\n\n{note}"
        return text, rich.collection.images
    return _shared_extract(source), ()


# ---------------------------------------------------------------------------
# Flat text → sections
# ---------------------------------------------------------------------------


def _extract_sections(source: Path) -> Extraction:
    """Flat-text formats, cut into sections on paragraph boundaries.

    DOCX goes through the rich extraction first so embedded images survive
    with their section mapping; every other format (and a failed rich parse)
    uses the shared text-only extractor.
    """
    images: tuple[EmbeddedImage, ...] = ()
    if source.suffix.lower() == ".docx":
        try:
            rich = extract_docx_rich(source.read_bytes())
        except Exception:
            rich = None
        if rich is not None and any(paragraph.strip() for paragraph in rich.paragraphs):
            text = "\n\n".join(rich.paragraphs)
            note = rich.collection.summary_note()
            if note:
                text += f"\n\n{note}"
            units = split_into_sections(text)
            return Extraction(
                units=units,
                unit="section",
                extractor="docx",
                media=_media_for_units(units, rich.collection.images),
            )
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


def split_markdown_by_headings(
    text: str,
) -> tuple[tuple[str, ...], tuple[OutlineEntry, ...]]:
    """Cut article markdown at headings and map every unit to its heading.

    A fetched page normally starts with the synthetic title heading added by
    the HTML extractor.  That heading alone is not meaningful article
    structure, so fewer than two usable headings deliberately falls back to
    :func:`split_into_sections` and returns no outline.  The store can then use
    its existing first-line outline rather than labelling an entire article as
    repeated continuations of the page title.

    Each heading-delimited region is still passed through the regular section
    splitter.  This preserves its hard cap for very long paragraphs, and every
    continuation gets an outline row pointing at its own locator while keeping
    the source heading's title and level.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalised:
        return (), ()

    boundaries: list[tuple[int, int, str]] = []
    fence_marker = ""
    offset = 0
    for line in normalised.splitlines(keepends=True):
        fence = _MD_FENCE.match(line)
        if fence:
            marker = fence.group("marker")
            if not fence_marker:
                fence_marker = marker[0]
            elif marker[0] == fence_marker:
                fence_marker = ""
            offset += len(line)
            continue
        if not fence_marker:
            heading = _MD_HEADING.match(line.rstrip("\n"))
            if heading:
                title = _clean_heading_title(heading.group("title"))
                if title:
                    boundaries.append((offset, len(heading.group("marks")), title))
        offset += len(line)

    if len(boundaries) < 2:
        return split_into_sections(normalised), ()

    units: list[str] = []
    outline: list[OutlineEntry] = []
    for index, (start, level, title) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(normalised)
        # Keep prose before the first heading instead of dropping it.  In web
        # extraction this is uncommon (the title is normally first), but hand-
        # authored pages sometimes place a short deck or byline above it.
        section_start = 0 if index == 0 else start
        for piece in split_into_sections(normalised[section_start:end]):
            units.append(piece)
            outline.append(OutlineEntry(locator=len(units), title=title, level=level))
    return tuple(units), tuple(outline)


def _clean_heading_title(title: str) -> str:
    """Remove inline Markdown decoration from a heading used as a UI label."""
    clean = re.sub(r"\[([^]]*)\]\([^)]*\)", r"\1", title)
    return re.sub(r"[*`_~]", "", clean).strip()


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
    "split_markdown_by_headings",
    "split_into_sections",
    "synthesise_outline",
]
