"""The browser layout check against small hand-made pages (skipped without Chrome)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.agents.video_lesson.layout_check import (
    CAPTION_TOP,
    check_layout,
    chrome_path,
    sample_frames,
)

needs_chrome = pytest.mark.skipif(chrome_path() is None, reason="no Chrome/Chromium on PATH")


def _page(tmp_path: Path, body: str) -> Path:
    page = tmp_path / "lesson.html"
    page.write_text(
        "<!doctype html><html><head><style>body{margin:0}div.t{position:absolute;font:48px sans-serif}"
        '</style></head><body><div style="position:relative;width:1920px;height:1080px">'
        + body
        + "</div></body></html>",
        encoding="utf-8",
    )
    return page


def test_sample_frames_spread_every_four_seconds() -> None:
    assert sample_frames(30 * 20) == [60, 180, 300, 420, 540]
    assert sample_frames(1) == [0]


@needs_chrome
def test_clean_page_has_no_issues(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div class="t" style="left:200px;top:100px">Title</div>'
        '<div class="t" style="left:200px;top:400px">Body</div>',
    )
    assert check_layout(page, [0]) == []


@needs_chrome
def test_overlapping_text_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div class="t" style="left:200px;top:100px">Kernel namespaces</div>'
        '<div class="t" style="left:260px;top:110px">cgroups</div>',
    )
    issues = check_layout(page, [0])
    assert issues and any("overlaps text" in i for i in issues)


@needs_chrome
def test_stroke_through_text_and_caption_band_are_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div class="t" style="left:600px;top:300px">Image layer</div>'
        '<svg width="1920" height="1080" style="position:absolute;left:0;top:0">'
        '<path d="M 500 330 L 1100 330" stroke="black" stroke-width="4" fill="none"/>'
        f'<path d="M 100 700 L 100 {CAPTION_TOP + 120}" stroke="black" stroke-width="4" fill="none"/></svg>',
    )
    issues = check_layout(page, [0])
    assert issues is not None
    assert any('cross the text "Image layer"' in i for i in issues)
    assert any("caption band" in i for i in issues)


def test_browser_executable_can_be_configured(monkeypatch, tmp_path):
    browser = tmp_path / "custom-chrome"
    browser.write_text("browser", encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_CHROME_EXECUTABLE", str(browser))
    assert chrome_path() == str(browser)
    monkeypatch.setenv("DEEPTUTOR_CHROME_EXECUTABLE", str(tmp_path / "missing"))
    assert chrome_path() is None
