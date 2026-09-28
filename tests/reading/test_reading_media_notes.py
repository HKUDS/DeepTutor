"""Media-note rendering: legacy output stays exact, captions are carried through.

Two render points are covered together because they share one idea — the text
model should learn what an embedded figure shows from the ``caption`` a vision
model wrote at ingestion, and nothing at all when there is no caption:

* ``read_material``'s per-unit image list (``_media_note``), and
* the viewport seed's compact figure caption line (``pre_loop_seed``).

The byte-for-byte guarantee for caption-less material is asserted explicitly on
both paths, so a future edit that merely "tidies" the wording fails here.
"""

from __future__ import annotations

import pytest

from deeptutor.capabilities.reading import ReadingCapability
from deeptutor.capabilities.reading.capability import (
    MATERIAL_ID_KEY,
    VIEWPORT_KEY,
)
from deeptutor.capabilities.reading.media_notes import (
    CAPTION_CHAR_LIMIT,
    MAX_NOTE_LINES,
)
from deeptutor.capabilities.reading.tools import _media_note
from deeptutor.core.context import UnifiedContext
import deeptutor.reading as reading_pkg
from deeptutor.reading import page_render as page_render_module


class _FakeStore:
    """The slice of the reading store the two render points actually touch."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def media_items(self, material_id: str) -> list[dict]:
        return list(self._rows)

    def media_items_at(self, material_id: str, locator: int) -> list[dict]:
        return [row for row in self._rows if row.get("locator") == locator]


def _row(locator: int, name: str, caption: str = "") -> dict:
    row = {"name": name, "locator": locator, "mime": "image/png", "bytes": 10}
    if caption:
        row["caption"] = caption
    return row


def _legacy_note(unit: str, rows: list[tuple[int, list[str]]]) -> str:
    lines = [f"- {unit} {locator}: " + ", ".join(names) for locator, names in rows]
    return (
        "\n\nEmbedded images in the units above (shown in the reader pane; "
        "image parts attached to this conversation's messages are these "
        "figures):\n" + "\n".join(lines)
    )


# ---------------------------------------------------------------------------
# _media_note
# ---------------------------------------------------------------------------


def test_media_note_without_captions_is_byte_for_byte_the_legacy_output() -> None:
    rows = [
        _row(3, "image-01.png"),
        _row(3, "image-02.png"),
        _row(5, "image-09.png"),
    ]

    note = _media_note(_FakeStore(rows), "material", "page", [3, 5])

    assert note == _legacy_note(
        "page", [(3, ["image-01.png", "image-02.png"]), (5, ["image-09.png"])]
    )


def test_media_note_appends_each_caption_after_its_figure() -> None:
    rows = [
        _row(3, "image-01.png", "A red cube on a white table."),
        _row(3, "image-02.png", "A blue sphere beside it."),
    ]

    note = _media_note(_FakeStore(rows), "material", "page", [3])

    assert "image-01.png — A red cube on a white table." in note
    assert "image-02.png — A blue sphere beside it." in note
    # One caption-less row must not gain a stray separator.
    assert note.endswith("A blue sphere beside it.")


def test_media_note_clips_a_runaway_caption() -> None:
    rows = [_row(1, "image-01.png", "x" * (CAPTION_CHAR_LIMIT + 200))]

    note = _media_note(_FakeStore(rows), "material", "page", [1])

    caption = note.rsplit(" — ", 1)[1]
    assert len(caption) == CAPTION_CHAR_LIMIT
    assert caption.endswith("…")


def test_media_note_caps_the_number_of_lines() -> None:
    rows = [_row(locator, f"image-{locator:02d}.png") for locator in range(1, 26)]

    note = _media_note(_FakeStore(rows), "material", "page", list(range(1, 26)))

    lines = note.splitlines()
    image_lines = [line for line in lines if line.startswith("- page ")]
    assert len(image_lines) == MAX_NOTE_LINES
    # 25 locators, 20 shown, 5 dropped — and the model is told the list is short.
    assert lines[-1] == "(5 more images omitted)"


def test_media_note_disappears_when_the_store_fails() -> None:
    class _Broken:
        def media_items(self, material_id: str) -> list[dict]:
            raise RuntimeError("media index unreadable")

    assert _media_note(_Broken(), "material", "page", [1]) == ""


# ---------------------------------------------------------------------------
# pre_loop_seed
# ---------------------------------------------------------------------------


def _viewport_context(locator: int, selection: str = "") -> UnifiedContext:
    viewport: dict = {"locator": locator}
    if selection:
        viewport["selection"] = selection
    return UnifiedContext(
        session_id="s1",
        user_message="what does the figure show?",
        metadata={MATERIAL_ID_KEY: "abc123ff", VIEWPORT_KEY: viewport},
    )


def test_pre_loop_seed_adds_a_caption_line_for_the_current_locator(monkeypatch) -> None:
    rows = [
        _row(4, "image-01.png", "A red cube on a white table."),
        _row(4, "image-02.png", "A blue sphere beside it."),
        _row(9, "image-07.png", "A figure on another page."),
    ]
    monkeypatch.setattr(reading_pkg, "ReadingStore", lambda: _FakeStore(rows))

    seed = ReadingCapability().pre_loop_seed(_viewport_context(4))

    assert "Locator 4's figures: " in seed
    assert "image-01.png — A red cube on a white table." in seed
    assert "image-02.png — A blue sphere beside it." in seed
    # Only the current locator's figures are described.
    assert "image-07.png" not in seed
    # The attachment sentence keeps its old meaning alongside the caption line.
    assert "they are attached to this message" in seed


def test_pre_loop_seed_omits_the_caption_line_without_captions(monkeypatch) -> None:
    rows = [_row(4, "image-01.png"), _row(4, "image-02.png")]
    monkeypatch.setattr(reading_pkg, "ReadingStore", lambda: _FakeStore(rows))

    seed = ReadingCapability().pre_loop_seed(_viewport_context(4))

    assert "figures:" not in seed
    assert "image-01.png" not in seed
    assert "Locator 4 contains 2 embedded image(s)" in seed


def test_pre_loop_seed_is_unchanged_when_the_store_raises(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(reading_pkg, "ReadingStore", _boom)

    seed = ReadingCapability().pre_loop_seed(_viewport_context(4))

    # No material, no viewport seed breakage: exactly the legacy sentence.
    assert seed == "The reader is currently showing locator 4."


def test_pre_loop_seed_caps_captions_at_three_figures(monkeypatch) -> None:
    rows = [_row(2, f"image-{index:02d}.png", f"Figure {index}.") for index in range(1, 6)]
    monkeypatch.setattr(reading_pkg, "ReadingStore", lambda: _FakeStore(rows))

    seed = ReadingCapability().pre_loop_seed(_viewport_context(2))

    assert seed.count(" — ") == 3
    assert "image-04.png" not in seed


@pytest.mark.parametrize("locator", [0])
def test_pre_loop_seed_skips_media_work_without_a_locator(monkeypatch, locator) -> None:
    def _boom():
        raise AssertionError("no store call should happen without a locator")

    monkeypatch.setattr(reading_pkg, "ReadingStore", _boom)

    seed = ReadingCapability().pre_loop_seed(_viewport_context(locator))

    assert seed == ""


def test_pre_loop_seed_announces_a_page_render(monkeypatch) -> None:
    monkeypatch.setattr(reading_pkg, "ReadingStore", lambda: _FakeStore([]))
    monkeypatch.setattr(page_render_module, "page_has_render", lambda material_id, locator: True)

    seed = ReadingCapability().pre_loop_seed(_viewport_context(14))

    assert "rendered image of that page" in seed
    assert "Locator 14's content is drawn" in seed


def test_pre_loop_seed_is_byte_for_byte_unchanged_without_a_page_render(monkeypatch) -> None:
    monkeypatch.setattr(reading_pkg, "ReadingStore", lambda: _FakeStore([_row(4, "image-01.png")]))
    monkeypatch.setattr(page_render_module, "page_has_render", lambda material_id, locator: False)

    seed = ReadingCapability().pre_loop_seed(_viewport_context(4))

    # Exactly the pre-render seed: the new sentence appears only when a render
    # was actually attached.
    assert seed == (
        "The reader is currently showing locator 4. "
        "Locator 4 contains 1 embedded image(s) from the document; "
        "they are attached to this message, so read them directly when the question "
        "concerns a figure."
    )
    assert "rendered image" not in seed


def test_pre_loop_seed_survives_a_page_render_probe_failure(monkeypatch) -> None:
    def _boom(material_id, locator):
        raise RuntimeError("page render probe failed")

    monkeypatch.setattr(reading_pkg, "ReadingStore", lambda: _FakeStore([]))
    monkeypatch.setattr(page_render_module, "page_has_render", _boom)

    seed = ReadingCapability().pre_loop_seed(_viewport_context(4))

    assert seed == "The reader is currently showing locator 4."
    assert "rendered image" not in seed
