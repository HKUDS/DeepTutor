"""The stored original keeps its extension when a long display name is cut."""

from __future__ import annotations

from pathlib import Path

from deeptutor.reading.store import _safe_filename


def test_long_name_keeps_its_extension() -> None:
    name = "A" * 300 + ".pdf"

    stored = _safe_filename(name, fallback="material")

    assert stored.endswith(".pdf")
    assert len(stored) == 180


def test_cut_does_not_leave_a_trailing_dot_or_space_before_the_extension() -> None:
    name = "A" * 175 + " . " + "B" * 50 + ".epub"

    stored = _safe_filename(name, fallback="material")

    assert stored == "A" * 175 + ".epub"


def test_short_name_is_unchanged() -> None:
    assert _safe_filename("lecture notes.pdf", fallback="material") == "lecture notes.pdf"


def test_overlong_suffix_is_cut_like_the_rest_of_the_name() -> None:
    name = "paper." + "x" * 300

    assert _safe_filename(name, fallback="material") == name[:180]


def test_long_utf8_name_fits_on_disk_and_keeps_extension(tmp_path: Path) -> None:
    name = "课" * 100 + ".pdf"

    stored = _safe_filename(name, fallback="material")

    assert stored == "课" * 83 + ".pdf"
    raw_file = tmp_path / stored
    raw_file.write_bytes(b"original")
    assert raw_file.read_bytes() == b"original"
