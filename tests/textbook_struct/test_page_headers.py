"""Running-header chapter rebuild: footer + header channels both.

Some textbooks print the chapter name embedded mid-text in the running
*header* (e.g. “集合第1章” / “空间向量与立体几何 第6章”) while the footer
only carries the publisher name — a footer-only pass then finds 0 chapters.
Header-embedded chapter tokens are extracted and normalized to the
“第N章 章名” shape, sharing the level filter and seen-dedupe with the
footer path.
"""

from __future__ import annotations

from deeptutor.textbook_struct.chapter_rebuild import rebuild_from_headers_level
from deeptutor.textbook_struct.page_headers import (
    normalize_header_chapter,
    page_facts,
)


def _page(page_idx: int, discarded: list[dict]) -> dict:
    return {"page_idx": page_idx, "discarded_blocks": discarded}


def _footer(text: str) -> dict:
    return {"type": "footer", "lines": [{"spans": [{"content": text}]}]}


def _header(text: str) -> dict:
    return {"type": "header", "lines": [{"spans": [{"content": text}]}]}


def _page_number(n: str) -> dict:
    return {"type": "page_number", "lines": [{"spans": [{"content": n}]}]}


# ── normalize: three header forms + mismatch guards ──────────────────────


def test_normalize_embedded_chapter_name_before_token() -> None:
    assert normalize_header_chapter("集合第1章") == "第1章 集合"


def test_normalize_embedded_chapter_name_after_token() -> None:
    assert normalize_header_chapter("空间向量与立体几何 第6章") == "第6章 空间向量与立体几何"


def test_normalize_bare_token() -> None:
    assert normalize_header_chapter("第6章") == "第6章"


def test_normalize_leading_token_keeps_footer_shape() -> None:
    assert normalize_header_chapter("第6章 空间向量与立体几何") == "第6章 空间向量与立体几何"


def test_normalize_rejects_book_title_and_prose() -> None:
    # Book-title-with-year, a plain header without a chapter token, and long
    # prose are not chapter boundaries.
    assert normalize_header_chapter("高中数学人教A版2019") is None
    assert normalize_header_chapter("数学·必修第一册") is None
    assert normalize_header_chapter("a" * 60) is None


# ── page_facts: dual-channel collection ──────────────────────────────────


def test_page_facts_reads_footer_verbatim() -> None:
    footers, printed = page_facts(
        _page(3, [_footer("第一章 集合与常用逻辑用语"), _page_number("12")])
    )
    assert footers == ["第一章 集合与常用逻辑用语"]
    assert printed == "12"


def test_page_facts_reads_header_normalized() -> None:
    footers, printed = page_facts(_page(4, [_header("集合第1章"), _page_number("13")]))
    assert footers == ["第1章 集合"]
    assert printed == "13"


# ── rebuild_from_headers_level: header-driven chapter build, end to end ───


def _header_layout() -> dict:
    """Header layout: chapter name in the running header, each chapter
    starting on its own page (printed numbers enable offset checking).

    physical (1-based) − printed page number stays constant at 1 across the
    book (the cover prints no page number; the body starts at printed 2).
    """
    return {
        "pdf_info": [
            _page(0, [_header("高中数学·必修第一册"), _page_number("1")]),  # cover
            _page(1, [_header("集合与常用逻辑用语 第1章"), _page_number("2")]),
            _page(2, [_header("集合与常用逻辑用语 第1章"), _page_number("3")]),
            _page(19, [_header("一元二次函数、方程和不等式 第2章"), _page_number("20")]),
        ]
    }


def test_rebuild_level_builds_chapters_from_headers() -> None:
    chapters = rebuild_from_headers_level(_header_layout(), unit="章")
    assert [c.title for c in chapters] == [
        "第1章 集合与常用逻辑用语",
        "第2章 一元二次函数、方程和不等式",
    ]
    assert [c.page_idx for c in chapters] == [1, 19]
    assert chapters[0].meta["printed_page"] == 2
    assert chapters[1].meta["printed_page"] == 20
    # Constant offset: physical page − printed page = 1 across the whole book.
    assert verify_offsets_ok(chapters)


def verify_offsets_ok(chapters) -> bool:
    from deeptutor.textbook_struct.chapter_rebuild import verify_offset

    return verify_offset(chapters)["ok"]


def test_rebuild_level_unit_filter_drops_other_levels() -> None:
    # With two-level running headers (rotating “第X章/第Y节” pairs),
    # unit="节" only follows section-level changes.
    layout = {
        "pdf_info": [
            _page(0, [_header("函数 第2章"), _header("函数的概念 第1节"), _page_number("5")]),
            _page(1, [_header("函数 第2章"), _header("函数的表示法 第2节"), _page_number("9")]),
        ]
    }
    chapters = rebuild_from_headers_level(layout, unit="节")
    assert [c.title for c in chapters] == ["第1节 函数的概念", "第2节 函数的表示法"]
