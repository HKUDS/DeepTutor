"""Opt-in working copies for abnormally small, high-density scanned pages.

The source is never rewritten. This preserves compressed image/soft-mask
streams, not arbitrary PDF signatures or interactive-document semantics.
Rotated, cropped, annotated, vector, and non-default UserUnit pages are skipped.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import logging
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .config import MinerUConfig, MinerUError

POLICY = "tiny-scan-v1"
logger = logging.getLogger(__name__)


def _plan(source: Path) -> list[tuple[int, float]]:
    try:
        import pymupdf
    except ImportError as exc:
        raise MinerUError(
            "Tiny-scan normalization requires PyMuPDF. Install the "
            "deeptutor[parse-pymupdf4llm] extra or disable normalize_tiny_scans."
        ) from exc

    changes: list[tuple[int, float]] = []
    with pymupdf.open(source) as doc:
        if doc.is_encrypted:
            return changes
        for index, page in enumerate(doc):
            rect = page.rect
            if (
                page.rotation
                or page.cropbox != page.mediabox
                or rect.x0 != 0
                or rect.y0 != 0
                or not 0 < min(rect.width, rect.height)
                or max(rect.width, rect.height) >= 144
                or not 0.4 <= rect.width / rect.height <= 2.5
                or page.get_text().strip()
                or page.get_drawings()
                or page.first_annot is not None
                or page.first_widget is not None
                or page.get_links()
            ):
                continue
            unit = doc.xref_get_key(page.xref, "UserUnit")
            if unit[0] != "null" and float(unit[1]) != 1:
                continue
            for image in page.get_image_info(xrefs=True):
                box = pymupdf.Rect(image["bbox"])
                if box.is_empty or image.get("xref", 0) == 0:
                    continue
                coverage = (box & rect).get_area() / rect.get_area()
                density = min(image["width"], image["height"]) * 72 / max(box.width, box.height)
                if (
                    min(image["width"], image["height"]) >= 1000
                    and coverage >= 0.8
                    and density >= 1200
                ):
                    changes.append((index, 768 / max(rect.width, rect.height)))
                    break
    return changes


def _image_streams(path: Path) -> list[list[str]]:
    import pymupdf

    with pymupdf.open(path) as doc:
        pages = []
        for page in doc:
            streams = []
            for item in page.get_images(full=True):
                for xref in item[:2]:
                    if xref:
                        streams.append(hashlib.sha256(doc.xref_stream_raw(xref)).hexdigest())
            pages.append(sorted(streams))
        return pages


@contextmanager
def working_copy(
    source: Path,
    output: Path,
    config: MinerUConfig,
    on_progress: Callable[[str], None] | None = None,
) -> Iterator[Path]:
    url = urlsplit(config.api_base_url)
    if (
        not config.normalize_tiny_scans
        or not config.is_cloud
        or source.suffix.lower() != ".pdf"
        or url.scheme != "https"
        or url.hostname not in {"mineru.net", "www.mineru.net"}
    ):
        yield source
        return
    changes = _plan(source)
    if not changes:
        yield source
        return

    from pypdf import PdfReader, PdfWriter

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mineru-normalized-", dir=output.parent) as tmp:
        target = Path(tmp) / source.name
        before = _image_streams(source)
        with PdfReader(source) as reader:
            writer = PdfWriter()
            try:
                writer.clone_document_from_reader(reader)
                for index, factor in changes:
                    writer.pages[index].scale_by(factor)
                writer.write(target)
            finally:
                writer.close()
        if _image_streams(target) != before:
            raise MinerUError("PDF normalization changed image streams; refusing upload")
        if on_progress:
            try:
                on_progress(
                    f"MinerU: normalized {len(changes)} tiny scanned page(s) in a temporary copy"
                )
            except Exception:
                logger.debug("Normalization progress callback failed", exc_info=True)
        yield target
