"""The browser layout check against small hand-made pages (skipped without Chrome)."""

from __future__ import annotations

import html
import json
from pathlib import Path
import subprocess

import pytest

from deeptutor.agents.video_lesson import layout_check
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
    assert sample_frames(30 * 20) == [0, 60, 180, 300, 420, 540]
    assert sample_frames(1) == [0]
    assert len(sample_frames(30 * 60 * 60)) <= 48
    assert sample_frames(2, fps=1, every_s=1) == [0]
    assert {0, 15, 74, 75, 90, 119}.issubset(sample_frames(120, scene_lengths=[75, 45]))
    assert len(sample_frames(1000, scene_lengths=[10] * 100)) <= 48


@pytest.mark.parametrize("lengths", [None, [], [True, 9], [0, 10], [3, 6], [1] * 65, ["5", 5]])
def test_invalid_scene_lengths_fall_back_to_periodic_sampling(lengths) -> None:
    assert sample_frames(10, scene_lengths=lengths) == sample_frames(10)


def test_short_scenes_and_budget_are_bounded() -> None:
    assert sample_frames(3, scene_lengths=[1, 1, 1]) == [0, 1, 2]
    frames = sample_frames(640, scene_lengths=[10] * 64)
    assert len(frames) <= 48
    assert frames == sorted(set(frames))
    assert all(0 <= frame < 640 for frame in frames)


@needs_chrome
def test_frame_zero_requires_visible_problem_text(tmp_path: Path) -> None:
    hidden = _page(
        tmp_path,
        '<div data-scene-content style="position:absolute;left:120px;top:140px;width:760px">'
        '<div data-title style="opacity:1;font:76px serif">椭圆与直线的弦长</div>'
        '<div style="opacity:0;font:36px sans-serif">已知椭圆与直线交于两点</div></div>',
    )
    issues = check_layout(hidden, [0])
    assert issues and any("visible problem" in issue for issue in issues)
    shown = _page(
        tmp_path,
        '<div data-scene-content style="position:absolute;left:120px;top:140px;width:760px">'
        '<div data-title style="opacity:1;font:76px serif">椭圆与直线的弦长</div>'
        '<div style="opacity:1;font:36px sans-serif">已知椭圆与直线交于两点，求弦长</div></div>',
    )
    assert not any("visible problem" in issue for issue in check_layout(shown, [0]) or [])


@needs_chrome
def test_scene_region_clipping_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-content style="position:absolute;left:120px;top:140px;'
        'width:400px;height:100px;overflow:hidden">'
        '<div style="font:48px sans-serif;height:200px">Long content</div></div>',
    )
    issues = check_layout(page, [0])
    assert issues and any("overflow" in issue for issue in issues)


@needs_chrome
def test_full_canvas_svg_with_in_bounds_drawing_is_not_overflow(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:960px;top:140px;'
        'width:840px;height:720px;overflow:hidden">'
        '<svg width="1920" height="1080" style="position:absolute;left:0;top:0;overflow:visible">'
        '<path d="M 20 20 L 200 20" stroke="black" stroke-width="4" fill="none"/>'
        "</svg></div>",
    )
    assert check_layout(page, [0]) == []


@needs_chrome
def test_text_overflow_remains_detected_with_full_canvas_svg(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-content style="position:absolute;left:120px;top:140px;'
        'width:400px;height:100px;overflow:hidden">'
        '<svg width="1920" height="1080" style="position:absolute;left:0;top:0;overflow:visible">'
        '<path d="M 20 20 L 200 20" stroke="black" stroke-width="4" fill="none"/>'
        '</svg><div style="font:48px sans-serif;height:200px">Long content</div></div>',
    )
    issues = check_layout(page, [0])
    assert issues and any("overflow" in issue for issue in issues)


@needs_chrome
def test_inline_svg_preserves_layout_when_measuring_overflow(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-content style="position:absolute;left:120px;top:140px;'
        'width:120px;height:120px;overflow:hidden">'
        '<svg width="80" height="100"><path d="M 10 10 L 30 10" stroke="black"/></svg>'
        '<div style="height:40px">x</div></div>',
    )
    issues = check_layout(page, [0])
    assert issues and any("overflow" in issue for issue in issues)


@needs_chrome
def test_svg_stroke_width_clipped_by_graphic_region_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:400px;top:140px;'
        'width:120px;height:120px;overflow:hidden">'
        '<svg width="120" height="120" style="display:block;overflow:visible">'
        '<path d="M 1 20 L 1 100" stroke="black" stroke-width="20" fill="none"/>'
        "</svg></div>",
    )
    issues = check_layout(page, [0])
    assert issues and any("drawn shape" in issue and "clipped" in issue for issue in issues)


@needs_chrome
def test_hidden_or_zero_stroke_is_not_reported_as_clipped(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:400px;top:140px;'
        'width:120px;height:120px;overflow:hidden">'
        '<svg width="120" height="120" style="display:block;overflow:visible">'
        '<path d="M 1 20 L 1 100" stroke="black" stroke-width="20" stroke-opacity="0" fill="none"/>'
        '<path d="M 1 20 L 1 100" stroke="black" stroke-width="0" fill="none"/>'
        '<path d="M 1 20 L 1 100" stroke="black" stroke-width="20" opacity="0" fill="none"/>'
        "</svg></div>",
    )
    assert check_layout(page, [0]) == []


