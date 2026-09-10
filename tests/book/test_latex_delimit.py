"""Tests for P5 bare-LaTeX delimiter completion (latex_delimit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.book.latex_delimit import (
    FRAGMENT_RE,
    _segments,
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


# ── P5fix：payload 才是 GET /pages 服务端读取的真相源 ─────────────────────────


@pytest.fixture()
def book_with_rendered_body(monkeypatch):
    """存量书的实际形态：reading 块 params 与 payload 各持一份正文。"""
    from deeptutor.book.models import Block, BlockStatus, BlockType, Book, Page

    body = "如图，已知 \\overrightarrow{OA}，当 \\lambda>0 时同向。"
    page = Page(
        id="pg_9",
        book_id="bk_x",
        title="页8",
        blocks=[
            Block(
                type=BlockType.READING,
                status=BlockStatus.READY,
                params={"body": body, "variant": "prose", "source_label": "textbook"},
                payload={"body": body, "format": "markdown", "author": "textbook"},
            )
        ],
    )
    book = Book(id="bk_x", title="书", language="zh", revision=7)
    storage = _FakeStorage(book, [page])
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: storage)
    return storage, page


def test_fix_book_writes_payload_layer_not_just_params(book_with_rendered_body) -> None:
    """09-09 实锤回归：只改 params，API 永远返回 0 处定界。两层都要落。"""
    storage, page = book_with_rendered_body
    summary = fix_book("bk_x")

    assert summary["blocks_fixed"] == 1
    block = page.blocks[0]
    assert "$\\overrightarrow{OA}$" in block.payload["body"]
    assert "$\\lambda$" in block.payload["body"]
    assert "$\\overrightarrow{OA}$" in block.params["body"]
    assert block.payload["format"] == "markdown"
    assert block.payload["author"] == "textbook"
    assert block.params["variant"] == "prose"


def test_fix_book_dry_run_leaves_payload_untouched(book_with_rendered_body) -> None:
    storage, page = book_with_rendered_body
    summary = fix_book("bk_x", dry_run=True)

    assert summary["blocks_fixed"] == 1
    assert storage.saved_pages == []
    block = page.blocks[0]
    assert "$" not in block.payload["body"]
    assert "$" not in block.params["body"]


# ── P5fix 召回补丁：整行/整段数学主体 ────────────────────────────────────────


def _bare_commands(text: str) -> list[str]:
    """Whitelisted ``\\command`` occurrences outside any math delimiter."""
    bare: list[str] = []
    for chunk, protected in _segments(text):
        if protected:
            continue
        bare.extend(m.group(0) for m in FRAGMENT_RE.finditer(chunk))
    return bare


def _load_leak_fixture() -> dict:
    path = Path(__file__).parent / "fixtures" / "latex_delimit_page8_leaks.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_connective_equation_line_wrapped_whole() -> None:
    """老板原样样本：连等式整行包一个 $...$，题号与句末分号随行进数学模式。"""
    body = "(1) a+b=\\overrightarrow{OA}+\\overrightarrow{AB}=\\overrightarrow{OB};"
    fixed = delimit_bare_latex(body)
    assert fixed == "$(1) a+b=\\overrightarrow{OA}+\\overrightarrow{AB}=\\overrightarrow{OB};$"
    assert _bare_commands(fixed) == []


def test_command_variable_chain_wrapped_whole() -> None:
    """老板原样样本：\\mu a 这类命令+变量连写逐片段必然漏，整行包才召回。"""
    body = "\\lambda(\\mu a)=(\\lambda\\mu)a"
    fixed = delimit_bare_latex(body)
    assert fixed == "$\\lambda(\\mu a)=(\\lambda\\mu)a$"
    assert _bare_commands(fixed) == []


def test_math_run_between_chinese_wrapped_whole() -> None:
    """数学串夹在中文里（含尾部全角标点）同样整体包，散文留在模式外。"""
    body = "\\lambda(\\mu a)=(\\lambda\\mu)a，即数乘结合律。"
    fixed = delimit_bare_latex(body)
    assert fixed == "$\\lambda(\\mu a)=(\\lambda\\mu)a$，即数乘结合律。"
    assert _bare_commands(fixed) == []


def test_adjacent_chain_without_equation_keeps_fragment_path() -> None:
    """无等号的命令链维持既有逐片段行为，不整段包。"""
    fixed = delimit_bare_latex("如图，\\lambda\\overrightarrow{OA} 共线。")
    assert fixed == "如图，$\\lambda$$\\overrightarrow{OA}$ 共线。"


def test_english_sentence_with_two_commands_untouched() -> None:
    """误判防线：散文词（and/here）让英文句子在构造上出局。"""
    body = "Use \\frac{a}{b} and \\lambda here."
    assert delimit_bare_latex(body) == body


def test_equation_run_wrapped_but_separate_prose_fragments_still_wrapped() -> None:
    """整段包装后，同行剩余裸片段仍走逐片段路径（$...$ 自动受保护）。"""
    body = "因为 a=\\overrightarrow{OA}+\\overrightarrow{AB}，所以 \\lambda 与之共线。"
    fixed = delimit_bare_latex(body)
    assert fixed == "因为 $a=\\overrightarrow{OA}+\\overrightarrow{AB}$，所以 $\\lambda$ 与之共线。"
    assert _bare_commands(fixed) == []


def test_page8_leak_fixture_full_recall_idempotent_no_new_marks() -> None:
    """36 处裸样本修复率 100%、41 处已定界逐字保留、幂等、无误判新增。"""
    fixture = _load_leak_fixture()
    bare_samples = fixture["bare_samples"]
    delimited = fixture["delimited_fragments"]
    lines: list[str] = ["（人教A版选择性必修第一册）页8 本节常用记号："]
    prose_lines: list[str] = []
    for i, sample in enumerate(bare_samples):
        lines.append(sample)
        # 已定界片段按原样嵌进散文行，两两覆盖全部 41 个片段。
        prose = (
            f"记号回顾{i}：{delimited[i % len(delimited)]} 与 "
            f"{delimited[(i + 18) % len(delimited)]} 的含义见上。"
        )
        lines.append(prose)
        prose_lines.append(prose)
    prose_lines.extend(fixture["protections"])
    lines.extend(fixture["protections"])
    body = "\n".join(lines)

    assert len(bare_samples) == 36
    assert _bare_commands(body), "fixture 自身必须带裸命令（否则回归无效）"

    fixed = delimit_bare_latex(body)

    assert _bare_commands(fixed) == []  # 36 处裸全部召回，无一漏网
    assert delimit_bare_latex(fixed) == fixed  # 幂等
    for prose in prose_lines:  # 41 处已定界所在散文行 + 误判防线行逐字不动
        assert prose in fixed, prose
