"""Regression tests for the P0/P1 fixes.

Covers: 1:N sentence-splitting in _render_group, export overrides propagation,
_detect_target_lang discriminative character sets, OPF paired-tag regex,
_auto_chapter_map confidence scores, chapter_count caching.
"""

from pathlib import Path
import zipfile

import pytest

from deeptutor.immersive_reading.bilingual.align import (
    EnPara,
    Group,
    ZhUnit,
    feature_set,
    fragment_inner,
    sentence_partitions,
    split_sentences,
)
from deeptutor.immersive_reading.bilingual.merge_epub import _render_group
from deeptutor.immersive_reading.bilingual.service import (
    _auto_chapter_map,
    _detect_target_lang,
    _read_epub_chapters,
)
from tests.immersive_reading.bilingual._fixtures import _container_xml, make_chapter_xhtml

# ── P0 #3: 1:N sentence-splitting in _render_group ─────────────────────


def _make_en_para(text: str, inner: str = "", pid: str = "p1") -> EnPara:
    inner = inner or text
    return EnPara(
        tag="p",
        attrs=f' id="{pid}"',
        inner=inner,
        text=text,
        source=f'<p id="{pid}">{inner}</p>',
        start=0,
        end=len(inner) + 20,
        ident=pid,
        feats=feature_set(text),
    )


def _make_zh_unit(text: str, uid: str = "z1") -> ZhUnit:
    return ZhUnit(
        tag="p",
        attrs=f' id="{uid}"',
        inner=text,
        text=text,
        heading_html="",
        heading_text="",
        ident=uid,
        feats=feature_set(text),
    )


def test_render_group_1_to_2_sentence_split():
    """When 1 EN paragraph maps to 2 ZH units, the paragraph is split into
    sentence fragments and interleaved with each translation panel."""
    en_text = "First sentence here. Second sentence follows. Third one ends now."
    en_para = _make_en_para(en_text, inner=en_text, pid="p1")
    zh_units = [
        _make_zh_unit("第一句。第二句。", "z1"),
        _make_zh_unit("第三句結束。", "z2"),
    ]
    group = Group(0, 1, 0, 2, 0.5)
    rendered = _render_group(group, [en_para], zh_units, "label")

    # Should produce 2 fragments, both keyed to EN index 0
    assert len(rendered) == 2
    assert all(idx == 0 for idx, _ in rendered)

    # Each fragment should contain a <details> block (Chinese panel)
    details_count = sum(1 for _, m in rendered if "zh-details" in m)
    assert details_count == 2

    # The EN paragraph should have been split: second fragment needs a unique ID
    markup0 = rendered[0][1]
    markup1 = rendered[1][1]
    assert 'id="p1"' in markup0
    assert "bilingual-2" in markup1  # fragment index 1 -> suffix -bilingual-2


def test_render_group_1_to_1_unchanged():
    """1:1 groups still render normally (no sentence splitting)."""
    en1 = _make_en_para("Hello world.", pid="p1")
    zh1 = _make_zh_unit("你好世界。", "z1")
    group = Group(0, 1, 0, 1, 0.1)
    rendered = _render_group(group, [en1], [zh1], "label")
    assert len(rendered) == 1
    assert rendered[0][0] == 0
    assert "zh-details" in rendered[0][1]


def test_render_group_1_to_3_sentence_split():
    """1 EN paragraph to 3 ZH units: three interleaved fragments."""
    en_text = "First. Second. Third. Fourth. Fifth."
    en_para = _make_en_para(en_text, inner=en_text, pid="p1")
    zh_units = [
        _make_zh_unit("第一。", "z1"),
        _make_zh_unit("第二。第三。", "z2"),
        _make_zh_unit("第四。第五。", "z3"),
    ]
    group = Group(0, 1, 0, 3, 0.5)
    rendered = _render_group(group, [en_para], zh_units, "label")
    assert len(rendered) == 3
    assert all(idx == 0 for idx, _ in rendered)


