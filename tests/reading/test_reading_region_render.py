"""A marked page area rides along as a crop of exactly that area (#2741).

Scanned pages, figures, formulas and handwriting have no text layer to select,
so the reader lets the learner draw a rectangle instead. These tests build real
PDFs with PyMuPDF and exercise the store-isolated helpers: the region is
validated, only the clip is rendered (correct page, correct rectangle, within
the pixel budget), and its crop leads the turn's attachments.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

from deeptutor.reading.page_render import (
    REGION_RENDER_MAX_DPI,
    REGION_RENDER_MAX_PIXELS,
    REGION_RENDER_MAX_SIDE,
    normalise_region,
    region_has_render,
    region_render_dpi,
    region_render_record,
)
from deeptutor.services.path_service import PathService
from deeptutor.services.session._turn_runtime_shared import (
    READING_VIEWPORT_MAX_IMAGES,
    _reading_viewport,
    _reading_viewport_image_attachments,
)

pymupdf = pytest.importorskip("pymupdf")
PILImage = pytest.importorskip("PIL.Image")

RED = (1, 0, 0)
BLUE = (0, 0, 1)


@pytest.fixture
def reading_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A real per-user store rooted in a temp DEEPTUTOR_HOME."""
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


def _ingest(path: Path):
    from deeptutor.reading import ReadingStore

    return ReadingStore().ingest(path)


def _two_block_pdf(path: Path, *, rotate: int = 0) -> None:
    """Page 1: a red block top-left and a blue block bottom-right; page 2 prose."""
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((72, 40), "Two coloured blocks for the crop test.")
    page.draw_rect(pymupdf.Rect(60, 100, 240, 220), color=RED, fill=RED)
    page.draw_rect(pymupdf.Rect(360, 580, 540, 700), color=BLUE, fill=BLUE)
    if rotate:
        page.set_rotation(rotate)
    second = doc.new_page(width=600, height=800)
    second.insert_textbox(pymupdf.Rect(72, 72, 540, 600), "Page two prose. " * 20)
    doc.save(str(path))
    doc.close()


def _decode(record: dict | None):
    assert record is not None
    raw = base64.b64decode(record["base64"])
    assert raw[:2] == b"\xff\xd8"  # JPEG SOI marker
    return PILImage.open(io.BytesIO(raw)).convert("RGB")


def _share(image, colour: str) -> float:
    """Share of the crop's pixels that are clearly ``colour``."""
    pixels = list(image.getdata())

    def is_colour(pixel: tuple[int, int, int]) -> bool:
        r, g, b = pixel
        if colour == "red":
            return r > 180 and g < 80 and b < 80
        return b > 180 and r < 80 and g < 80

    return sum(1 for pixel in pixels if is_colour(pixel)) / len(pixels)


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------


def test_region_is_ordered_clamped_and_rounded() -> None:
    assert normalise_region({"locator": 3, "box": [0.6, 0.9, 0.1, 0.2]}) == {
        "locator": 3,
        "box": [0.1, 0.2, 0.6, 0.9],
    }
    assert normalise_region({"locator": 1, "box": [-0.5, 0.123456, 1.7, 0.5]}) == {
        "locator": 1,
        "box": [0.0, 0.1235, 1.0, 0.5],
    }
    # A whole-number float locator is still a page.
    whole = normalise_region({"locator": 2.0, "box": [0, 0, 1, 1]})
    assert whole is not None and whole["locator"] == 2


