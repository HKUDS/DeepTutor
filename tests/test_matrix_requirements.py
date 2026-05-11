"""Tests for Matrix dependency split."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_matrix_default_requirements_do_not_install_e2e() -> None:
    text = (ROOT / "requirements" / "matrix.txt").read_text(encoding="utf-8")

    assert "matrix-nio[e2e]" not in text
    assert "matrix-nio>=0.25.2,<1.0.0" in text


def test_matrix_e2e_requirements_are_separate() -> None:
    text = (ROOT / "requirements" / "matrix-e2e.txt").read_text(encoding="utf-8")

    assert "-r matrix.txt" in text
    assert "matrix-nio[e2e]>=0.25.2,<1.0.0" in text