@needs_chrome
@pytest.mark.parametrize(
    "shape",
    [
        '<path d="M -20 20 L 20 20" stroke="transparent" stroke-width="10" fill="none"/>',
        '<path d="M -20 20 L 20 20" stroke="rgba(0,0,0,0)" stroke-width="10" fill="none"/>',
        '<path d="M -20 20 L 20 20 Z" fill="rgba(0,0,0,0)" stroke="none"/>',
        '<path d="M -20 20 L 20 20" stroke="rgba(0,0,0,0.2)" stroke-opacity="0.5" stroke-width="10" fill="none"/>',
        '<g opacity="0.5"><path d="M -20 20 L 20 20" stroke="rgba(0,0,0,0.2)" stroke-width="10" fill="none"/></g>',
    ],
)
def test_transparent_svg_paint_is_not_reported_as_clipped(tmp_path: Path, shape: str) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:400px;top:140px;'
        'width:120px;height:120px;overflow:hidden">'
        '<svg width="120" height="120" style="display:block;overflow:visible">'
        + shape
        + "</svg></div>",
    )
    assert check_layout(page, [0]) == []


@needs_chrome
@pytest.mark.parametrize(
    "paint",
    ["rgba(0,0,0,0.5)", "url(#gradient)"],
)
def test_visible_or_unknown_svg_paint_remains_checked(tmp_path: Path, paint: str) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:400px;top:140px;'
        'width:120px;height:120px;overflow:hidden">'
        '<svg width="120" height="120" style="display:block;overflow:visible">'
        '<defs><linearGradient id="gradient"><stop stop-color="black"/></linearGradient></defs>'
        f'<path d="M -20 20 L 20 20" stroke="{paint}" stroke-width="10" fill="none"/>'
        "</svg></div>",
    )
    issues = check_layout(page, [0])
    assert issues and any("drawn shape" in issue and "clipped" in issue for issue in issues)


@needs_chrome
def test_svg_image_clipped_by_graphic_region_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:400px;top:140px;'
        'width:120px;height:120px;overflow:hidden">'
        '<svg width="120" height="120" style="display:block;overflow:visible">'
        '<image x="-20" y="20" width="40" height="40" '
        'href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%271%27 height=%271%27%3E%3Crect width=%271%27 height=%271%27/%3E%3C/svg%3E" />'
        "</svg></div>",
    )
    issues = check_layout(page, [0])
    assert issues and any("image" in issue and "clipped" in issue for issue in issues)


@needs_chrome
def test_svg_stroke_clipped_by_graphic_region_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div data-scene-graphic style="position:absolute;left:400px;top:140px;'
        'width:300px;height:300px;overflow:hidden">'
        '<svg width="300" height="300" style="display:block;overflow:visible">'
        '<path d="M -100 50 L 100 50" stroke="black" stroke-width="4" fill="none"/>'
        "</svg></div>",
    )
    issues = check_layout(page, [0])
    assert issues and any("drawn shape" in issue and "clipped" in issue for issue in issues)


@needs_chrome
def test_clean_page_has_no_issues(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div class="t" style="left:200px;top:100px">Title</div>'
        '<div class="t" style="left:200px;top:400px">Body</div>',
    )
    assert check_layout(page, [0]) == []


@needs_chrome
def test_strict_check_rejects_missing_player_frame(tmp_path: Path) -> None:
    page = _page(tmp_path, '<div class="t" style="left:200px;top:100px">Title</div>')
    assert check_layout(page, [0], require_player_frame=True) is None


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
def test_overlapping_non_ascii_text_is_reported(tmp_path: Path) -> None:
    page = _page(
        tmp_path,
        '<div class="t" style="left:200px;top:100px">导数的定义</div>'
        '<div class="t" style="left:230px;top:110px">切线的斜率</div>',
    )
    issues = check_layout(page, [0])
    assert issues and any('"导数的定义" overlaps text "切线的斜率"' in i for i in issues)


def test_browser_output_is_decoded_as_utf8_whatever_the_locale(monkeypatch, tmp_path):
    # A Windows server whose ANSI code page is cp936 decodes ``text=True``
    # output with that code page unless an encoding is given; Chrome writes
    # --dump-dom as UTF-8, and the report quotes the lesson's text.
    issue = 'text "导数的定义" overlaps text "切线的斜率" near x=230, y=110'
    report = html.escape(json.dumps({"0": {"issues": [issue]}}, ensure_ascii=False))
    dom = f'<html><body><pre id="out">{report}</pre></body></html>\n'.encode()

    def cp936_server_run(argv, **kwargs):
        stdout = dom.decode(kwargs.get("encoding") or "cp936", kwargs.get("errors") or "strict")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    browser = tmp_path / "chrome"
    browser.write_text("browser", encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_CHROME_EXECUTABLE", str(browser))
    monkeypatch.setattr(layout_check.subprocess, "run", cp936_server_run)

    assert check_layout(_page(tmp_path, ""), [0]) == [f"at frame 0 (0.00s): {issue}"]


def test_browser_report_with_missing_issue_list_is_unavailable(monkeypatch, tmp_path):
    report = html.escape(json.dumps({"0": {}}))
    browser = tmp_path / "chrome"
    browser.write_text("browser", encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_CHROME_EXECUTABLE", str(browser))
    monkeypatch.setattr(
        layout_check.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=f'<pre id="out">{report}</pre>', stderr=""
        ),
    )
    assert check_layout(_page(tmp_path, ""), [0]) is None


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
