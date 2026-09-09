"""Tests for P5 figure backfill planning + application (figure_backfill)."""

from __future__ import annotations

import pytest

from deeptutor.book.figure_backfill import (
    FigureSource,
    PlanEntry,
    apply_plan,
    build_figure_plan,
    collect_images,
    extract_fig_labels,
    load_content_lists,
)


def _page(page_id: str, title: str, bodies: list[str] | None = None):
    from deeptutor.book.models import Block, BlockType, Page

    blocks = [
        Block(type=BlockType.READING, params={"body": b, "variant": "prose"}) for b in bodies or []
    ]
    return Page(id=page_id, book_id="bk_fig", title=title, blocks=blocks)


def _content_list() -> list[dict]:
    return [
        {"type": "text", "text": "如图1.1-3", "page_idx": 7},
        {
            "type": "image",
            "img_path": "images/fig_a.jpg",
            "img_caption": ["图1.1-3 平行四边形法则"],
            "page_idx": 7,
            "bbox": [1.0, 2.0, 3.0, 4.0],
        },
        {
            "type": "image",
            "img_path": "images/fig_b.jpg",
            "img_caption": [],
            "page_idx": 8,
        },
        {
            "type": "image",
            "img_path": "images/fig_c.jpg",
            "img_caption": ["图2-1 对照组"],
            "page_idx": 20,
        },
    ]


def test_collect_images_reads_caption_and_bbox() -> None:
    images = collect_images(_content_list())
    assert [i.img_path for i in images] == [
        "images/fig_a.jpg",
        "images/fig_b.jpg",
        "images/fig_c.jpg",
    ]
    assert images[0].caption == "图1.1-3 平行四边形法则"
    assert images[0].bbox == [1.0, 2.0, 3.0, 4.0]
    assert images[0].page_idx == 7


def test_extract_fig_labels_requires_separator_and_dedupes() -> None:
    labels = extract_fig_labels("如图1.1-3与图 2-1；又见图1.1-3。孤立说 图1 不算。")
    assert labels == ["1.1-3", "2-1"]


def test_caption_match_wins_over_page_order() -> None:
    pages = [_page("pg_1", "页8", ["由图1.1-3可知，两向量共面。"])]
    plan = build_figure_plan("bk_fig", pages, _content_list())

    assert len(plan.entries) == 1
    entry = plan.entries[0]
    assert entry.page_id == "pg_1"
    assert [(i.source.img_path, i.reason) for i in entry.images] == [
        ("images/fig_a.jpg", "caption")
    ]
    assert plan.unmatched_labels == []
    assert [i.img_path for i in plan.unplaced_images] == ["images/fig_b.jpg", "images/fig_c.jpg"]


def test_caption_image_from_another_page_is_pulled_forward() -> None:
    """跨页：引用页8，图在页21 —— caption 匹配仍应把图带回引用页。"""
    content = _content_list()
    content[1]["page_idx"] = 20  # fig_a lives on pdf page 21
    pages = [_page("pg_1", "页8", ["如图1.1-3，作平行四边形。"])]
    plan = build_figure_plan("bk_fig", pages, content)
    assert [(i.source.img_path, i.reason) for i in plan.entries[0].images] == [
        ("images/fig_a.jpg", "caption")
    ]


def test_uncaptioned_images_fall_back_to_page_title_alignment() -> None:
    pages = [
        _page("pg_8", "页8", ["正文无图引用。"]),
        _page("pg_9", "页9", ["也无引用。"]),
    ]
    plan = build_figure_plan("bk_fig", pages, _content_list())
    # fig_a sits on pdf page 8 (页8), uncaptioned-eligible fig_b on 页9 —
    # page-order fallback assigns each to its aligned book page.
    by_page = {e.page_id: [i.source.img_path for i in e.images] for e in plan.entries}
    assert by_page == {"pg_8": ["images/fig_a.jpg"], "pg_9": ["images/fig_b.jpg"]}


def test_pages_without_numeric_titles_use_spine_position() -> None:
    pages = [_page("pg_a", "第1课时"), _page("pg_b", "第2课时")]
    content = [
        {"type": "image", "img_path": "images/x.png", "img_caption": [], "page_idx": 1},
    ]
    plan = build_figure_plan("bk_fig", pages, content)
    assert [e.page_id for e in plan.entries] == ["pg_b"]
    assert plan.entries[0].images[0].reason == "page"