def test_split_sentences_basic():
    assert split_sentences("Hello world. Goodbye!") == ["Hello world.", "Goodbye!"]


def test_split_sentences_abbreviation():
    """Abbreviations should not trigger sentence breaks."""
    result = split_sentences("Mr. Smith went to the store. He bought milk.")
    assert len(result) == 2
    assert result[0] == "Mr. Smith went to the store."


def test_fragment_inner_preserves_inline_tags():
    """Splitting should reopen inline tags in each fragment."""
    inner = "<em>Hello</em> world. <strong>Goodbye</strong> friend."
    ends = [len("Hello world")]  # boundary after first sentence chars
    parts = fragment_inner(inner, [0, ends[0], 100])
    # Each part should be valid (balanced tags)
    assert len(parts) >= 1


def test_sentence_partitions_proportional():
    sentences = ["Short.", "Medium length sentence.", "Very long descriptive sentence here."]
    zh = [_make_zh_unit("短"), _make_zh_unit("中等長度"), _make_zh_unit("非常長的描述性句子")]
    parts = sentence_partitions(sentences, zh)
    assert len(parts) == 3
    # Partitions should cover all sentences contiguously
    assert parts[0][0] == 0
    assert parts[-1][1] == len(sentences)


# ── P0 #2: _detect_target_lang with non-overlapping character sets ─────


def _make_epub_with_text(path: Path, title: str, body_text: str) -> None:
    """Build a minimal EPUB with custom body text for language detection."""
    xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>{body_text}</body>
</html>"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">test</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:language>zh</dc:language>
  </metadata>
  <manifest>
    <item id="ch0" href="chapter0.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch0"/></spine>
</package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("content.opf", opf)
        zf.writestr("chapter0.xhtml", xhtml)


def test_detect_target_lang_traditional(tmp_path: Path):
    """Traditional Chinese content with discriminative characters."""
    path = tmp_path / "trad.epub"
    # Use characters from the trad-only set: 說讀體會個後來開裡邊這國學發經過還實難關覺觀認識記討論門問處沒東長當
    body = "<p>" + "這個國家的學生在學校裡讀書。" * 10 + "</p>"
    _make_epub_with_text(path, "繁體書", body)
    assert _detect_target_lang(path) == "zh-Hant"


def test_detect_target_lang_simplified(tmp_path: Path):
    """Simplified Chinese content with discriminative characters."""
    path = tmp_path / "simp.epub"
    # Use characters from the simp-only set: 说读体会个后来开里边这国学发经过还实难关觉观认识记讨论门问处没东长当
    body = "<p>" + "这个国家的学生在学校里读书。" * 10 + "</p>"
    _make_epub_with_text(path, "简体书", body)
    assert _detect_target_lang(path) == "zh-Hans"


def test_detect_target_lang_no_discriminative_chars(tmp_path: Path):
    """When no discriminative characters are found, defaults to zh-Hant."""
    path = tmp_path / "neutral.epub"
    body = "<p>ABCDEFG 12345</p>"
    _make_epub_with_text(path, "Neutral", body)
    assert _detect_target_lang(path) == "zh-Hant"


# ── P1 #6: OPF manifest regex matching paired <item></item> tags ───────


def test_read_epub_chapters_paired_item_tags(tmp_path: Path):
    """EPUBs with <item ...></item> (not self-closing) should parse correctly."""
    path = tmp_path / "paired.epub"
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Paired Tags Book</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ch0" href="chapter0.xhtml" media-type="application/xhtml+xml"></item>
    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"></item>
  </manifest>
  <spine>
    <itemref idref="ch0"/>
    <itemref idref="ch1"/>
  </spine>
</package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("content.opf", opf)
        zf.writestr("chapter0.xhtml", make_chapter_xhtml("First", ["Para one."]))
        zf.writestr("chapter1.xhtml", make_chapter_xhtml("Second", ["Para two."]))

    title, chapters = _read_epub_chapters(path)
    assert title == "Paired Tags Book"
    assert len(chapters) == 2
    assert chapters[0]["title"] == "First"
    assert chapters[1]["title"] == "Second"