@pytest.mark.parametrize(
    "value",
    [
        None,
        "region",
        [1, [0, 0, 1, 1]],
        {"box": [0, 0, 1, 1]},
        {"locator": 0, "box": [0, 0, 1, 1]},
        {"locator": -2, "box": [0, 0, 1, 1]},
        {"locator": True, "box": [0, 0, 1, 1]},
        {"locator": "2", "box": [0, 0, 1, 1]},
        {"locator": 1.5, "box": [0, 0, 1, 1]},
        {"locator": float("nan"), "box": [0, 0, 1, 1]},
        {"locator": 1, "box": [0, 0, 1]},
        {"locator": 1, "box": "0,0,1,1"},
        {"locator": 1, "box": [0, 0, float("nan"), 1]},
        {"locator": 1, "box": [0, 0, float("inf"), 1]},
        {"locator": 1, "box": [0, 0, True, 1]},
        {"locator": 1, "box": [0, 0, "1", 1]},
        # Zero or near-zero area: a click, not a region.
        {"locator": 1, "box": [0.4, 0.4, 0.4, 0.8]},
        {"locator": 1, "box": [0.4, 0.4, 0.405, 0.8]},
        # Entirely off the page collapses to a zero-width sliver once clamped.
        {"locator": 1, "box": [1.2, 0.1, 1.5, 0.5]},
    ],
)
def test_unusable_regions_are_rejected(value: object) -> None:
    assert normalise_region(value) is None


def test_viewport_keeps_a_valid_region_and_drops_a_bad_one_silently() -> None:
    assert _reading_viewport(
        {"locator": 4, "region": {"locator": 4, "box": [0.1, 0.1, 0.5, 0.3]}}
    ) == {
        "locator": 4,
        "region": {"locator": 4, "box": [0.1, 0.1, 0.5, 0.3]},
    }
    # The rest of the viewport survives an unusable region.
    assert _reading_viewport(
        {"locator": 4, "selection": "x", "region": {"locator": 4, "box": [0, 0, 0, 0]}}
    ) == {"locator": 4, "selection": "x"}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_region_crop_contains_exactly_the_marked_area(reading_home: Path) -> None:
    source = reading_home / "blocks.pdf"
    _two_block_pdf(source)
    material_id = _ingest(source).material_id

    # Around the red block only: x 50..250 of 600, y 90..230 of 800.
    box = [50 / 600, 90 / 800, 250 / 600, 230 / 800]
    record = region_render_record(material_id, 1, box)

    assert record is not None
    assert record["mime_type"] == "image/jpeg"
    assert record["id"].startswith("rr-")
    assert record["filename"].endswith("-page-1-area.jpg")
    assert record["url"] == "" and record["embedded"] is True
    image = _decode(record)
    # The red block fills most of the crop and nothing of the blue one is in it.
    assert _share(image, "red") > 0.6
    assert _share(image, "blue") == 0
    # Rendered sharper than the page render: a 200x140 pt clip at the max DPI.
    assert image.size == pytest.approx(
        (200 * REGION_RENDER_MAX_DPI / 72, 140 * REGION_RENDER_MAX_DPI / 72), abs=2
    )

    other = _decode(
        region_render_record(material_id, 1, [350 / 600, 570 / 800, 550 / 600, 710 / 800])
    )
    assert _share(other, "blue") > 0.6
    assert _share(other, "red") == 0


def test_region_follows_the_page_as_displayed_when_rotated(reading_home: Path) -> None:
    """pdf.js lays a rotated page out rotated; the box is relative to that."""
    source = reading_home / "rotated.pdf"
    _two_block_pdf(source, rotate=90)
    material_id = _ingest(source).material_id

    # Rotated 90° clockwise, the unrotated top-left red block shows at the
    # displayed top-right: displayed x 580..700 of 800, y 60..240 of 600.
    record = region_render_record(material_id, 1, [570 / 800, 50 / 600, 710 / 800, 250 / 600])

    assert record is not None
    image = _decode(record)
    assert _share(image, "red") > 0.6
    assert _share(image, "blue") == 0


def test_large_region_stays_within_the_pixel_budget(reading_home: Path) -> None:
    source = reading_home / "poster.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=2384, height=3370)  # A0 in points
    # Reading ingest needs some text layer; a fully image-only scan is refused.
    page.insert_text((100, 60), "Poster title")
    page.draw_rect(pymupdf.Rect(100, 100, 2200, 3200), color=RED, fill=RED)
    doc.save(str(source))
    doc.close()
    material_id = _ingest(source).material_id

    image = _decode(region_render_record(material_id, 1, [0, 0, 1, 1]))

    width, height = image.size
    assert width * height <= REGION_RENDER_MAX_PIXELS
    assert max(width, height) <= REGION_RENDER_MAX_SIDE
    assert region_render_dpi(2384, 3370) < REGION_RENDER_MAX_DPI


