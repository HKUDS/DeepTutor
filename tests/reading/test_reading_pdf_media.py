"""PDF reading ingest must surface embedded images as locator-pinned media.

Builds small real PDFs with PyMuPDF so the assertions exercise the actual
``extract_material`` path: markers appended at each page's text tail, and the
matching ``MediaItem`` records carrying the page locator.
"""

from __future__ import annotations

import io
import random

import pytest

from deeptutor.reading.extract import extract_material
from deeptutor.utils.document_images import find_markers


def _png_bytes(size: tuple[int, int], seed: int) -> bytes:
    """A noisy PNG above the min-bytes and 64px minimum-size gates."""
    rng = random.Random(seed)
    raw = bytes(rng.randrange(256) for _ in range(size[0] * size[1] * 3))
    from PIL import Image as PILImage

    image = PILImage.frombytes("RGB", size, raw)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _prose(label: str) -> str:
    return (
        f"{label} This page carries a real text layer so the density check "
        "accepts it as prose rather than a figure-label scan. " * 3
    )


def _build_pdf(path, images_per_page: list[int]) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for page_index, image_count in enumerate(images_per_page, start=1):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 60), _prose(f"Page {page_index}"))
        for image_index in range(image_count):
            rect = pymupdf.Rect(72, 100 + image_index * 90, 240, 180 + image_index * 90)
            page.insert_image(
                rect, stream=_png_bytes((150, 120), seed=page_index * 10 + image_index)
            )
    doc.save(str(path))
    doc.close()


def test_pdf_images_become_locator_pinned_media(tmp_path) -> None:
    pdf_path = tmp_path / "figures.pdf"
    _build_pdf(pdf_path, images_per_page=[2, 1, 0])

    extraction = extract_material(pdf_path)

    assert len(extraction.units) == 3
    assert extraction.extractor == "pymupdf"

    assert "[图片" in extraction.units[0]
    assert "[图片" in extraction.units[1]
    assert "[图片" not in extraction.units[2]

    locator_counts: dict[int, int] = {}
    for item in extraction.media:
        locator_counts[item.locator] = locator_counts.get(item.locator, 0) + 1
    assert locator_counts == {1: 2, 2: 1}

    # Marker names and media names agree one-for-one on each page.
    for locator in (1, 2):
        marker_names = [name for _, name in find_markers(extraction.units[locator - 1])]
        media_names = [item.name for item in extraction.media if item.locator == locator]
        assert marker_names == media_names
        assert len(media_names) == locator_counts[locator]


def test_reused_pdf_image_is_mapped_to_each_page(tmp_path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pdf_path = tmp_path / "repeated-figure.pdf"
    image = _png_bytes((150, 120), seed=7)
    doc = pymupdf.open()
    for page_index in range(1, 4):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 60), _prose(f"Page {page_index}"))
        page.insert_image(pymupdf.Rect(72, 100, 240, 180), stream=image)
    doc.save(str(pdf_path))
    doc.close()

    extraction = extract_material(pdf_path)

    assert len(extraction.units) == 3
    assert [item.locator for item in extraction.media] == [1, 2, 3]
    assert len({item.name for item in extraction.media}) == 1
    for unit in extraction.units:
        assert find_markers(unit) == [(1, extraction.media[0].name)]


def test_text_only_pdf_has_no_media_and_no_marker(tmp_path) -> None:
    pdf_path = tmp_path / "plain.pdf"
    _build_pdf(pdf_path, images_per_page=[0, 0])

    extraction = extract_material(pdf_path)

    assert len(extraction.units) == 2
    assert extraction.media == ()
    assert all("[图片" not in unit for unit in extraction.units)
