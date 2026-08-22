"""Export a material together with the marks the reader made on it.

Two shapes, because they answer different needs:

* **PDF** (``fmt="pdf"``) — the original file with *real* PDF annotations written
  in via PyMuPDF. The point is portability: the result opens in Preview, Acrobat
  or Chrome with the highlights and notes intact, so a user's reading survives
  leaving DeepTutor. Only available for materials that kept their raw bytes.
* **Markdown** (``fmt="markdown"``) — the marks themselves, in locator order,
  each with its quote and note. Works for every format, and is what a user
  actually wants to paste into their own notes.

Coordinate handling is the one subtle part. Annotations are stored normalised
against the *visual* unit box (origin top-left, y down) because that is what the
browser measured. ``page.rect`` is the same visual box — PyMuPDF already applies
``/Rotate`` — so scaling by its width/height lands the rectangle where the user
drew it. Writing an annotation, however, addresses the page's *unrotated* space,
so a rotated page needs ``derotation_matrix`` applied on the way in. Skipping
that step is what makes highlights land sideways on scanned documents.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Literal

from deeptutor.reading.models import (
    ANNOTATION_COLORS,
    DEFAULT_ANNOTATION_COLOR,
    Annotation,
    MaterialManifest,
    ReadingError,
)
from deeptutor.reading.store import ReadingStore

logger = logging.getLogger(__name__)

ExportFormat = Literal["auto", "pdf", "markdown"]

# Notes attached to a whole unit have no geometry; anchor their sticky icon a
# little inside the top-left corner so it is visible but not clipped.
_NOTE_FALLBACK_INSET = 24.0


@dataclass(frozen=True, slots=True)
class ExportResult:
    """A ready-to-download artefact."""

    filename: str
    media_type: str
    data: bytes

    @property
    def byte_size(self) -> int:
        return len(self.data)


def export_material(
    store: ReadingStore,
    material_id: str,
    *,
    fmt: ExportFormat = "auto",
) -> ExportResult:
    """Export *material_id*, choosing the richest available shape for ``auto``."""
    manifest = store.manifest(material_id)
    annotations = store.annotations(material_id)

    resolved = fmt
    if resolved == "auto":
        resolved = "pdf" if manifest.has_raw_view else "markdown"
    if resolved == "pdf" and not manifest.has_raw_view:
        raise ReadingError(
            f"{manifest.filename} has no original PDF to annotate — export it as Markdown instead."
        )

    if resolved == "pdf":
        return _export_pdf(store, manifest, annotations)
    return _export_markdown(store, manifest, annotations)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _export_pdf(
    store: ReadingStore,
    manifest: MaterialManifest,
    annotations: list[Annotation],
) -> ExportResult:
    raw_path = store.raw_path(manifest.material_id)
    if raw_path is None or not raw_path.is_file():
        raise ReadingError(f"{manifest.filename}: the original file is no longer available")

    stem = _stem(manifest.filename)
    filename = f"{stem}-annotated.pdf"

    if not annotations:
        # Nothing to draw — hand back the original bytes rather than paying a
        # re-serialisation that could only degrade the file.
        return ExportResult(
            filename=filename,
            media_type="application/pdf",
            data=raw_path.read_bytes(),
        )

    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - pymupdf is a core dep
        raise ReadingError("Annotated PDF export needs PyMuPDF") from exc

    by_locator: dict[int, list[Annotation]] = {}
    for annotation in annotations:
        by_locator.setdefault(annotation.locator, []).append(annotation)

    try:
        with pymupdf.open(raw_path) as doc:
            for locator, rows in sorted(by_locator.items()):
                if not 1 <= locator <= doc.page_count:
                    continue
                page = doc[locator - 1]
                for annotation in rows:
                    _draw_annotation(pymupdf, page, annotation)
            data = doc.tobytes(deflate=True, garbage=3)
    except ReadingError:
        raise
    except Exception as exc:
        raise ReadingError(f"{manifest.filename}: failed to write annotations ({exc})") from exc

    return ExportResult(filename=filename, media_type="application/pdf", data=data)


def _draw_annotation(pymupdf, page, annotation: Annotation) -> None:
    """Write one stored annotation onto *page* as a native PDF annotation."""
    rects = _page_rects(pymupdf, page, annotation)
    colour = ANNOTATION_COLORS.get(annotation.color, ANNOTATION_COLORS[DEFAULT_ANNOTATION_COLOR])
    body = _annotation_body(annotation)

    try:
        if annotation.kind == "note" or not rects:
            point = (
                rects[0].tl
                if rects
                else pymupdf.Point(
                    page.rect.x0 + _NOTE_FALLBACK_INSET,
                    page.rect.y0 + _NOTE_FALLBACK_INSET,
                )
            )
            annot = page.add_text_annot(point, body or annotation.quote or "Note")
        elif annotation.kind == "underline":
            annot = page.add_underline_annot(rects)
        else:
            annot = page.add_highlight_annot(rects)
        if annotation.kind != "note":
            annot.set_colors(stroke=colour)
            if body:
                annot.set_info(content=body)
        annot.update()
    except Exception:
        # One bad rectangle must not lose the other marks on the page.
        logger.warning(
            "Skipped annotation %s on locator %s during export",
            annotation.annotation_id,
            annotation.locator,
            exc_info=True,
        )


def _page_rects(pymupdf, page, annotation: Annotation) -> list:
    """Stored normalised rects → PyMuPDF rects in the page's own space."""
    visual = page.rect
    width, height = visual.width, visual.height
    if width <= 0 or height <= 0:
        return []

    derotate = page.derotation_matrix if page.rotation else None
    out = []
    for rect in annotation.rects:
        box = rect.clamped()
        if box.is_degenerate:
            continue
        absolute = pymupdf.Rect(
            visual.x0 + box.x0 * width,
            visual.y0 + box.y0 * height,
            visual.x0 + box.x1 * width,
            visual.y0 + box.y1 * height,
        )
        if derotate is not None:
            absolute = absolute * derotate
        out.append(absolute)
    return out


def _annotation_body(annotation: Annotation) -> str:
    """The text carried inside the PDF annotation's popup."""
    note = (annotation.note or "").strip()
    if note:
        return note
    return ""


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _export_markdown(
    store: ReadingStore,
    manifest: MaterialManifest,
    annotations: list[Annotation],
) -> ExportResult:
    unit_word = manifest.unit.capitalize()
    lines: list[str] = [f"# {manifest.title or _stem(manifest.filename)}", ""]
    lines.append(f"*{manifest.filename} — {manifest.unit_count} {manifest.unit}s*")
    lines.append("")

    if not annotations:
        lines.append("_No annotations yet._")
        lines.append("")
    else:
        current: int | None = None
        for annotation in annotations:
            if annotation.locator != current:
                current = annotation.locator
                lines.append(f"## {unit_word} {current}")
                lines.append("")
            quote = " ".join((annotation.quote or "").split())
            if quote:
                lines.append(f"> {quote}")
                lines.append("")
            note = (annotation.note or "").strip()
            if note:
                for note_line in note.splitlines():
                    lines.append(note_line.rstrip())
                lines.append("")
            if not quote and not note:
                lines.append(f"_({annotation.kind} with no text)_")
                lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    return ExportResult(
        filename=f"{_stem(manifest.filename)}-annotations.md",
        media_type="text/markdown; charset=utf-8",
        data=text.encode("utf-8"),
    )


def _stem(filename: str) -> str:
    from pathlib import Path

    stem = Path(filename or "material").stem.strip()
    return stem or "material"


__all__ = ["ExportFormat", "ExportResult", "export_material"]
