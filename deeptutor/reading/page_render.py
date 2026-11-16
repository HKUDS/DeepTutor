"""Whole-page raster fallback for the reading viewport.

Slide-exported PDFs draw their figures as vectors, so ``page.get_images()``
yields only shadow fragments and a vision model has nothing to read. When the
open page carries enough vector primitives, rasterising the whole page — figure
labels and all — into one JPEG is the only way a vision model sees the figure.

When the reader marks an area of a page (a scanned exam task, a sub-figure, a
formula, a table), only that clip is rasterised, at a higher DPI than the
whole-page render, so the model reads exactly what the question points at.

The rules live here, in the reading engine, rather than in
``services.session``: the per-turn attachment injection and the capability's
viewport narration share one implementation, and the reading layer never has to
import back into ``services``. Best-effort throughout — every failure degrades
to "no render" so a page quirk can never break a turn.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

#: Page raster DPI for the "whole page is drawn" fallback. 110 dpi at JPEG
#: quality 82 measures ~132 KB / 60-80 ms per page — small enough to ride along
#: with every turn, sharp enough to read the figure labels.
PAGE_RENDER_DPI = 110

#: A page with at least this many vector drawing objects is a diagram page
#: (slide exports hit 40+; prose-only pages stay at 0-7), so a full-page
#: render adds signal instead of duplicating the text channel.
PAGE_RENDER_MIN_DRAWINGS = 8


def page_render_record(material_id: str, locator: int) -> dict | None:
    """Render the locator's page to a JPEG when it is mainly drawn.

    Returns one attachment record shaped like the session's embedded-image
    records, or ``None`` when the material has no raw PDF, the locator is out
    of range, or the page has too few vector primitives (prose-only pages are
    already covered by the text channel, so rendering them is wasted work).
    Any failure logs and returns ``None``.
    """
    try:
        if not material_id or locator <= 0:
            return None
        import base64

        import pymupdf

        from deeptutor.reading import ReadingStore

        raw = ReadingStore().raw_path(material_id)
        if raw is None or raw.suffix.lower() != ".pdf" or not raw.is_file():
            return None
        with pymupdf.open(raw) as doc:
            if not 1 <= locator <= doc.page_count:
                return None
            page = doc[locator - 1]
            if len(page.get_drawings()) < PAGE_RENDER_MIN_DRAWINGS:
                return None
            pixmap = page.get_pixmap(dpi=PAGE_RENDER_DPI)
            image_bytes = pixmap.tobytes("jpeg", jpg_quality=82)
        return {
            "type": "image",
            "url": "",
            "base64": base64.b64encode(image_bytes).decode("ascii"),
            "filename": f"{raw.stem}-page-{locator}.jpg",
            "mime_type": "image/jpeg",
            "id": f"rp-{material_id[:12]}-{locator}",
            "embedded": True,
        }
    except Exception:
        logger.warning("reading page render failed", exc_info=True)
        return None


#: Upper DPI for a marked-area crop. A small area (one formula line, a table
#: cell, handwriting) is rendered this sharp so a vision model can read it; the
#: full-page render's 110 dpi is often too coarse for that.
REGION_RENDER_MAX_DPI = 300

#: Pixel budget for one crop (~1.6 MP, e.g. 1600x1000). A large area is
#: rendered at a lower DPI instead of a larger bitmap.
REGION_RENDER_MAX_PIXELS = 1_600_000

#: Longest side of a crop in pixels. Vision models downscale beyond roughly
#: this anyway, so sending more only costs bytes.
REGION_RENDER_MAX_SIDE = 2000

#: Byte budget for one encoded crop. A dense scan that still exceeds it after
#: the pixel budget is re-rendered at a lower DPI.
REGION_RENDER_MAX_BYTES = 1_500_000

#: Smallest side of a marked area as a share of the page. Anything smaller is
#: an accidental click or tap rather than a region.
REGION_MIN_SIDE = 0.01


def normalise_region(value: object) -> dict | None:
    """Validate a marked page area from the reader.

    The reader sends ``{"locator": n, "box": [x0, y0, x1, y1]}`` in
    page-normalised coordinates (fractions of the displayed page, origin top
    left). Returns the same shape with the box ordered, clamped to ``[0, 1]``
    and rounded, or ``None`` when the value is not a usable area: wrong shape,
    a non-positive locator, non-finite numbers, or a side shorter than
    :data:`REGION_MIN_SIDE`. Whether the locator exists in the material is
    checked when the crop is rendered, which is where the page count is known.
    """
    if not isinstance(value, dict):
        return None
    locator = value.get("locator")
    if isinstance(locator, bool) or not isinstance(locator, (int, float)):
        return None
    if not math.isfinite(locator) or locator != int(locator) or locator <= 0:
        return None
    box = value.get("box")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    numbers: list[float] = []
    for item in box:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        number = float(item)
        if not math.isfinite(number):
            return None
        numbers.append(min(1.0, max(0.0, number)))
    x0, x1 = sorted((numbers[0], numbers[2]))
    y0, y1 = sorted((numbers[1], numbers[3]))
    if x1 - x0 < REGION_MIN_SIDE or y1 - y0 < REGION_MIN_SIDE:
        return None
    return {
        "locator": int(locator),
        "box": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)],
    }


def region_render_dpi(width_pt: float, height_pt: float) -> int:
    """DPI that keeps a ``width_pt`` x ``height_pt`` crop inside the budgets.

    As sharp as :data:`REGION_RENDER_MAX_DPI` allows, lowered until the crop
    fits both the pixel budget and the longest-side cap.
    """
    width_pt = max(width_pt, 1.0)
    height_pt = max(height_pt, 1.0)
    by_pixels = 72.0 * math.sqrt(REGION_RENDER_MAX_PIXELS / (width_pt * height_pt))
    by_side = 72.0 * REGION_RENDER_MAX_SIDE / max(width_pt, height_pt)
    return max(1, int(min(REGION_RENDER_MAX_DPI, by_pixels, by_side)))


def _raw_pdf(material_id: str):
    from deeptutor.reading import ReadingStore

    raw = ReadingStore().raw_path(material_id)
    if raw is None or raw.suffix.lower() != ".pdf" or not raw.is_file():
        return None
    return raw


def region_render_record(material_id: str, locator: int, box: list[float]) -> dict | None:
    """Render only the marked area of a PDF page to a JPEG attachment.

    ``box`` is page-normalised (see :func:`normalise_region`) against the page
    as displayed, which is PyMuPDF's ``page.rect`` (rotation applied, crop box
    at the origin) — the same frame pdf.js lays the page out in. The crop is
    rendered server-side from the stored raw PDF, so it always matches the
    stored revision and the client never uploads pixels. Returns a record
    shaped like :func:`page_render_record`'s, or ``None`` when the material is
    not a PDF, the locator is out of range or anything fails.
    """
    try:
        region = normalise_region({"locator": locator, "box": box})
        if not material_id or region is None:
            return None
        import base64

        import pymupdf

        raw = _raw_pdf(material_id)
        if raw is None:
            return None
        x0, y0, x1, y1 = region["box"]
        with pymupdf.open(raw) as doc:
            if not 1 <= locator <= doc.page_count:
                return None
            page = doc[locator - 1]
            rect = page.rect
            clip = pymupdf.Rect(
                rect.x0 + x0 * rect.width,
                rect.y0 + y0 * rect.height,
                rect.x0 + x1 * rect.width,
                rect.y0 + y1 * rect.height,
            )
            dpi = region_render_dpi(clip.width, clip.height)
            image_bytes = b""
            for _ in range(3):
                pixmap = page.get_pixmap(clip=clip, dpi=dpi)
                image_bytes = pixmap.tobytes("jpeg", jpg_quality=85)
                if len(image_bytes) <= REGION_RENDER_MAX_BYTES or dpi <= 72:
                    break
                dpi = max(72, int(dpi * 0.7))
            if len(image_bytes) > REGION_RENDER_MAX_BYTES:
                return None
        return {
            "type": "image",
            "url": "",
            "base64": base64.b64encode(image_bytes).decode("ascii"),
            "filename": f"{raw.stem}-page-{locator}-area.jpg",
            "mime_type": "image/jpeg",
            "id": f"rr-{material_id[:12]}-{locator}",
            "embedded": True,
        }
    except Exception:
        logger.warning("reading region render failed", exc_info=True)
        return None


def region_has_render(material_id: str, locator: int) -> bool:
    """Whether a marked area on ``locator`` can be cropped (probe only).

    Same gate as :func:`region_render_record` — a raw PDF with that page —
    without rasterising, so the capability only tells the model about a crop
    the turn actually carries. Failures return ``False``.
    """
    try:
        if not material_id or locator <= 0:
            return False
        import pymupdf

        raw = _raw_pdf(material_id)
        if raw is None:
            return False
        with pymupdf.open(raw) as doc:
            return 1 <= locator <= doc.page_count
    except Exception:
        logger.warning("reading region render probe failed", exc_info=True)
        return False


def page_has_render(material_id: str, locator: int) -> bool:
    """Whether the locator's page qualifies for a full-page render (probe only).

    Same gate as :func:`page_render_record` — raw PDF and enough vector
    primitives — without paying the rasterisation, so capability narration can
    mention the page image cheaply. Failures return ``False``.
    """
    try:
        if not material_id or locator <= 0:
            return False
        import pymupdf

        from deeptutor.reading import ReadingStore

        raw = ReadingStore().raw_path(material_id)
        if raw is None or raw.suffix.lower() != ".pdf" or not raw.is_file():
            return False
        with pymupdf.open(raw) as doc:
            if not 1 <= locator <= doc.page_count:
                return False
            return len(doc[locator - 1].get_drawings()) >= PAGE_RENDER_MIN_DRAWINGS
    except Exception:
        logger.warning("reading page render probe failed", exc_info=True)
        return False