def test_unmatched_labels_and_page_offset() -> None:
    pages = [_page("pg_1", "页1", ["参考图9-9（本书没有）。"])]
    plan = build_figure_plan("bk_fig", pages, _content_list())
    assert plan.unmatched_labels == ["9-9"]
    assert plan.entries == []

    # 印刷页偏移: 页1（印刷页）→ content_list page_idx 2（pdf 第 3 页）
    content = [{"type": "image", "img_path": "images/off.png", "img_caption": [], "page_idx": 2}]
    shifted = build_figure_plan("bk_fig", [_page("pg_1", "页1")], content, page_offset=2)
    assert [i.source.img_path for i in shifted.entries[0].images] == ["images/off.png"]


def test_load_content_lists_renumbers_part_files(tmp_path) -> None:
    (tmp_path / "part1_content_list.json").write_text(
        '[{"type": "image", "img_path": "a.png", "page_idx": 0}]', encoding="utf-8"
    )
    (tmp_path / "part2_content_list.json").write_text(
        '[{"type": "image", "img_path": "b.png", "page_idx": 3}]', encoding="utf-8"
    )
    (tmp_path / "part2_content_list_v2.json").write_text("[]", encoding="utf-8")
    items, content_dir = load_content_lists(tmp_path)
    assert content_dir == tmp_path
    assert [i["page_idx"] for i in items if i["type"] == "image"] == [0, 4]


def test_apply_plan_copies_files_and_inserts_reading_blocks(tmp_path) -> None:
    import asyncio

    content_dir = tmp_path / "parse"
    (content_dir / "images").mkdir(parents=True)
    (content_dir / "images" / "fig_a.jpg").write_bytes(b"\xff\xd8fake")

    inserted: list[tuple[str, str]] = []

    class _Engine:
        class storage:  # noqa: N801
            @staticmethod
            def ensure_book_root(book_id: str):
                root = tmp_path / "book_bk_fig"
                root.mkdir(exist_ok=True)
                return root

        async def insert_block(self, *, book_id, page_id, block_type, params, compile_now):
            inserted.append((page_id, params["body"]))
            return object()

    pages = [_page("pg_1", "页8", ["如图1.1-3，作平行四边形。"])]
    plan = build_figure_plan("bk_fig", pages, _content_list())
    summary = asyncio.run(apply_plan(_Engine(), "bk_fig", plan, content_dir=content_dir))

    assert summary["blocks_inserted"] == 1
    assert summary["images_copied"] == 1
    page_id, body = inserted[0]
    assert page_id == "pg_1"
    assert "![图1.1-3 平行四边形法则](/api/books/bk_fig/assets/figures/fig_a.jpg)" in body
    assert (tmp_path / "book_bk_fig" / "assets" / "figures" / "fig_a.jpg").read_bytes() == (
        b"\xff\xd8fake"
    )


def test_apply_plan_skips_missing_source_files(tmp_path) -> None:
    import asyncio

    inserted: list = []

    class _Engine:
        class storage:  # noqa: N801
            @staticmethod
            def ensure_book_root(book_id: str):
                return tmp_path

        async def insert_block(self, **kwargs):
            inserted.append(kwargs)
            return object()

    plan = build_figure_plan(
        "bk_fig",
        [_page("pg_1", "页8", ["如图1.1-3。"])],
        _content_list(),
    )
    summary = asyncio.run(apply_plan(_Engine(), "bk_fig", plan, content_dir=tmp_path / "nowhere"))
    assert inserted == []
    assert summary["blocks_inserted"] == 0


def test_unique_filename_no_collision() -> None:
    from deeptutor.book.figure_backfill import _unique_filename

    taken: set[str] = set()
    assert _unique_filename("a.png", taken) == "a.png"
    assert _unique_filename("a.png", taken) == "a_1.png"


def test_empty_content_list_yields_empty_plan() -> None:
    plan = build_figure_plan("bk_fig", [_page("pg_1", "页1", ["正文。"])], [])
    assert plan.entries == []
    assert plan.image_count == 0


def test_plan_entry_dataclass_defaults() -> None:
    entry = PlanEntry(page_id="p", page_title="t")
    assert entry.images == []
    assert FigureSource(page_idx=0, img_path="x.png").caption == ""
