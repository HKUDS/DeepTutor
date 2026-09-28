"""Vector-diagram pages must ride along as a full-page render.

Slide-exported PDFs draw their figures as vectors, so a vision model sees
nothing but shadow fragments from ``page.get_images()``. These tests build real
PDFs with PyMuPDF and exercise the store-isolated helpers: a drawn page yields
a JPEG render record (leading the attachment list), a prose-only page yields
none, and the total never exceeds ``READING_VIEWPORT_MAX_IMAGES``.

The store is isolated by pointing ``DEEPTUTOR_HOME`` at a temp dir and resetting
the path-service singleton, so the helpers' real ``ReadingStore()`` resolution
path runs rather than a hand-injected store.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from deeptutor.reading.page_render import page_has_render, page_render_record
from deeptutor.services.path_service import PathService
from deeptutor.services.session._turn_runtime_shared import (
    READING_VIEWPORT_MAX_IMAGES,
    _reading_viewport_image_attachments,
    _reading_viewport_page_render,
)

pymupdf = pytest.importorskip("pymupdf")


@pytest.fixture
def reading_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A real per-user store rooted in a temp DEEPTUTOR_HOME."""
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


def _png_bytes(seed: int) -> bytes:
    """A noisy PNG above the min-bytes gate so extraction keeps it."""
    import io
    import random

    from PIL import Image as PILImage

    rng = random.Random(seed)
    raw = bytes(rng.randrange(256) for _ in range(150 * 120 * 3))
    image = PILImage.frombytes("RGB", (150, 120), raw)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _prose(label: str) -> str:
    return (
        f"{label} This page carries a real text layer so the density check "
        "accepts it as prose rather than a figure-label scan. " * 3
    )


def _draw_diagram(page) -> None:
    """Ten vector primitives — comfortably past the render gate of 8."""
    for index in range(4):
        page.draw_line(pymupdf.Point(72, 120 + index * 12), pymupdf.Point(300, 120 + index * 12))
    for index in range(3):
        page.draw_rect(pymupdf.Rect(72, 220 + index * 34, 220, 244 + index * 34))
    for index in range(3):
        page.draw_circle(pymupdf.Point(420, 220 + index * 34), 14)


def _build_pdf(path: Path, *, embedded_images: int = 0) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 60), _prose("Page one."))
    _draw_diagram(page)
    for index in range(embedded_images):
        rect = pymupdf.Rect(72, 380 + index * 60, 260, 440 + index * 60)
        page.insert_image(rect, stream=_png_bytes(seed=index + 1))
    text_page = doc.new_page(width=612, height=792)
    text_page.insert_textbox(pymupdf.Rect(72, 72, 540, 600), _prose("Page two."), fontsize=11)
    doc.save(str(path))
    doc.close()


def _ingest_deck(reading_home: Path, *, embedded_images: int = 0):
    from deeptutor.reading import ReadingStore

    source = reading_home / "day04_potential.pdf"
    _build_pdf(source, embedded_images=embedded_images)
    return ReadingStore().ingest(source)


def _write_media_index(store, material_id: str, count: int) -> list[str]:
    """Write *count* embedded-image rows directly into the store index.

    The reading ingest caps extraction at 4 images per page, which is exactly
    the cap under test, so the index is seeded by hand to prove truncation.
    """
    material_dir = store._dir(material_id)
    media_dir = material_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    names = [f"image-{index:02d}.png" for index in range(1, count + 1)]
    rows = []
    for name in names:
        (media_dir / name).write_bytes(b"png-bytes")
        rows.append({"name": name, "locator": 1, "mime": "image/png", "bytes": 9})
    (material_dir / "media.json").write_text(json.dumps(rows), encoding="utf-8")
    return names


