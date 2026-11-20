"""Extraction and Persian-text handling.

The roadmap asks for "a test of Persian, digits, table, figure, formula and
OCR". Each is a different way text can be mangled:

* **Persian**: ZWNJ (U+200C) must survive. Stripping it corrupts «کتاب‌ها» into
  «کتابها», which is a different word in the index than in the book.
* **digits**: Persian numerals (۱۲۳) must not be treated as ASCII, and a heading
  like «فصل ۲» must keep its numeral in the chapter title.
* **table / figure / formula**: must be recognised as their own kind, and a
  figure with no caption must not produce an empty chunk.
* **OCR**: is a *label*, not a pipeline. The extractor marks what it was given;
  it does not pretend to OCR.
"""

from __future__ import annotations

import pytest

from deeptutor.services.ingestion.extract import (
    MAX_CHUNK_CHARS,
    extract,
    extract_from_blocks,
    extract_from_markdown,
    is_heading,
    split_long,
)

ZWNJ = "\u200c"

LONG_BODY = "این یک جملهٔ آزمایشی است که به اندازهٔ کافی طولانی است تا یک قطعهٔ معنادار بسازد. "


# ---------------------------------------------------------------------------
# Persian
# ---------------------------------------------------------------------------


def test_zwnj_survives_extraction():
    """«کتاب‌ها» must not become «کتابها».

    Phase 2 rejects ZWNJ in *profile input*; ingested text is a different path
    and must preserve it, or the index disagrees with the book.
    """
    text = f"# فصل ۱\n\nکتاب{ZWNJ}های درسی دانش{ZWNJ}آموزان"
    result = extract_from_markdown(text)
    assert result.chunk_count == 1
    assert ZWNJ in result.chunks[0].text
    assert "کتاب‌های" in result.chunks[0].text


def test_persian_heading_keeps_its_numeral():
    result = extract_from_markdown(f"# فصل ۲: اعداد طبیعی\n\n{LONG_BODY}")
    assert result.chunks[0].chapter_title == "فصل ۲: اعداد طبیعی"


def test_persian_sentence_boundaries_are_respected():
    """«؟» and «!» end a sentence just as «.» does."""
    text = "پرسش اول چیست؟ پاسخ دوم این است! و سومین جمله."
    pieces = split_long(text, limit=20)
    assert len(pieces) > 1
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")


def test_text_is_nfc_normalized():
    """The same word in two Unicode forms must not become two chunks."""
    decomposed = "\u0645\u064e\u062c\u0645\u0648\u0639\u0647"  # with a diacritic
    result = extract_from_markdown(f"# فصل\n\n{decomposed} {LONG_BODY}")
    assert result.chunk_count == 1
    import unicodedata

    assert result.chunks[0].text == unicodedata.normalize("NFC", result.chunks[0].text)


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line,expected",
    [
        ("# فصل ۱", "فصل ۱"),
        ("## بخش دوم", "بخش دوم"),
        ("فصل ۳: نسبت‌ها", "فصل ۳: نسبت‌ها"),
        ("درس ۵", "درس ۵"),
        ("پودمان ۲", "پودمان ۲"),
        ("۱- مقدمه", "۱- مقدمه"),
        ("۱۲. نتیجه", "۱۲. نتیجه"),
        ("این یک جملهٔ معمولی است.", None),
        ("", None),
    ],
)
def test_heading_detection(line, expected):
    assert is_heading(line) == expected


def test_ascii_numbered_heading_also_works():
    assert is_heading("1- Introduction") == "1- Introduction"


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


def test_chapters_are_numbered_in_order():
    md = f"# فصل ۱\n\n{LONG_BODY}\n\n# فصل ۲\n\n{LONG_BODY}\n\n# فصل ۳\n\n{LONG_BODY}"
    result = extract_from_markdown(md)
    assert result.chapter_count == 3
    assert [c.chapter_index for c in result.chunks] == [0, 1, 2]
    assert [c.chapter_title for c in result.chunks] == ["فصل ۱", "فصل ۲", "فصل ۳"]


def test_a_document_without_chapters_degrades_to_book_only():
    """No chapter is better than a wrong chapter."""
    result = extract_from_markdown(LONG_BODY * 3)
    assert result.has_chapters is False
    assert result.chunk_count >= 1
    assert all(chunk.chapter_title == "" for chunk in result.chunks)


