"""Tests for the bilingual EPUB merge/generation module."""

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest

from deeptutor.immersive_reading.bilingual.merge_epub import build_bilingual_epub
from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


@pytest.fixture
def en_epub(tmp_path: Path) -> Path:
    path = tmp_path / "english.epub"
    make_minimal_epub(path, "Test Book", [
        ("Chapter One", ["The cat sat on the mat. It was nice.", "The dog ran fast."]),
        ("Chapter Two", ["Birds fly high in the sky above."]),
    ])
    return path


@pytest.fixture
def zh_epub(tmp_path: Path) -> Path:
    path = tmp_path / "chinese.epub"
    make_minimal_epub(path, "測試書", [
        ("第一章", ["貓坐在墊子上。很好。", "狗跑得快。"]),
        ("第二章", ["鳥在天空中高飛。"]),
    ])
    return path


def test_build_bilingual_epub_creates_valid_epub(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    chapter_map = [
        ["ch0", "chapter0.xhtml", "chapter0.xhtml"],
        ["ch1", "chapter1.xhtml", "chapter1.xhtml"],
    ]
    stats = build_bilingual_epub(en_epub, zh_epub, chapter_map, output)
    assert output.exists()
    assert output.stat().st_size > 0
    assert len(stats) == 2


def test_bilingual_epub_has_details_blocks(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    chapter_map = [["ch0", "chapter0.xhtml", "chapter0.xhtml"]]
    build_bilingual_epub(en_epub, zh_epub, chapter_map, output)

    with zipfile.ZipFile(output) as zf:
        ch0 = zf.read("chapter0.xhtml").decode("utf-8")
        assert 'class="zh-details"' in ch0
        assert "<summary" in ch0
        # English content preserved
        assert "cat" in ch0


def test_mimetype_is_first_and_uncompressed(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(en_epub, zh_epub, [["ch0", "chapter0.xhtml", "chapter0.xhtml"]], output)

    with zipfile.ZipFile(output) as zf:
        info = zf.infolist()[0]
        assert info.filename == "mimetype"
        assert info.compress_type == zipfile.ZIP_STORED


def test_opf_has_target_language(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(
        en_epub, zh_epub, [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output, target_lang="zh-Hant",
    )

    with zipfile.ZipFile(output) as zf:
        opf = zf.read("content.opf").decode("utf-8")
        assert "zh-Hant" in opf


def test_css_injected(en_epub: Path, zh_epub: Path, tmp_path: Path):
    output = tmp_path / "output.epub"
    build_bilingual_epub(en_epub, zh_epub, [["ch0", "chapter0.xhtml", "chapter0.xhtml"]], output)

    with zipfile.ZipFile(output) as zf:
        ch0 = zf.read("chapter0.xhtml").decode("utf-8")
        # CSS is injected either inline or into a linked stylesheet.
        # Since our minimal EPUB has no CSS, it should be inline.
        assert "zh-details" in ch0


@pytest.mark.parametrize(
    "style,expected_class",
    [
        ("folded", "zh-details"),
        ("alternating", "zh-alternate"),
        ("two_column", "bilingual-row"),
    ],
)
def test_epub_export_styles(
    en_epub: Path,
    zh_epub: Path,
    tmp_path: Path,
    style: str,
    expected_class: str,
):
    output = tmp_path / f"{style}.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        style=style,
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")
        ET.fromstring(chapter)
        assert expected_class in chapter
        assert "The cat sat on the mat." in chapter
        assert "貓坐在墊子上。" in chapter


def test_epub_export_injects_custom_font_and_stylesheet(
    en_epub: Path, zh_epub: Path, tmp_path: Path
):
    output = tmp_path / "custom.epub"
    custom_css = ".zh-alternate { color: rgb(12, 34, 56); } .en-column::after { content: '<'; }"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        style="alternating",
        font_family="Reader Serif",
        custom_css=custom_css,
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")
        stylesheet = archive.read("bilingual.css").decode("utf-8")
        ET.fromstring(chapter)
        assert 'href="bilingual.css"' in chapter
        assert '"Reader Serif"' in stylesheet
        assert ".zh-alternate { color: rgb(12, 34, 56); }" in stylesheet
        assert "\\3c " in stylesheet


def test_epub_export_uses_task_translation_overrides(
    en_epub: Path, zh_epub: Path, tmp_path: Path
):
    output = tmp_path / "overrides.epub"
    build_bilingual_epub(
        en_epub,
        zh_epub,
        [["ch0", "chapter0.xhtml", "chapter0.xhtml"]],
        output,
        translation_overrides={"ch0": [None, "机器生成译文"]},
    )

    with zipfile.ZipFile(output) as archive:
        chapter = archive.read("chapter0.xhtml").decode("utf-8")
        ET.fromstring(chapter)
        assert "机器生成译文" in chapter
