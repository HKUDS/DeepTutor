"""Tests for the bilingual paragraph alignment core."""

from deeptutor.immersive_reading.bilingual.align import (
    Group,
    plain_text,
    ZhUnit,
    align_groups,
    extract_align_pairs,
    extract_en_paragraphs,
    extract_zh_units,
    feature_set,
    fold_standalone_zh_notes,
)

EN_CHAPTER = """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 1</title></head>
<body>
<h2>Chapter 1</h2>
<p id="p1">The cat sat on the mat. It was a sunny day in 1984.</p>
<p id="p2">The dog ran quickly through the green park nearby.</p>
<p id="p3">A bird sang in the tree above the old wooden bench.</p>
</body>
</html>"""

ZH_CHAPTER = """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>第一章</title></head>
<body>
<h2>第一章</h2>
<p id="z1">貓坐在墊子上。那是1984年的一個晴天。</p>
<p id="z2">狗快速地跑過附近綠色的公園。</p>
<p id="z3">一隻鳥在舊木椅上方的樹上唱歌。</p>
</body>
</html>"""


def test_extract_en_paragraphs():
    paras = extract_en_paragraphs(EN_CHAPTER)
    assert len(paras) == 3
    assert paras[0].tag == "p"
    assert "cat" in paras[0].text
    assert paras[0].ident == "p1"


def test_extract_zh_units():
    units, footnotes = extract_zh_units(ZH_CHAPTER)
    assert len(units) == 3
    assert "貓" in units[0].text
    assert footnotes == ""


def test_align_groups_1_to_1():
    en = extract_en_paragraphs(EN_CHAPTER)
    zh, _ = extract_zh_units(ZH_CHAPTER)
    groups = align_groups(en, zh, "ch01", {})
    assert len(groups) == 3
    for g in groups:
        assert g.en_end - g.en_start == 1
        assert g.zh_end - g.zh_start == 1


def test_extract_align_pairs_shape():
    result = extract_align_pairs(EN_CHAPTER, ZH_CHAPTER, chapter="ch01")
    assert result["chapter"] == "ch01"
    assert result["en_title"] == "Chapter 1"
    assert result["pairs"] == 3
    assert len(result["groups"]) == 3
    for group in result["groups"]:
        assert len(group["en"]) >= 1
        assert len(group["zh"]) >= 1
        assert group["shape"] == "1:1"


def test_extract_align_pairs_empty_zh():
    en_only = '<html><body><p>Hello world.</p></body></html>'
    zh_empty = '<html><body></body></html>'
    result = extract_align_pairs(en_only, zh_empty, chapter="ch")
    assert result["pairs"] == 0
    assert result["groups"] == []


def test_align_1_to_2():
    """One English paragraph maps to two Chinese paragraphs."""
    en = '<html><body><p id="p1">The quick brown fox jumps over the lazy dog. It was a remarkable sight to behold in the morning light.</p></body></html>'
    zh = '<html><body><p id="z1">敏捷的棕色狐狸跳過了懶狗。</p><p id="z2">在晨光中這是一個令人矚目的景象。</p></body></html>'
    result = extract_align_pairs(en, zh, chapter="ch")
    assert result["pairs"] == 2
    # The alignment may produce either 1:2 or two 1:1 groups depending on cost.
    assert len(result["groups"]) >= 1


def test_calibre_br_separator():
    """Calibre bare-text export with <br/> separators."""
    zh = '''<html><body>
<p>第一段文字。<br/>第二段文字。<br/>第三段文字。</p>
</body></html>'''
    units, _ = extract_zh_units(zh)
    # When <br/> count exceeds unit count, synthetic paragraphs are created.
    assert len(units) >= 2


def test_fold_standalone_zh_notes():
    """Translator notes beginning with note markers fold into preceding paragraph."""
    u1 = ZhUnit("p", "", "原文", "原文文字", "", "", "", feature_set("原文文字"))
    u2 = ZhUnit("p", "", "【註】譯註", "【註】譯註內容", "", "", "", feature_set("【註】譯註內容"))
    folded = fold_standalone_zh_notes([u1, u2])
    assert len(folded) == 1
    assert "譯註" in folded[0].text


