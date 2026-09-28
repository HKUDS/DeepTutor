"""Embedded-image extraction for Office documents and PDFs.

Text extraction everywhere in DeepTutor is text-only by design, which silently
drops the pictures inside DOCX/PPTX/PDF attachments: the reader never sees
them and neither does the model. This module is the shared fix — bytes in,
embedded raster images out, plus the *marker strings* that let the plain-text
extraction record where each image belonged in the reading order.

Two consumers:
  * ``utils.document_extractor`` — chat attachments (and the KB/reading text
    paths that share its parsers) append the markers to the extracted text and
    emit the images as image-type attachment records so the existing
    multimodal injection pipeline forwards them to vision-capable models.
  * ``reading.extract`` — maps markers to section locators so the reader pane
    can display each image next to the section that contains it.

Markers use a fixed, greppable format (``[图片 3: image-03.png]``) so both
consumers and the model itself can tie an image back to its position without
any side-channel. Numbering is 1-based and document-wide, matching the
``name`` given to each :class:`EmbeddedImage`.

Vector formats (EMF/WMF) and other formats vision models cannot consume are
counted in the returned :class:`ImageCollection` and never emitted, but the
text keeps an unnumbered note so their existence is not silently erased.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import logging
import posixpath
import re
from typing import Any
import zipfile

from defusedxml import ElementTree as DefusedElementTree

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Budgets. Defaults serve the chat-attachment path; the reading-area ingest
# passes looser per-document caps because images are stored on disk there and
# never inflated into a single LLM request.
# ---------------------------------------------------------------------------
MAX_IMAGES_PER_DOC = 12
MAX_TOTAL_IMAGE_BYTES_PER_DOC = 12 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MIN_IMAGE_BYTES = 1_200  # below this it is a bullet point or a divider, not a figure


def reading_image_budget() -> ImageBudget:
    """Looser per-document caps for the reading-area ingest path.

    The reading store keeps the image bytes on disk, and a single chat turn
    inflates only the *current page's* images into the request, so the caps
    split in two directions: the document-wide caps can be far looser than the
    chat-attachment defaults, while the per-page cap is tightened to what one
    request can carry. ``max_images_per_page=4`` mirrors
    ``READING_VIEWPORT_MAX_IMAGES`` in ``services/session/_turn_runtime_shared``
    (kept as a literal so this utils module stays free of a services import).
    """
    return ImageBudget(
        max_images=120,
        max_total_bytes=60 * 1024 * 1024,
        max_images_per_page=4,
    )


# Raster formats vision models and the browser can both consume. Everything
# else (EMF/WMF vector, TIFF, SVG, …) is skipped with a note.
SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
)

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@dataclass(frozen=True, slots=True)
class EmbeddedImage:
    """One extracted raster image. ``name`` is unique within a document."""

    name: str
    mime_type: str
    data: bytes


@dataclass
class ImageBudget:
    """Running caps and skip counters while collecting one document's images.

    Mutable by design: the walk functions thread one instance through the
    whole document and read the counters afterwards.
    """

    max_images: int = MAX_IMAGES_PER_DOC
    max_total_bytes: int = MAX_TOTAL_IMAGE_BYTES_PER_DOC
    max_image_bytes: int = MAX_IMAGE_BYTES
    min_image_bytes: int = MIN_IMAGE_BYTES
    # 0 = unlimited. Only the per-page walkers (PDF) enforce this; it keeps one
    # page from monopolising the document budget when a single request can only
    # carry a handful of images.
    max_images_per_page: int = 0
    count: int = 0
    total_bytes: int = 0
    skipped_vector: int = 0
    skipped_other: int = 0
    skipped_budget: int = 0
    skipped_page_budget: int = 0

    def register_vector_skip(self) -> None:
        self.skipped_vector += 1

    def register_other_skip(self) -> None:
        self.skipped_other += 1

    def try_admit(self, ext: str, data: bytes) -> EmbeddedImage | None:
        """Admit one candidate image, applying every budget. ``None`` = skip."""
        if len(data) < self.min_image_bytes or len(data) > self.max_image_bytes:
            self.skipped_budget += 1
            return None
        if self.count >= self.max_images or self.total_bytes + len(data) > self.max_total_bytes:
            self.skipped_budget += 1
            return None
        self.count += 1
        self.total_bytes += len(data)
        return EmbeddedImage(
            name=f"image-{self.count:02d}{ext}",
            mime_type=_MIME_BY_EXT.get(ext, "application/octet-stream"),
            data=data,
        )


@dataclass(frozen=True, slots=True)
class ImageCollection:
    """Images from one document plus how many were left behind."""

    images: tuple[EmbeddedImage, ...] = ()
    skipped_vector: int = 0
    skipped_other: int = 0
    skipped_budget: int = 0
    skipped_page_budget: int = 0

    def summary_note(self) -> str:
        """One-line note for the extracted text describing what was dropped."""
        parts: list[str] = []
        if self.skipped_vector:
            parts.append(f"{self.skipped_vector} 张矢量图(EMF/WMF)未提取")
        if self.skipped_other:
            parts.append(f"{self.skipped_other} 张不支持的图片格式未提取")
        if self.skipped_budget:
            parts.append(f"{self.skipped_budget} 张图片超出数量/大小上限未提取")
        if self.skipped_page_budget:
            parts.append(f"{self.skipped_page_budget} 张超出单页上限未提取")
        if not parts:
            return ""
        return "[" + "，".join(parts) + "]"


@dataclass(frozen=True, slots=True)
class DocxRich:
    """Marker-annotated body paragraphs plus the images they reference."""

    paragraphs: tuple[str, ...] = ()
    collection: ImageCollection = field(default_factory=ImageCollection)


@dataclass(frozen=True, slots=True)
class PptxRich:
    """Per-slide text with image markers, plus the slide images."""

    slides: tuple[str, ...] = ()
    collection: ImageCollection = field(default_factory=ImageCollection)


@dataclass(frozen=True, slots=True)
class PdfImages:
    """PDF page images with the page each first appeared on."""

    collection: ImageCollection = field(default_factory=ImageCollection)
    page_map: tuple[tuple[int, tuple[int, ...]], ...] = ()  # (page, image indices)


def image_index_from_name(name: str) -> int:
    """``image-03.png`` → 3. Marker text and numbering stay in lockstep."""
    stem = posixpath.basename(name).rsplit(".", 1)[0]
    tail = stem.rsplit("-", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return 0


def build_marker(image: EmbeddedImage) -> str:
    """The canonical in-text marker for one image."""
    return f"[图片 {image_index_from_name(image.name)}: {image.name}]"


_MARKER_PATTERN = re.compile(r"\[图片 (\d+): ([^\]\s]+)\]")


def find_markers(text: str) -> list[tuple[int, str]]:
    """All ``(image_index, image_name)`` markers in *text*, in order."""
    return [(int(m.group(1)), m.group(2)) for m in _MARKER_PATTERN.finditer(text)]


def _local_name(tag: Any) -> str:
    if isinstance(tag, str) and "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag if isinstance(tag, str) else ""


def _parse_xml(raw: bytes) -> Any:
    return DefusedElementTree.fromstring(raw)


def _normalise_ext(ext: str) -> str:
    ext = (ext or "").lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def extract_docx_rich(data: bytes, *, budget: ImageBudget | None = None) -> DocxRich:
    """Walk ``word/document.xml`` once, collecting ordered paragraphs and images.

    Only the main body is mined (header/footer images are decoration). A
    relationship target referenced by several paragraphs is extracted once but
    marked at every position, so repeated/floating figures stay anchored to
    the text around them.
    """
    budget = budget or ImageBudget()
    images: list[EmbeddedImage] = []
    by_target: dict[str, EmbeddedImage] = {}
    attempted: set[str] = set()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        rel_targets = _office_rels(zf, "word/_rels/document.xml.rels")
        root = _parse_xml(zf.read("word/document.xml"))

        paragraphs: list[str] = []
        for node in root.iter():
            if _local_name(node.tag) != "p":
                continue
            text_parts: list[str] = []
            markers: list[str] = []
            seen_rids: set[str] = set()
            for child in node.iter():
                name = _local_name(child.tag)
                if name == "t" and child.text:
                    text_parts.append(child.text)
                elif name == "tab":
                    text_parts.append("\t")
                elif name in {"br", "cr"}:
                    text_parts.append("\n")
                elif name == "blip":
                    rid = _blip_embed_rid(child)
                    if not rid or rid in seen_rids:
                        continue
                    seen_rids.add(rid)
                    target = rel_targets.get(rid, "")
                    image = by_target.get(target)
                    if image is None and target not in attempted:
                        attempted.add(target)
                        image = _load_office_image(zf, names, target, budget, images)
                        if image is not None:
                            by_target[target] = image
                    if image is not None:
                        markers.append(build_marker(image))
            paragraph = "".join(text_parts).strip()
            if markers:
                paragraph = (paragraph + "\n" if paragraph else "") + "\n".join(markers)
            if paragraph:
                paragraphs.append(paragraph)

    return DocxRich(
        paragraphs=tuple(paragraphs),
        collection=_collection_from(budget, images),
    )


def _blip_embed_rid(blip: Any) -> str:
    """The ``r:embed`` relationship id of one ``a:blip`` (external links out)."""
    for key, value in blip.attrib.items():
        if value and _local_name(key) == "embed":
            return str(value)
    return ""


def _office_rels(zf: zipfile.ZipFile, rels_member: str) -> dict[str, str]:
    """rId → normalised archive path for internal media targets."""
    try:
        raw = zf.read(rels_member)
    except KeyError:
        return {}
    try:
        root = _parse_xml(raw)
    except Exception:
        return {}
    base = posixpath.dirname(posixpath.dirname(rels_member))  # …/word/_rels → …/word
    targets: dict[str, str] = {}
    for node in root.iter():
        if _local_name(node.tag) != "Relationship":
            continue
        if (node.get("TargetMode") or "").lower() == "external":
            continue
        rid = node.get("Id") or ""
        target = node.get("Target") or ""
        if rid and target:
            targets[rid] = posixpath.normpath(posixpath.join(base, target))
    return targets


def _load_office_image(
    zf: zipfile.ZipFile,
    names: set[str],
    target: str,
    budget: ImageBudget,
    images: list[EmbeddedImage],
) -> EmbeddedImage | None:
    if not target or target not in names:
        return None
    ext = _normalise_ext(posixpath.splitext(target)[1])
    if ext in {".emf", ".wmf"}:
        budget.register_vector_skip()
        return None
    if ext not in SUPPORTED_IMAGE_EXTENSIONS:
        budget.register_other_skip()
        return None
    try:
        data = zf.read(target)
    except (KeyError, zipfile.BadZipFile):
        return None
    image = budget.try_admit(ext, data)
    if image is not None:
        images.append(image)
    return image


def _collection_from(budget: ImageBudget, images: list[EmbeddedImage]) -> ImageCollection:
    return ImageCollection(
        images=tuple(images),
        skipped_vector=budget.skipped_vector,
        skipped_other=budget.skipped_other,
        skipped_budget=budget.skipped_budget,
        skipped_page_budget=budget.skipped_page_budget,
    )


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------


def extract_pptx_rich(data: bytes, *, budget: ImageBudget | None = None) -> PptxRich:
    """Slide texts with markers plus pictures, via python-pptx when available.

    python-pptx resolves picture placeholders and grouped shapes cleanly and
    only reports images actually placed on a slide (layout/master decoration
    stays out). The raw-OOXML fallback additionally catches background fills
    when python-pptx is missing or fails.
    """
    try:
        from pptx import Presentation
    except ImportError:
        return _extract_pptx_rich_ooxml(data, budget=budget)

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception:
        return _extract_pptx_rich_ooxml(data, budget=budget)

    budget = budget or ImageBudget()
    images: list[EmbeddedImage] = []
    slides: list[str] = []
    for slide in prs.slides:
        lines: list[str] = []
        _collect_shape_rich(slide.shapes, lines, budget, images)
        slides.append("\n".join(line for line in lines if line))

    return PptxRich(slides=tuple(slides), collection=_collection_from(budget, images))


def _collect_shape_rich(
    shapes: Any,
    lines: list[str],
    budget: ImageBudget,
    images: list[EmbeddedImage],
) -> None:
    for shape in shapes:
        sub_shapes = getattr(shape, "shapes", None)
        if sub_shapes is not None:
            _collect_shape_rich(sub_shapes, lines, budget, images)
            continue

        try:
            image = shape.image  # Picture only; other shapes raise or lack it
            blob = image.blob
            ext = _normalise_ext("." + (image.ext or ""))
        except Exception:
            blob, ext = b"", ""
        if blob:
            if ext in {".emf", ".wmf"}:
                budget.register_vector_skip()
            elif ext in SUPPORTED_IMAGE_EXTENSIONS:
                admitted = budget.try_admit(ext, blob)
                if admitted is not None:
                    images.append(admitted)
                    lines.append(build_marker(admitted))
            else:
                budget.register_other_skip()

        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                line = "\t".join(cell for cell in cells if cell)
                if line:
                    lines.append(line)
            continue
        text = getattr(shape, "text", "")
        if text and text.strip():
            lines.append(text.strip())


def _extract_pptx_rich_ooxml(data: bytes, *, budget: ImageBudget | None = None) -> PptxRich:
    """Raw fallback: per-slide paragraph text + blip markers from slide rels."""
    budget = budget or ImageBudget()
    images: list[EmbeddedImage] = []
    slides: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        slide_members = sorted(
            (name for name in names if _SLIDE_MEMBER_PATTERN.fullmatch(name)),
            key=_natural_slide_key,
        )
        for member in slide_members:
            rel_targets = _office_rels(zf, _rels_for(member))
            lines: list[str] = []
            try:
                root = _parse_xml(zf.read(member))
            except Exception:
                slides.append("")
                continue
            for node in root.iter():
                if _local_name(node.tag) != "p":
                    continue
                text_parts: list[str] = []
                markers: list[str] = []
                seen_rids: set[str] = set()
                for child in node.iter():
                    name = _local_name(child.tag)
                    if name == "t" and child.text:
                        text_parts.append(child.text)
                    elif name == "tab":
                        text_parts.append("\t")
                    elif name in {"br", "cr"}:
                        text_parts.append("\n")
                    elif name == "blip":
                        rid = _blip_embed_rid(child)
                        if not rid or rid in seen_rids:
                            continue
                        seen_rids.add(rid)
                        image = _load_office_image(
                            zf, names, rel_targets.get(rid, ""), budget, images
                        )
                        if image is not None:
                            markers.append(build_marker(image))
                paragraph = "".join(text_parts).strip()
                if markers:
                    paragraph = (paragraph + "\n" if paragraph else "") + "\n".join(markers)
                if paragraph:
                    lines.append(paragraph)
            slides.append("\n".join(lines))

    return PptxRich(slides=tuple(slides), collection=_collection_from(budget, images))


_SLIDE_MEMBER_PATTERN = re.compile(r"ppt/slides/slide\d+\.xml")


def _natural_slide_key(name: str) -> list[int]:
    digits = re.findall(r"\d+", posixpath.basename(name))
    return [int(digits[0])] if digits else [0]


def _rels_for(member: str) -> str:
    directory, filename = posixpath.split(member)
    return posixpath.join(directory, "_rels", filename + ".rels")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def extract_pdf_images(data: bytes, *, budget: ImageBudget | None = None) -> PdfImages:
    """Raster images per page via PyMuPDF, deduplicated across the document.

    Running headers/footers embed the same logo xref on every page. Store its
    bytes once, but map that image to every page where it appears.

    ``budget`` defaults to the chat-attachment caps (unchanged behaviour). When
    it carries a non-zero ``max_images_per_page``, a page stops admitting once
    it hits that many images and the rest of that page's candidates are counted
    as page-budget skips. Reused xrefs still count toward the per-page cap,
    but do not consume the document-wide image or byte budgets again.
    """
    try:
        import pymupdf
    except ImportError:
        return PdfImages()

    budget = budget or ImageBudget()
    images: list[EmbeddedImage] = []
    page_map: list[tuple[int, tuple[int, ...]]] = []
    xref_to_index: dict[int, int] = {}
    rejected_xrefs: set[int] = set()

    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page_number, page in enumerate(doc, 1):
                indices: list[int] = []
                admitted_on_page = 0
                seen_on_page: set[int] = set()
                for info in page.get_images(full=True):
                    xref = info[0]
                    if xref in seen_on_page:
                        continue
                    seen_on_page.add(xref)
                    if budget.max_images_per_page and (
                        admitted_on_page >= budget.max_images_per_page
                    ):
                        budget.skipped_page_budget += 1
                        continue
                    if xref in xref_to_index:
                        indices.append(xref_to_index[xref])
                        admitted_on_page += 1
                        continue
                    if xref in rejected_xrefs:
                        continue
                    rejected_xrefs.add(xref)
                    try:
                        extracted = doc.extract_image(xref)
                    except Exception:
                        continue
                    raw = extracted.get("image") or b""
                    if (
                        int(extracted.get("width") or 0) < 64
                        or int(extracted.get("height") or 0) < 64
                    ):
                        continue
                    ext = _normalise_ext("." + (extracted.get("ext") or ""))
                    if ext in {".emf", ".wmf"}:
                        budget.register_vector_skip()
                        continue
                    if ext not in SUPPORTED_IMAGE_EXTENSIONS:
                        budget.register_other_skip()
                        continue
                    admitted = budget.try_admit(ext, raw)
                    if admitted is not None:
                        images.append(admitted)
                        xref_to_index[xref] = len(images) - 1
                        indices.append(xref_to_index[xref])
                        admitted_on_page += 1
                if indices:
                    page_map.append((page_number, tuple(indices)))
    except Exception:
        logger.warning("pdf image extraction failed", exc_info=True)
        return PdfImages()

    return PdfImages(collection=_collection_from(budget, images), page_map=tuple(page_map))


__all__ = [
    "EmbeddedImage",
    "ImageBudget",
    "ImageCollection",
    "DocxRich",
    "PptxRich",
    "PdfImages",
    "MAX_IMAGES_PER_DOC",
    "SUPPORTED_IMAGE_EXTENSIONS",
    "build_marker",
    "find_markers",
    "image_index_from_name",
    "reading_image_budget",
    "extract_docx_rich",
    "extract_pptx_rich",
    "extract_pdf_images",
]