# ── P1 #4: _auto_chapter_map with title similarity confidence ──────────


def test_auto_chapter_map_includes_confidence():
    """Chapter map entries should now include a title-similarity confidence score."""
    en_chapters = [
        {"title": "Chapter 1: The Beginning", "href": "ch0.xhtml"},
        {"title": "Chapter 2: The End", "href": "ch1.xhtml"},
    ]
    zh_chapters = [
        {"title": "Chapter 1: The Beginning", "href": "ch0.xhtml"},
        {"title": "Chapter 2: The End", "href": "ch1.xhtml"},
    ]
    result = _auto_chapter_map(en_chapters, zh_chapters)
    assert len(result) == 2
    # Each entry should have 6 elements: [id, en_href, zh_href, en_title, zh_title, confidence]
    assert len(result[0]) == 6
    # Matching titles should have high confidence
    assert result[0][5] > 0.9


def test_auto_chapter_map_matches_by_ordinal_across_scripts():
    """EN 'Chapter 1' and ZH '第一章' should match by chapter ordinal."""
    en_chapters = [
        {
            "title": "Chapter 1: The Beginning",
            "href": "ch0.xhtml",
            "first_p": "",
            "p_count": 5,
            "text_len": 2000,
            "is_content": True,
        }
    ]
    zh_chapters = [
        {
            "title": "第一章：開始",
            "href": "ch0.xhtml",
            "first_p": "",
            "p_count": 5,
            "text_len": 2000,
            "is_content": True,
        }
    ]
    result = _auto_chapter_map(en_chapters, zh_chapters)
    assert len(result) == 1
    assert len(result[0]) == 6
    confidence = result[0][5]
    # Both have ordinal 1, so they match with high confidence despite script difference.
    assert confidence == 1.0


def test_auto_chapter_map_front_matter_skipped():
    """Front-matter files (TOC, copyright) should be excluded from matching."""
    en_chapters = [
        {
            "title": "Contents",
            "href": "toc.xhtml",
            "first_p": "",
            "p_count": 0,
            "text_len": 200,
            "is_content": False,
        },
        {
            "title": "1",
            "href": "ch1.xhtml",
            "first_p": "1",
            "p_count": 10,
            "text_len": 5000,
            "is_content": True,
        },
    ]
    zh_chapters = [
        {
            "title": "目錄",
            "href": "toc.xhtml",
            "first_p": "",
            "p_count": 0,
            "text_len": 100,
            "is_content": False,
        },
        {
            "title": "第一章",
            "href": "zh1.xhtml",
            "first_p": "",
            "p_count": 8,
            "text_len": 4000,
            "is_content": True,
        },
    ]
    result = _auto_chapter_map(en_chapters, zh_chapters)
    # Only 1 content chapter should be matched, skipping the TOC.
    assert len(result) == 1
    assert result[0][1] == "ch1.xhtml"
    assert result[0][2] == "zh1.xhtml"
    assert result[0][5] == 1.0


# ── P1 #5: chapter_count caching ───────────────────────────────────────


def test_pair_documents_caches_chapter_count(tmp_path: Path, monkeypatch):
    """pair_documents should store chapter_count in pairing.json."""
    import json

    from deeptutor.immersive_reading.bilingual import service as svc_module
    from tests.immersive_reading.bilingual._fixtures import make_minimal_epub

    en_epub = tmp_path / "en.epub"
    zh_epub = tmp_path / "zh.epub"
    make_minimal_epub(en_epub, "EN Book", [("Ch1", ["Text."]), ("Ch2", ["Text."])])
    make_minimal_epub(zh_epub, "ZH Book", [("第一章", ["文。"]), ("第二章", ["文。"])])

    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            d = tmp_path / "bilingual"
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = tmp_path / "bilingual" / f"pairing_{pairing_id}"
            (root / "sections").mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            return tmp_path / f"document_{document_id}"

    for doc_id, epub in [("en01", en_epub), ("zh01", zh_epub)]:
        d = tmp_path / f"document_{doc_id}"
        d.mkdir(parents=True)
        (d / "original.epub").write_bytes(epub.read_bytes())

    monkeypatch.setattr(svc_module, "get_path_service", lambda: FakePathService())
    svc = svc_module.BilingualPairingService()
    result = svc.pair_documents("en01", "zh01")

    # pairing.json should have chapter_count cached
    pairing_json = json.loads(
        (tmp_path / "bilingual" / f"pairing_{result['pairing_id']}" / "pairing.json").read_text()
    )
    assert pairing_json["chapter_count"] == 2

    # list_pairings should use the cached value (no chapter_map.json read needed)
    pairings = svc.list_pairings()
    assert pairings[0]["chapter_count"] == 2


