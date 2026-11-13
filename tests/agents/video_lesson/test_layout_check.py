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

    assert check_layout(_page(tmp_path, ""), [0]) == [f"at 0s: {issue}"]


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