def test_region_render_refuses_what_it_cannot_crop(reading_home: Path) -> None:
    from deeptutor.reading import ReadingStore

    source = reading_home / "blocks.pdf"
    _two_block_pdf(source)
    material_id = _ingest(source).material_id

    assert region_render_record(material_id, 3, [0, 0, 0.5, 0.5]) is None
    assert region_render_record(material_id, 0, [0, 0, 0.5, 0.5]) is None
    assert region_render_record(material_id, 1, [0, 0, 0, 0]) is None
    assert region_render_record("", 1, [0, 0, 0.5, 0.5]) is None
    assert region_has_render(material_id, 1) and region_has_render(material_id, 2)
    assert not region_has_render(material_id, 3)

    text = ReadingStore().ingest_units(
        "b" * 16, filename="notes.txt", units=["Plain text."], unit="section", title="Notes"
    )
    assert region_render_record(text.material_id, 1, [0, 0, 0.5, 0.5]) is None
    assert not region_has_render(text.material_id, 1)


# ---------------------------------------------------------------------------
# attachment order
# ---------------------------------------------------------------------------


def _noisy_png(seed: int) -> bytes:
    """A noisy PNG above the min-bytes gate so extraction keeps it."""
    import random

    rng = random.Random(seed)
    raw = bytes(rng.randrange(256) for _ in range(150 * 120 * 3))
    buffer = io.BytesIO()
    PILImage.frombytes("RGB", (150, 120), raw).save(buffer, format="PNG")
    return buffer.getvalue()


def test_region_crop_leads_the_attachments_and_the_cap_holds(reading_home: Path) -> None:
    """Crop first, then the drawn page's render, then its embedded figures."""
    source = reading_home / "slide.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 60), "A drawn slide with embedded figures.")
    for index in range(10):  # past the full-page render gate
        page.draw_line(pymupdf.Point(72, 100 + index * 10), pymupdf.Point(300, 100 + index * 10))
    for index in range(4):
        rect = pymupdf.Rect(72, 300 + index * 110, 260, 400 + index * 110)
        page.insert_image(rect, stream=_noisy_png(seed=index + 1))
    doc.save(str(source))
    doc.close()
    material_id = _ingest(source).material_id
    region = {"locator": 1, "box": [0.1, 0.1, 0.4, 0.3]}

    without = _reading_viewport_image_attachments(material_id, {"locator": 1})
    with_region = _reading_viewport_image_attachments(
        material_id, _reading_viewport({"locator": 1, "region": region})
    )

    # Without a region the turn is exactly as before: render, then figures.
    assert without[0]["id"].startswith("rp-")
    assert len(without) == READING_VIEWPORT_MAX_IMAGES
    # With one, the crop leads and pushes the last figure out of the cap.
    assert [item["id"][:3] for item in with_region] == ["rr-", "rp-", "rv-", "rv-"]
    assert [item["id"] for item in with_region[1:]] == [
        item["id"] for item in without[: READING_VIEWPORT_MAX_IMAGES - 1]
    ]


def test_region_on_another_page_than_the_viewport_is_still_cropped(reading_home: Path) -> None:
    source = reading_home / "blocks.pdf"
    _two_block_pdf(source)
    material_id = _ingest(source).material_id

    attachments = _reading_viewport_image_attachments(
        material_id,
        _reading_viewport({"locator": 2, "region": {"locator": 1, "box": [0.1, 0.1, 0.4, 0.3]}}),
    )

    assert attachments[0]["filename"].endswith("-page-1-area.jpg")


def test_unrenderable_region_leaves_the_attachments_as_before(reading_home: Path) -> None:
    source = reading_home / "blocks.pdf"
    _two_block_pdf(source)
    material_id = _ingest(source).material_id

    baseline = _reading_viewport_image_attachments(material_id, {"locator": 1})
    out_of_range = _reading_viewport_image_attachments(
        material_id,
        _reading_viewport({"locator": 1, "region": {"locator": 9, "box": [0.1, 0.1, 0.4, 0.3]}}),
    )

    assert [item["id"] for item in out_of_range] == [item["id"] for item in baseline]