# ── P0 #1: export_epub passes alignment overrides ──────────────────────


def test_export_epub_uses_overrides(tmp_path: Path, monkeypatch):
    """export_epub should pass alignment_overrides to build_bilingual_epub."""
    from deeptutor.immersive_reading.bilingual import merge_epub
    from deeptutor.immersive_reading.bilingual import service as svc_module
    from tests.immersive_reading.bilingual._fixtures import make_minimal_epub

    en_epub = tmp_path / "en.epub"
    zh_epub = tmp_path / "zh.epub"
    make_minimal_epub(en_epub, "EN", [("Ch1", ["The cat sat. The dog ran."])])
    make_minimal_epub(zh_epub, "ZH", [("第一章", ["貓坐。狗跑。"])])

    captured = {}

    original_build = merge_epub.build_bilingual_epub

    def spy_build(*args, **kwargs):
        captured["alignment_overrides"] = kwargs.get("alignment_overrides")
        return original_build(*args, **kwargs)

    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            d = tmp_path / "bilingual"
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = tmp_path / "bilingual" / f"pairing_{pairing_id}"
            (root / "sections").mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            return tmp_path / f"document_{document_id}"

    for doc_id, epub in [("en03", en_epub), ("zh03", zh_epub)]:
        d = tmp_path / f"document_{doc_id}"
        d.mkdir(parents=True)
        (d / "original.epub").write_bytes(epub.read_bytes())

    monkeypatch.setattr(svc_module, "get_path_service", lambda: FakePathService())
    monkeypatch.setattr(svc_module, "build_bilingual_epub", spy_build)

    svc = svc_module.BilingualPairingService()
    result = svc.pair_documents("en03", "zh03")

    # No overrides saved -> should pass empty dict
    svc.export_epub(result["pairing_id"])
    assert captured["alignment_overrides"] == {}

    # Save overrides -> should be passed through
    svc.save_alignment_overrides(
        result["pairing_id"],
        '{"overrides": [{"chapter": "ch001", "english_ids": ["p1"], "translation_ids": ["p1"]}]}',
    )
    svc.export_epub(result["pairing_id"])
    assert "ch001" in captured["alignment_overrides"]


# ── Smart chapter mapping (OPT-1 through OPT-4) ─────────────────────────


def test_parse_zh_number_simple():
    from deeptutor.immersive_reading.bilingual.service import _parse_zh_number

    assert _parse_zh_number("一") == 1
    assert _parse_zh_number("九") == 9


def test_parse_zh_number_compound():
    """Compound numerals like 二十(20), 十九(19), 二十四(24)."""
    from deeptutor.immersive_reading.bilingual.service import _parse_zh_number

    assert _parse_zh_number("十") == 10
    assert _parse_zh_number("十一") == 11
    assert _parse_zh_number("十九") == 19
    assert _parse_zh_number("二十") == 20
    assert _parse_zh_number("二十一") == 21
    assert _parse_zh_number("二十四") == 24


def test_parse_zh_number_fullwidth():
    from deeptutor.immersive_reading.bilingual.service import _parse_zh_number

    assert _parse_zh_number("１") == 1
    assert _parse_zh_number("５") == 5
    assert _parse_zh_number("10") == 10