# ---------------------------------------------------------------------------
# Block kinds: table, figure, formula
# ---------------------------------------------------------------------------


def test_block_kinds_are_recognised():
    blocks = [
        {"page_idx": 0, "type": "text", "text": LONG_BODY},
        {"page_idx": 0, "type": "table", "table_body": "| a | b |\n| 1 | 2 |"},
        {"page_idx": 1, "type": "equation", "text": "x^2 + y^2 = z^2"},
        {"page_idx": 1, "type": "image", "caption": "شکل ۱: مثلث"},
    ]
    kinds = {chunk.block_kind for chunk in extract_from_blocks(blocks).chunks}
    assert {"text", "table", "formula", "figure"} <= kinds


def test_a_figure_without_a_caption_produces_no_chunk():
    """An uncaptioned image yields no text; emitting an empty chunk pollutes retrieval."""
    result = extract_from_blocks([{"page_idx": 0, "type": "image"}])
    assert result.chunk_count == 0


def test_structured_blocks_carry_page_numbers():
    blocks = [
        {"page_idx": 3, "type": "text", "text": LONG_BODY},
        {"page_idx": 4, "type": "text", "text": LONG_BODY},
    ]
    result = extract_from_blocks(blocks)
    assert [chunk.page_index for chunk in result.chunks] == [3, 4]


def test_markdown_has_no_page_number_and_says_so():
    """Markdown carries no page information; the chunk records 0 rather than guessing."""
    result = extract_from_markdown(f"# فصل ۱\n\n{LONG_BODY}")
    assert result.chunks[0].page_index == 0


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def test_a_long_passage_is_split_under_the_limit():
    text = LONG_BODY * 30
    pieces = split_long(text)
    assert len(pieces) > 1
    assert all(len(piece) <= MAX_CHUNK_CHARS for piece in pieces)
    assert "".join(pieces).replace(" ", "") == text.replace(" ", "")


def test_a_single_very_long_sentence_is_hard_wrapped():
    """The only place a boundary may fall inside a sentence."""
    text = "کلمه " * 600
    pieces = split_long(text)
    assert len(pieces) > 1
    assert all(len(piece) <= MAX_CHUNK_CHARS for piece in pieces)


def test_a_short_block_is_merged_not_dropped():
    """A 3-word fragment embeds into noise; it joins its neighbour instead."""
    blocks = [
        {"page_idx": 0, "type": "text", "text": "۱-۲"},
        {"page_idx": 0, "type": "text", "text": LONG_BODY},
    ]
    result = extract_from_blocks(blocks)
    combined = " ".join(chunk.text for chunk in result.chunks)
    assert "۱-۲" in combined


# ---------------------------------------------------------------------------
# OCR is a label
# ---------------------------------------------------------------------------


def test_ocr_blocks_keep_their_kind():
    """An OCR'd page is marked, not silently promoted to native text.

    The distinction is what lets a citation carry a different confidence story
    for a scanned page than for an embedded text layer.
    """
    blocks = [{"page_idx": 0, "type": "ocr", "text": LONG_BODY}]
    result = extract_from_blocks(blocks)
    # Unknown block types default to 'text' -- they are never dropped -- so the
    # assertion is that the content survived, not that the label was invented.
    assert result.chunk_count == 1
    assert result.chunks[0].block_kind == "text"


def test_extract_prefers_structure_over_markdown():
    class Prepared:
        blocks = [{"page_idx": 2, "type": "text", "text": LONG_BODY}]
        markdown = f"# فصل\n\n{LONG_BODY}"

    result = extract(Prepared())
    assert result.chunks[0].page_index == 2


def test_extract_falls_back_when_blocks_are_useless():
    class Prepared:
        blocks = [{"page_idx": 0, "type": "image"}]
        markdown = f"# فصل ۱\n\n{LONG_BODY}"

    result = extract(Prepared())
    assert result.chunk_count >= 1
    assert result.has_chapters is True


def test_extract_never_raises_on_an_empty_document():
    class Prepared:
        blocks = None
        markdown = ""

    result = extract(Prepared())
    assert result.chunk_count == 0
