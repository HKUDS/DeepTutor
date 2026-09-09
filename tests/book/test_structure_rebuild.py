"""P6 书结构重组测试：节标题提取 / display_title 序号 / 页→节归属 / CLI.

bk_7a519f7e6e 的样本按生产 parse 产品的形状本地构造（人教A选必一：
章标题页 + 1.1/1.2 节首页 + 同节多页），不读任何生产数据。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.book.models import Block, BlockType, Book, Chapter, Page, Spine
import deeptutor.book.storage as storage_module
from deeptutor.book.structure_rebuild import (
    assign_display_titles,
    build_structure_plan,
    collect_section_nodes,
    extract_section_title,
    main,
)
from deeptutor.services.path_service import PathService

# ── 生产样本（本地构造）─────────────────────────────────────────────────────

SAMPLE_KP_TREE = {
    "title": "人教A版高中数学选择性必修第一册",
    "children": [
        {
            "title": "第一章 空间向量与立体几何",
            "level": 1,
            "node_id": "ch01",
            "struct_path": "第一章 空间向量与立体几何",
            "children": [
                {
                    "title": "1.1 空间向量及其加减运算",
                    "level": 3,
                    "node_id": "s101",
                    "struct_path": "第一章 空间向量与立体几何/1.1 空间向量及其加减运算",
                    "type": "mu",
                    "children": [],
                },
                {
                    "title": "1.2 空间向量的数量积运算",
                    "level": 3,
                    "node_id": "s102",
                    "struct_path": "第一章 空间向量与立体几何/1.2 空间向量的数量积运算",
                    "type": "mu",
                    "children": [],
                },
            ],
        }
    ],
}


def _build_storage(tmp_path: Path, monkeypatch) -> storage_module.BookStorage:
    service = PathService(workspace_root=tmp_path / "data")
    storage_module._storages.clear()
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    return storage_module.get_book_storage()


def _reading_page(
    page_id: str, book_id: str, chapter_id: str, title: str, body: str, order: int = 0, n: int = 0
) -> Page:
    return Page(
        id=page_id,
        book_id=book_id,
        chapter_id=chapter_id,
        title=title,
        order=order,
        created_at=1_000_000.0 + n,
        blocks=[Block(type=BlockType.READING, params={"body": body, "variant": "prose"})],
    )


def _seed_sample_book(storage: storage_module.BookStorage, book_id: str = "bk_7a519f7e6e") -> Spine:
    """生产样本形状: 章 4→2 个、页平铺"页N"、canonical_kp_tree 有节节点。"""
    storage.save_book(
        Book(
            id=book_id,
            title="人教A版高中数学选择性必修第一册",
            metadata={"canonical_kp_tree": SAMPLE_KP_TREE},
        )
    )
    spine = Spine(
        book_id=book_id,
        chapters=[
            Chapter(id="ch_c1", title="第一章 空间向量与立体几何", order=0),
            Chapter(id="ch_c2", title="第二章 直线和圆的方程", order=1),
        ],
    )
    storage.save_spine(spine)

    pages = [
        _reading_page(
            "pg_p01", book_id, "ch_c1", "页1", "本章导语：空间向量是研究几何问题的工具。", n=1
        ),
        _reading_page(
            "pg_p07",
            book_id,
            "ch_c1",
            "页7",
            "1.1 空间向量及其加减运算\n空间向量是既有大小又有方向的量……",
            n=2,
        ),
        _reading_page(
            "pg_p08", book_id, "ch_c1", "页8", "1.1 空间向量及其加减运算\n如图，设……", n=3
        ),
        _reading_page("pg_p09", book_id, "ch_c1", "页9", "1.1 空间向量及其加减运算\n例1 ……", n=4),
        _reading_page("pg_p10", book_id, "ch_c1", "页10", "1.2 空间向量的数量积运算\n已知……", n=5),
        _reading_page("pg_p20", book_id, "ch_c2", "页20", "2.1 直线的倾斜角与斜率\n……", n=6),
    ]
    for page in pages:
        storage.save_page(page)
        target = spine.chapters[0] if page.chapter_id == "ch_c1" else spine.chapters[1]
        target.page_ids.append(page.id)
    storage.save_spine(spine)
    return spine


# ── 节标题提取（三形态）──────────────────────────────────────────────────


def test_extract_numbered_section_title() -> None:
    assert extract_section_title("1.1 空间向量及其加减运算\n正文……") == "1.1 空间向量及其加减运算"
    # 全角空格分隔（排版实锤）同样命中
    assert extract_section_title("1.1　空间向量及其加减运算") == "1.1 空间向量及其加减运算"
    # 多级节号（6.2.1）也在节标题族里
    assert extract_section_title("6.2.1 排列问题") == "6.2.1 排列问题"


def test_extract_chapter_pattern_titles() -> None:
    assert extract_section_title("第一章 空间向量与立体几何") == "第一章 空间向量与立体几何"
    assert extract_section_title("第3章") == "第3章"
    assert extract_section_title("第二单元 函数") == "第二单元 函数"


def test_extract_no_match_returns_none() -> None:
    # 正文句子 / 长句 / 页码行都不该被当成标题
    assert extract_section_title("向量是既有大小又有方向的量") is None
    assert extract_section_title("1.1 空间向量有 3 个分量") is None  # 标题体含数字
    assert extract_section_title("") is None


# ── display_title 序号 ───────────────────────────────────────────────────


def test_display_titles_suffix_for_same_section_pages() -> None:
    spine = Spine(book_id="bk_x", chapters=[Chapter(id="ch_1", title="第一章", order=0)])
    pages = [
        _reading_page(f"pg_{i}", "bk_x", "ch_1", f"页{i}", "1.1 空间向量及其加减运算\n……", n=i)
        for i in range(1, 4)
    ]
    titles = assign_display_titles(pages)
    assert titles["pg_1"] == "1.1 空间向量及其加减运算（1/3）"
    assert titles["pg_2"] == "1.1 空间向量及其加减运算（2/3）"
    assert titles["pg_3"] == "1.1 空间向量及其加减运算（3/3）"
    assert spine.chapters[0].children == []  # 计划不触碰 spine


def test_display_titles_single_page_has_no_suffix() -> None:
    spine = Spine(book_id="bk_x", chapters=[Chapter(id="ch_1", title="第一章", order=0)])
    pages = [
        _reading_page("pg_a", "bk_x", "ch_1", "页1", "1.1 空间向量及其加减运算\n……", n=1),
        _reading_page("pg_b", "bk_x", "ch_1", "页2", "1.2 空间向量的数量积运算\n……", n=2),
    ]
    titles = assign_display_titles(pages)
    assert titles["pg_a"] == "1.1 空间向量及其加减运算"
    assert titles["pg_b"] == "1.2 空间向量的数量积运算"


def test_display_titles_no_match_stays_out() -> None:
    pages = [_reading_page("pg_a", "bk", "ch_1", "页1", "导语：本章讲空间向量。")]
    assert assign_display_titles(pages) == {}


# ── 页 → 节归属 ──────────────────────────────────────────────────────────


def test_collect_section_nodes_only_numbered() -> None:
    nodes = collect_section_nodes(SAMPLE_KP_TREE)
    assert [n["title"] for n in nodes] == ["1.1 空间向量及其加减运算", "1.2 空间向量的数量积运算"]


def test_build_plan_maps_pages_to_sections_and_keeps_unmatched_direct() -> None:
    spine = Spine(
        book_id="bk_x",
        chapters=[Chapter(id="ch_1", title="第一章 空间向量与立体几何", order=0)],
    )
    pages = [
        _reading_page("pg_intro", "bk_x", "ch_1", "页1", "本章导语……", n=1),
        _reading_page("pg_1a", "bk_x", "ch_1", "页2", "1.1 空间向量及其加减运算\n……", n=2),
        _reading_page("pg_1b", "bk_x", "ch_1", "页3", "1.1 空间向量及其加减运算\n……", n=3),
        _reading_page("pg_2a", "bk_x", "ch_1", "页4", "1.2 空间向量的数量积运算\n……", n=4),
    ]
    plan = build_structure_plan(spine, pages, SAMPLE_KP_TREE)

    children = plan.chapter_children["ch_1"]
    assert children == [
        {
            "title": "1.1 空间向量及其加减运算",
            "page_ids": ["pg_1a", "pg_1b"],
        },
        {"title": "1.2 空间向量的数量积运算", "page_ids": ["pg_2a"]},
    ]
    # 无节匹配的页不进任何节，保持章直挂（仍在 page_ids，children 之外）
    all_section_pages = {pid for child in children for pid in child["page_ids"]}
    assert "pg_intro" not in all_section_pages
    assert spine.chapters[0].children == []  # build 是纯计算，不写回


def test_build_plan_without_tree_or_matches_is_empty() -> None:
    spine = Spine(book_id="bk_x", chapters=[Chapter(id="ch_1", title="第一章", order=0)])
    pages = [_reading_page("pg_a", "bk_x", "ch_1", "页1", "1.1 空间向量及其加减运算\n……", n=1)]

    # 无树 → 无归属（P6-a 的 display_title 照常产出）
    plan = build_structure_plan(spine, pages, None)
    assert plan.chapter_children == {}
    assert plan.display_titles["pg_a"] == "1.1 空间向量及其加减运算"

    # 树里没有对应节 → 同样无归属
    plan = build_structure_plan(spine, pages, {"title": "别的书", "children": []})
    assert plan.chapter_children == {}


# ── CLI（dry-run 不落盘 / 真跑写回）──────────────────────────────────────


def test_cli_dry_run_on_sample_bk_7a519f7e6e(tmp_path: Path, monkeypatch, capsys) -> None:
    """验收判据 2：页8 的 dry-run 输出应含 1.1 节名，且不落任何盘。"""
    storage = _build_storage(tmp_path, monkeypatch)
    _seed_sample_book(storage)

    exit_code = main(["bk_7a519f7e6e", "--dry-run"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "页8 → 1.1 空间向量及其加减运算（2/3）" in out
    assert "1.1 空间向量及其加减运算" in out
    assert "1.2 空间向量的数量积运算" in out
    assert "(dry-run — nothing written)" in out

    # dry-run 未写回：spine version/children 与页 display_title 原样
    spine = storage.load_spine("bk_7a519f7e6e")
    assert spine is not None and spine.version == 1
    assert all(chapter.children == [] for chapter in spine.chapters)
    page8 = storage.load_page("bk_7a519f7e6e", "pg_p08")
    assert page8 is not None and page8.display_title == ""


def test_cli_persist_writes_display_titles_and_children(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    storage = _build_storage(tmp_path, monkeypatch)
    _seed_sample_book(storage)

    exit_code = main(["bk_7a519f7e6e"])
    out = capsys.readouterr().out
    assert exit_code == 0

    spine = storage.load_spine("bk_7a519f7e6e")
    assert spine is not None and spine.version == 2
    chapter1 = spine.chapters[0]
    assert {"title": "1.1 空间向量及其加减运算", "page_ids": ["pg_p07", "pg_p08", "pg_p09"]} in [
        child for child in chapter1.children
    ]

    page8 = storage.load_page("bk_7a519f7e6e", "pg_p08")
    assert page8 is not None
    assert page8.display_title == "1.1 空间向量及其加减运算（2/3）"

    # 页1 无节匹配 → 无 display_title，保持章直挂
    page1 = storage.load_page("bk_7a519f7e6e", "pg_p01")
    assert page1 is not None and page1.display_title == ""
    assert "written:" in out


def test_cli_missing_book_errors(tmp_path: Path, monkeypatch) -> None:
    _build_storage(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        main(["bk_absent", "--dry-run"])


def test_sample_persisted_manifest_keeps_kp_tree(tmp_path: Path, monkeypatch) -> None:
    """写回流程之后 canonical_kp_tree 缓存仍在（structure_rebuild 不经手 manifest）。"""
    storage = _build_storage(tmp_path, monkeypatch)
    _seed_sample_book(storage)
    main(["bk_7a519f7e6e"])

    book = storage.load_book("bk_7a519f7e6e")
    assert book is not None
    assert book.metadata.get("canonical_kp_tree") == SAMPLE_KP_TREE