def test_feature_set():
    feats = feature_set("In 1984 and 2020, chapter 5 had 42 pages of network history.")
    assert "1984" in feats["years"]
    assert "2020" in feats["years"]
    assert "42" in feats["nums"]
    assert feats["len"] > 0


# ── Regression: CJK word-boundary fix + false-2:2 suppression ──────────

def test_feature_set_extracts_years_from_cjk_text():
    """feature_set must find years/numbers embedded in Chinese text.

    Previously, Python's \\b treated CJK characters as word characters, so
    \\b2016\\b failed to match inside '在2016年'. This left ZH feature sets
    nearly empty and made alignment rely on length alone.
    """
    feats = feature_set("在2016年,AlphaGo 擊敗李世乭。到了2024年")
    assert "2016" in feats["years"]
    assert "2024" in feats["years"]
    assert "2016" in feats["nums"]
    assert "alphago" in feats["latin"]


def test_feature_set_extracts_numbers_from_cjk_text():
    """Standalone numbers in CJK context should be captured."""
    feats = feature_set("第3章有42頁,共100個單字。")
    assert "3" in feats["nums"]
    assert "42" in feats["nums"]
    assert "100" in feats["nums"]


def test_false_2_2_resolved_to_1_1():
    """Two EN paragraphs with strong shared keywords (2016, AlphaGo, AI)
    must not be wrongly grouped as 2:2 when the paragraph breaks align 1:1.

    Regression for the Nexus epilogue: the DP picked a 2:2 group (cost 0.251)
    because (a) ZH feature sets were empty due to the \\b bug, and (b)
    feature pooling inflated matching bonuses for combined groups.
    """
    en = (
        '<html><body>'
        '<p id="p1">In late 2016, after AlphaGo defeated Lee Sedol, I published a book '
        "about AI. This opened doors to scientists and world leaders interested in AI.</p>"
        '<p id="p2">It turned out that my research into the Hundred Years War was not '
        "unrelated. Over the past eight years I discussed AI dangers, and by 2024 the "
        "tone became urgent.</p>"
        "</body></html>"
    )
    zh = (
        '<html><body>'
        '<p id="z1">2016年,AlphaGo 擊敗李世乭之後,我出版了關於 AI 的書。'
        "這讓我有機會接觸對 AI 有興趣的科學家和世界領導人。</p>"
        '<p id="z2">結果發現,我對百年戰爭的研究竟也不是完全無關。'
        "在過去八年裡,我討論了 AI 的危險,到了2024年,語調變得更加急迫。</p>"
        "</body></html>"
    )
    result = extract_align_pairs(en, zh, chapter="ch001")
    assert len(result["groups"]) == 2, "Should produce two 1:1 groups, not one 2:2"
    for group in result["groups"]:
        assert group["shape"] == "1:1"
        assert not group["forced"]


def test_review_threshold_does_not_flag_strong_matches():
    """A 1:1 group with a strongly negative cost (great feature match) must
    NOT be flagged for review. Previously, abs(cost) > 1.2 wrongly flagged
    excellent matches like cost=-2.2 (years + keywords shared)."""
    en = (
        '<html><body>'
        '<p id="p1">In 2016, AlphaGo defeated Lee Sedol. This was a pivotal moment for AI.</p>'
        "</body></html>"
    )
    zh = (
        '<html><body>'
        '<p id="z1">2016年,AlphaGo 擊敗李世乭。這是 AI 的關鍵時刻。</p>'
        "</body></html>"
    )
    result = extract_align_pairs(en, zh, chapter="ch")
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["shape"] == "1:1"
    assert group["cost"] < 0  # strong match
    assert not group["low_confidence"], (
        f"Strong match (cost={group['cost']}) should not be flagged for review"
    )


def test_plain_text_unescapes_html_entities():
    """HTML entities like &amp; should be decoded to plain text.

    Regression: 'A &amp; E department' appeared verbatim in aligned text
    instead of 'A & E department'.
    """
    assert plain_text("A &amp; E department") == "A & E department"
    assert plain_text("Bostrom&#39;s") == "Bostrom's"
    assert plain_text("&lt;tag&gt;") == "<tag>"
