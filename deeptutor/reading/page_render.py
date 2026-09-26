"""Whole-page raster fallback for the reading viewport.

Slide-exported PDFs draw their figures as vectors, so ``page.get_images()``
yields only shadow fragments and a vision model has nothing to read. When the
open page carries enough vector primitives, rasterising the whole page — figure
labels and all — into one JPEG is the only way a vision model sees the figure.

The rules live here, in the reading engine, rather than in
``services.session``: the per-turn attachment injection and the capability's
viewport narration share one implementation, and the reading layer never has to
import back into ``services``. Best-effort throughout — every failure degrades
to "no render" so a page quirk can never break a turn.
"""

from __future__ import annotations

import logging

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
