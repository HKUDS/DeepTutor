"""Overview-anchored rebuild (v0.5): English "Unit N" textbooks.

Real 译林 production shape (09-11 实锤): each unit opens with a title line
+ 「一、单元概述」 page. The number may sit in a ``discarded_blocks`` header
("UNIT 4" split off the theme title) while the theme title stays a para
``title`` block; Unit 1's title line often carries no number at all. The
「使用说明」 page's digit-prefixed 「1. 单元概述」 must never anchor.
"""

from __future__ import annotations

from deeptutor.textbook_struct.chapter_rebuild import rebuild_with_fallback
from deeptutor.textbook_struct.overview_anchor import rebuild_from_overview


def _page(page_idx: int, blocks: list[dict], discarded: list[dict] | None = None) -> dict:
    page = {"page_idx": page_idx, "para_blocks": blocks}
    if discarded:
        page["discarded_blocks"] = discarded
    return page


def _title(text: str, y: float = 100.0) -> dict:
    return {
        "type": "title",
        "bbox": [90, y, 400, y + 30],
        "lines": [{"spans": [{"content": text}]}],
    }


def _text(text: str) -> dict:
    return {"type": "text", "bbox": [89, 220, 520, 260], "lines": [{"spans": [{"content": text}]}]}


def _header(text: str) -> dict:
    return {
        "type": "header",
        "bbox": [104, 64, 147, 137],
        "lines": [{"spans": [{"content": text}]}],
    }


def _anchor(name: str, unit_header: str | None = None) -> tuple[list[dict], list[dict] | None]:
    """One unit home page: theme title + 一、单元概述 (optionally a UNIT N header)."""
    blocks = [_title(name), _title("一、单元概述", y=186)]
    discarded = [_header(unit_header)] if unit_header else None
    return blocks, discarded


def _layout(pages: list[dict]) -> dict:
    return {"pdf_info": pages}


# ── 正常锚定：3 Unit 书样例 ───────────────────────────────────────────────


def test_rebuild_normal_three_units() -> None:
    blocks1, disc1 = _anchor("The mass media")  # Unit 1 无序号 → 补齐为 1
    blocks2, disc2 = _anchor("Sports culture", "UNIT 2")
    blocks3, disc3 = _anchor("Fit for life", "UNIT 3")
    layout = _layout(
        [
            _page(0, [_title("封面")]),
            _page(1, blocks1, disc1),
            _page(2, [_text("unit1 body")]),
            _page(3, blocks2, disc2),
            _page(4, [_text("unit2 body")]),
            _page(5, blocks3, disc3),
            _page(6, [_text("unit3 body")]),
        ]
    )
    chapters = rebuild_from_overview(layout)
    assert [c.title for c in chapters] == [
        "导览",
        "Unit 1 The mass media",
        "Unit 2 Sports culture",
        "Unit 3 Fit for life",
        "附录",
    ]
    assert [c.page_idx for c in chapters] == [0, 1, 3, 5, 6]
    # assign_page_ranges 语义：end = 下一章起始页；导览覆盖 [0, 1)，附录覆盖 [6, 6].
    assert chapters[0].end_page_idx == 1
    assert chapters[-1].end_page_idx == 6
    # 序号落 meta，供显示层/去重使用.
    assert [c.meta["unit_no"] for c in chapters[1:-1]] == [1, 2, 3]


# ── 无锚页（纯中文书）返回空 list，不得误报 ──────────────────────────────


def test_rebuild_no_anchor_returns_empty() -> None:
    layout = _layout(
        [
            _page(0, [_title("第一章 集合与常用逻辑用语")]),
            _page(1, [_title("第二章 一元二次函数")]),
        ]
    )
    assert rebuild_from_overview(layout) == []


def test_fallback_keeps_chinese_books_empty() -> None:
    # 中文书（无 UNIT 锚）即使 0 章也不走第三通道 —— 返回空 list 走降级表.
    layout = _layout(
        [
            _page(0, [_title("第一章 集合与常用逻辑用语")]),
            _page(1, [_text("正文")]),
        ]
    )
    assert rebuild_with_fallback(layout, language="zh", title="高中数学必修一") == []
    # 书名含「英语」但版式无锚（0 章）→ 仍返回空，不硬造章.
    assert rebuild_with_fallback(layout, language="zh", title="英语必修一") == []


# ── Unit 序号乱序：扫描页序 Unit 3 在 Unit 1 前，仍按序号排序 ─────────────


def test_rebuild_out_of_order_units_sorted() -> None:
    blocks3, disc3 = _anchor("Sports culture", "UNIT 3")
    blocks1, disc1 = _anchor("The mass media")  # 无号 → 补齐缺失的 1
    blocks2, disc2 = _anchor("Fit for life", "UNIT 2")
    layout = _layout(
        [
            _page(0, blocks3, disc3),  # 扫描序：3, 无号, 2
            _page(1, blocks1, disc1),
            _page(2, blocks2, disc2),
        ]
    )
    chapters = rebuild_from_overview(layout)
    assert [c.title for c in chapters] == [
        "Unit 1 The mass media",
        "Unit 2 Fit for life",
        "Unit 3 Sports culture",
    ]
    assert [c.meta["unit_no"] for c in chapters] == [1, 2, 3]


# ── 首页前导页归导览章 ───────────────────────────────────────────────────