def test_drawn_page_renders_and_leads_attachments(reading_home: Path) -> None:
    manifest = _ingest_deck(reading_home, embedded_images=1)
    material_id = manifest.material_id

    record = page_render_record(material_id, 1)

    assert record is not None
    assert record["mime_type"] == "image/jpeg"
    assert record["type"] == "image"
    assert "-page-" in record["filename"]
    assert record["filename"].endswith("-page-1.jpg")
    assert record["id"].startswith("rp-")
    assert record["url"] == "" and record["embedded"] is True
    decoded = base64.b64decode(record["base64"])
    assert decoded[:2] == b"\xff\xd8"  # JPEG SOI marker

    attachments = _reading_viewport_image_attachments(material_id, {"locator": 1})
    assert attachments
    assert attachments[0]["id"] == record["id"]
    assert len(attachments) <= READING_VIEWPORT_MAX_IMAGES
    # The page's own embedded figure follows the render.
    assert any(item["id"].startswith("rv-") for item in attachments[1:])


def test_prose_only_page_has_no_render(reading_home: Path) -> None:
    manifest = _ingest_deck(reading_home)
    material_id = manifest.material_id

    assert page_render_record(material_id, 2) is None
    attachments = _reading_viewport_image_attachments(material_id, {"locator": 2})
    assert all(item["id"].startswith("rv-") for item in attachments)


def test_attachments_truncate_to_max_with_render_first(reading_home: Path) -> None:
    from deeptutor.reading import ReadingStore

    source = reading_home / "day04_potential.pdf"
    _build_pdf(source)
    store = ReadingStore()
    manifest = store.ingest(source)
    _write_media_index(store, manifest.material_id, count=5)

    attachments = _reading_viewport_image_attachments(manifest.material_id, {"locator": 1})

    assert len(attachments) == READING_VIEWPORT_MAX_IMAGES == 4
    assert attachments[0]["id"].startswith("rp-")
    embedded = [item for item in attachments if item["id"].startswith("rv-")]
    assert len(embedded) == READING_VIEWPORT_MAX_IMAGES - 1


def test_has_render_matches_render_gate(reading_home: Path) -> None:
    manifest = _ingest_deck(reading_home)
    material_id = manifest.material_id

    assert page_has_render(material_id, 1) is True
    assert page_has_render(material_id, 2) is False


def test_reading_layer_and_service_wrappers_agree(reading_home: Path) -> None:
    """The reading-layer API and the session wrappers must be one behaviour."""
    manifest = _ingest_deck(reading_home)
    material_id = manifest.material_id

    native = page_render_record(material_id, 1)
    wrapped = _reading_viewport_page_render(material_id, 1)
    assert native is not None and wrapped is not None
    assert native["id"] == wrapped["id"]
    assert native["filename"] == wrapped["filename"]
    assert native["base64"] == wrapped["base64"]
    assert page_has_render(material_id, 1) is True
    assert page_has_render(material_id, 2) is False
    assert _reading_viewport_page_render(material_id, 2) is None


def test_invalid_inputs_do_not_raise(reading_home: Path) -> None:
    manifest = _ingest_deck(reading_home)
    material_id = manifest.material_id

    # Bad material ids.
    assert page_render_record("", 1) is None
    assert page_render_record("zzz", 1) is None
    assert page_has_render("", 1) is False
    assert page_has_render("zzz", 1) is False
    assert _reading_viewport_page_render("", 1) is None
    assert _reading_viewport_page_render("zzz", 1) is None
    assert page_has_render("", 1) is False
    assert page_has_render("zzz", 1) is False
    assert _reading_viewport_image_attachments("", {"locator": 1}) == []

    # Out-of-range locators.
    assert page_render_record(material_id, 0) is None
    assert page_render_record(material_id, 999) is None
    assert page_has_render(material_id, 0) is False
    assert page_has_render(material_id, 999) is False
    assert _reading_viewport_page_render(material_id, 0) is None
    assert _reading_viewport_page_render(material_id, 999) is None
    assert page_has_render(material_id, 0) is False
    assert page_has_render(material_id, 999) is False
    assert _reading_viewport_image_attachments(material_id, {"locator": 999}) == []
    assert _reading_viewport_image_attachments(material_id, {}) == []