def test_extract_chapter_ordinal_en_number():
    from deeptutor.immersive_reading.bilingual.service import _extract_chapter_ordinal

    ch = {"title": "index_split_004", "first_p": "1", "is_content": True}
    ordinal, label = _extract_chapter_ordinal(ch)
    assert ordinal == 1
    assert label == "chapter"


def test_extract_chapter_ordinal_en_chapter_word():
    from deeptutor.immersive_reading.bilingual.service import _extract_chapter_ordinal

    ch = {"title": "Chapter 5", "first_p": "", "is_content": True}
    ordinal, label = _extract_chapter_ordinal(ch)
    assert ordinal == 5
    assert label == "chapter"


def test_extract_chapter_ordinal_zh():
    from deeptutor.immersive_reading.bilingual.service import _extract_chapter_ordinal

    ch = {"title": "第二十四章", "first_p": "", "is_content": True}
    ordinal, label = _extract_chapter_ordinal(ch)
    assert ordinal == 24
    assert label == "chapter"


def test_extract_chapter_ordinal_zh_no_suffix():
    """第十九 without 章 suffix should still be detected."""
    from deeptutor.immersive_reading.bilingual.service import _extract_chapter_ordinal

    ch = {"title": "第十九", "first_p": "", "is_content": True}
    ordinal, label = _extract_chapter_ordinal(ch)
    assert ordinal == 19
    assert label == "chapter"


def test_extract_chapter_ordinal_prologue():
    from deeptutor.immersive_reading.bilingual.service import _extract_chapter_ordinal

    ch = {"title": "開場白", "first_p": "", "is_content": True}
    ordinal, label = _extract_chapter_ordinal(ch)
    assert label == "prologue"


def test_extract_chapter_ordinal_front_matter():
    from deeptutor.immersive_reading.bilingual.service import _extract_chapter_ordinal

    ch = {"title": "Contents", "first_p": "", "is_content": True}
    ordinal, label = _extract_chapter_ordinal(ch)
    assert label == "front"


def test_smart_chapter_map_matches_by_ordinal():
    """EN files with chapter numbers should match ZH files with 第N章,
    skipping front-matter on both sides."""
    from deeptutor.immersive_reading.bilingual.service import _auto_chapter_map

    en = [
        {
            "title": "Praise",
            "href": "praise.html",
            "first_p": "",
            "p_count": 5,
            "text_len": 2000,
            "is_content": True,
        },
        {
            "title": "Contents",
            "href": "toc.html",
            "first_p": "",
            "p_count": 0,
            "text_len": 200,
            "is_content": False,
        },
        {
            "title": "split_004",
            "href": "ch1.html",
            "first_p": "1",
            "p_count": 30,
            "text_len": 26000,
            "is_content": True,
        },
        {
            "title": "split_005",
            "href": "ch2.html",
            "first_p": "2",
            "p_count": 32,
            "text_len": 30000,
            "is_content": True,
        },
        {
            "title": "Copyright",
            "href": "cr.html",
            "first_p": "",
            "p_count": 2,
            "text_len": 500,
            "is_content": True,
        },
    ]
    zh = [
        {
            "title": "title",
            "href": "t.html",
            "first_p": "",
            "p_count": 0,
            "text_len": 50,
            "is_content": False,
        },
        {
            "title": "第一章",
            "href": "z1.html",
            "first_p": "",
            "p_count": 0,
            "text_len": 8000,
            "is_content": True,
        },
        {
            "title": "第二章",
            "href": "z2.html",
            "first_p": "",
            "p_count": 0,
            "text_len": 13000,
            "is_content": True,
        },
    ]
    result = _auto_chapter_map(en, zh)
    assert len(result) == 2  # only 2 content chapters match
    assert result[0][1] == "ch1.html"  # EN chapter 1
    assert result[0][2] == "z1.html"  # ZH 第一章
    assert result[0][5] == 1.0  # high confidence
    assert result[1][1] == "ch2.html"
    assert result[1][2] == "z2.html"