def test_rebuild_front_matter_to_overview() -> None:
    blocks, disc = _anchor("The mass media")
    layout = _layout(
        [
            _page(0, [_title("封面")]),
            _page(1, [_text("使用说明")]),
            _page(2, blocks, disc),  # 首个 Unit 首页
        ]
    )
    chapters = rebuild_from_overview(layout)
    assert chapters[0].title == "导览"
    assert chapters[0].page_idx == 0
    assert chapters[0].end_page_idx == 2  # 导览覆盖 [0, 2)


# ── 真实版式防误报：使用说明页「1. 单元概述」不得锚 ───────────────────────


def test_rebuild_usage_page_digit_prefix_not_anchored() -> None:
    # 使用说明页的「1. 单元概述」是数字前缀 text 块 —— 不是「一、」字面.
    usage = _page(
        0,
        [
            _title("《普通高中教科书·英语 教师教学用书》"),
            _text("本书按单元编排，每单元共有五个部分：单元概述、单元教学内容、…"),
            _text("1. 单元概述：综述本单元主题语境…"),
        ],
    )
    blocks, disc = _anchor("The mass media", "UNIT 1")
    layout = _layout([usage, _page(1, blocks, disc)])
    chapters = rebuild_from_overview(layout)
    assert [c.title for c in chapters] == ["导览", "Unit 1 The mass media"]
    assert chapters[1].page_idx == 1  # 没有从 page 0（使用说明）锚出伪 Unit


# ── 前 1 页对位：UNIT N 序号落在首页前一页的标题行 ───────────────────────


def test_rebuild_unit_number_on_prev_page() -> None:
    # Unit 首页标题无序号，但前一页标题行带 UNIT 2（判据 2：首页或其前 1 页）.
    prev = _page(0, [_title("UNIT 2 Sports culture")])  # 前一页是上一单元尾页
    blocks, disc = _anchor("Sports culture")  # 首页只有主题名 + 概述锚
    layout = _layout([prev, _page(1, blocks, disc)])
    chapters = rebuild_from_overview(layout)
    assert [c.title for c in chapters] == ["导览", "Unit 2 Sports culture"]
    assert chapters[1].page_idx == 1
    assert chapters[1].meta["unit_no"] == 2


# ── 同 Unit 多锚页去重：保留页序最早者 ───────────────────────────────────


def test_rebuild_same_unit_multi_anchor_deduped() -> None:
    # 跨页长单元出现第二个「一、单元概述」时只保留首个（序号相同）.
    blocks, disc = _anchor("The mass media")
    page3 = _page(3, [_title("Unit 1 单元练习"), _title("一、单元概述", y=186)], [])
    layout = _layout(
        [
            _page(1, blocks, disc),
            page3,
        ]
    )
    chapters = rebuild_from_overview(layout)
    assert [c.title for c in chapters] == ["导览", "Unit 1 The mass media"]
    assert chapters[1].page_idx == 1  # 保留页序最早的锚页


# ── 全半角 + 大小写不敏感的 Unit 序号 ─────────────────────────────────────


def test_rebuild_fullwidth_and_lowercase_unit() -> None:
    blocks, disc = _anchor("Sports culture", "ｕｎｉｔ　２")  # 全角字母 + 全角空格
    layout = _layout([_page(0, blocks, disc)])
    chapters = rebuild_from_overview(layout)
    assert chapters[0].title == "Unit 2 Sports culture"
    assert chapters[0].meta["unit_no"] == 2


# ── fallback 链接线：en/英语书启用第三通道 ───────────────────────────────


def test_fallback_enables_third_channel_for_english() -> None:
    blocks, disc = _anchor("The mass media")
    # 页眉/页脚法对英语书 0 章（无第N章 running header），第三通道接管.
    layout = _layout(
        [
            _page(0, [_text("cover")]),
            _page(1, blocks, disc),
            _page(2, [_text("body")]),
        ]
    )
    chapters = rebuild_with_fallback(layout, language="en", title="英语 必修一")
    assert [c.title for c in chapters] == ["导览", "Unit 1 The mass media", "附录"]
    # 语言标记 zh 但书名含「英语」→ 书名信号同样启用第三通道（任务书条件）.
    assert [c.title for c in rebuild_with_fallback(layout, language="zh", title="英语 必修一")] == [
        "导览",
        "Unit 1 The mass media",
        "附录",
    ]


def test_fallback_keeps_chinese_title_off() -> None:
    # 语言 zh + 书名不含英语 → 第三通道不启用，0 章返回空（由降级表接管）.
    blocks, disc = _anchor("The mass media")
    layout = _layout(
        [
            _page(0, [_text("cover")]),
            _page(1, blocks, disc),
            _page(2, [_text("body")]),
        ]
    )
    assert rebuild_with_fallback(layout, language="zh", title="数学必修一") == []


def test_fallback_returns_headers_when_present() -> None:
    # 第一通道（页眉法）有章时直接返回，不落第三通道.
    layout = _layout(
        [
            _page(0, [_text("cover")], []),
            {
                "page_idx": 1,
                "para_blocks": [],
                "discarded_blocks": [
                    {"type": "header", "lines": [{"spans": [{"content": "集合 第1章"}]}]}
                ],
            },
        ]
    )
    chapters = rebuild_with_fallback(layout, language="en")
    assert [c.title for c in chapters] == ["第1章 集合"]
    assert [c.page_idx for c in chapters] == [1]
