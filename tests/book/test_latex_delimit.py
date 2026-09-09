"""Tests for P5 bare-LaTeX delimiter completion (latex_delimit)."""

from __future__ import annotations

import pytest

from deeptutor.book.latex_delimit import (
    delimit_bare_latex,
    fix_book,
)


def test_page8_real_sample_wraps_every_bare_command() -> None:
    """老板贴的人教A版选必一页8 段落：无定界裸命令必须全部入 $...$。"""
    body = (
        "（2）如图1.1-3，已知向量 \\overrightarrow{OA}、\\overrightarrow{OB}，"
        "以 OA、OB 为邻边作平行四边形 OA CB，则对角线 \\overrightarrow{OC} "
        "就是表示向量 \\overrightarrow{OA} 与 \\overrightarrow{OB} 的和的向量。"
        "当 \\lambda>0 时，\\lambda \\overrightarrow{OA} 与 \\overrightarrow{OA} 方向相同；"
        "当 \\lambda<0 时，方向相反。设 \\alpha 为实数，则 a_1 满足 \\mu \\overrightarrow{AB}。"
    )
    fixed = delimit_bare_latex(body)
    assert "\\overrightarrow{OA}" in fixed  # only ever inside $...$
    assert "$\\overrightarrow{OA}$" in fixed
    assert "$\\overrightarrow{OB}$" in fixed
    assert "$\\overrightarrow{OC}$" in fixed
    assert "$\\lambda$" in fixed
    assert "$\\alpha$" in fixed
    assert "$\\mu$" in fixed
    assert "$a_1$" in fixed
    # Chinese prose untouched
    assert "如图1.1-3，已知向量" in fixed


def test_arg_chain_frac_wrapped() -> None:
    assert delimit_bare_latex("斜率为 \\frac{a}{b} 的直线") == "斜率为 $\\frac{a}{b}$ 的直线"


def test_greek_solo_commands_wrapped() -> None:
    assert delimit_bare_latex("其中 \\pi、\\mu 与 \\omega 均为常数") == (
        "其中 $\\pi$、$\\mu$ 与 $\\omega$ 均为常数"
    )


def test_subsup_with_chinese_adjacency_wrapped() -> None:
    assert delimit_bare_latex("当 x^2>0 时成立，而 a_1 是首项") == (
        "当 $x^2$>0 时成立，而 $a_1$ 是首项"
    )


def test_already_delimited_math_untouched_and_idempotent() -> None:
    body = "定界的 $\\lambda$ 与 \\(\\mu\\) 以及 $$\\pi$$ 都不动。"
    once = delimit_bare_latex(body)
    assert once == body
    assert delimit_bare_latex(once) == body


def test_currency_prices_untouched() -> None:
    body = "这本书定价 $5，那本 $10，合计不便宜。"
    assert delimit_bare_latex(body) == body


def test_inline_code_and_fenced_code_untouched() -> None:
    body = "行内 `\\lambda x^2` 与代码块\n```\n\\overrightarrow{OA}\n```\n都不动。"
    assert delimit_bare_latex(body) == body


def test_markdown_links_and_bare_urls_untouched() -> None:
    body = "见 [图1.1-3](https://x.com/a_1) 或 https://example.com/\\lambda 直接查看。"
    assert delimit_bare_latex(body) == body


def test_english_sentence_untouched() -> None:
    body = "The value x^2 and y_1 are variables 如下所示。"
    assert delimit_bare_latex(body) == body


def test_textbf_not_wrapped_but_inner_command_is() -> None:
    # \text is whitelisted but \text inside \textbf must not be split out.
    body = "注意 \\textbf{重点} 与 \\overline{AB} 的区别。"
    fixed = delimit_bare_latex(body)
    assert "\\textbf{重点}" in fixed
    assert "$\\overline{AB}$" in fixed


def test_unknown_command_untouched() -> None:
    body = "宏 \\blabla{X} 不在白名单内。"
    assert delimit_bare_latex(body) == body


def test_adjacent_command_chain_wrapped_as_separate_spans() -> None:
    fixed = delimit_bare_latex("如图，\\lambda\\overrightarrow{OA} 共线。")
    assert "$\\lambda$" in fixed
    assert "$\\overrightarrow{OA}$" in fixed


def test_chinese_book_title_marks_do_not_block_wrapping() -> None:
    fixed = delimit_bare_latex("书里《函数》讲到 \\alpha 时。")
    assert "$\\alpha$" in fixed


class _FakeStorage:
    def __init__(self, book, pages: list) -> None:
        self.book = book
        self.pages = {p.id: p for p in pages}
        self.saved_pages: list[str] = []
        self.logs: list[str] = []

    def load_book(self, book_id: str):
        return self.book

    def save_book(self, book) -> None:
        self.book = book

    def list_pages(self, book_id: str) -> list:
        return list(self.pages.values())

    def save_page(self, page) -> None:
        self.saved_pages.append(page.id)

    def append_log(self, book_id: str, message: str, op: str = "info") -> None:
        self.logs.append(message)


@pytest.fixture()
def book_with_bare_body(monkeypatch, tmp_path):
    from deeptutor.book.models import Block, BlockType, Book, Page

    body = "如图，已知 \\overrightarrow{OA}，当 \\lambda>0 时同向。"
    page = Page(
        id="pg_1",
        book_id="bk_x",
        title="页8",
        blocks=[Block(type=BlockType.READING, params={"body": body})],
    )
    book = Book(id="bk_x", title="书", language="zh", revision=3)
    storage = _FakeStorage(book, [page])
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: storage)
    return storage, page, body


def test_fix_book_dry_run_changes_nothing(book_with_bare_body) -> None:
    storage, page, body = book_with_bare_body
    summary = fix_book("bk_x", dry_run=True)
    assert summary["blocks_fixed"] == 1
    assert summary["dry_run"] is True
    assert storage.saved_pages == []
    assert page.blocks[0].params["body"] == body
    assert storage.book.revision == 3


def test_fix_book_applies_and_bumps_revision(book_with_bare_body) -> None:
    storage, page, body = book_with_bare_body
    summary = fix_book("bk_x")
    assert summary["blocks_fixed"] == 1
    assert storage.saved_pages == ["pg_1"]
    assert "$\\overrightarrow{OA}$" in page.blocks[0].params["body"]
    assert "$\\lambda$" in page.blocks[0].params["body"]
    assert storage.book.revision == 4
    assert any("latex_delimit" in m for m in storage.logs)


def test_fix_book_missing_book_raises(monkeypatch) -> None:
    storage = _FakeStorage(None, [])
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: storage)
    with pytest.raises(ValueError):
        fix_book("bk_missing")
