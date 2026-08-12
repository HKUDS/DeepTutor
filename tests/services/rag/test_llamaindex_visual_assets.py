from __future__ import annotations

from pathlib import Path

import pymupdf

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.pipelines.llamaindex.visual_assets import build_visual_assets


def _write_image(path: Path, *, dark: bool = False, offset: int = 0) -> None:
    document = pymupdf.open()
    page = document.new_page(width=64, height=64)
    page.draw_rect(
        pymupdf.Rect(8 + offset, 8, 56 + offset, 56),
        color=(0, 0, 0) if dark else (0.7, 0.7, 0.7),
        fill=(0.2, 0.2, 0.2) if dark else (0.9, 0.9, 0.9),
    )
    page.get_pixmap(alpha=False).save(path)
    document.close()


def _parsed(asset_dir: Path, blocks: list[dict]) -> ParsedDocument:
    return ParsedDocument(
        markdown="# fixture",
        blocks=blocks,
        asset_dir=asset_dir,
        source_hash="source-hash",
        parser_signature="parser-signature",
        engine="mineru",
    )


def _image_block(
    path: Path | str,
    *,
    page: int,
    bbox: list[int],
    caption: str = "",
    footnote: str = "",
) -> dict:
    return {
        "type": "image",
        "page_idx": page,
        "bbox": bbox,
        "img_path": str(path),
        "image_caption": [caption] if caption else [],
        "image_footnote": [footnote] if footnote else [],
    }


def test_structured_blocks_index_only_referenced_safe_assets(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    referenced = asset_dir / "referenced.png"
    unreferenced = asset_dir / "unreferenced.png"
    outside = tmp_path / "outside.png"
    for path in (referenced, unreferenced, outside):
        _write_image(path)

    parsed = _parsed(
        asset_dir,
        [
            _image_block(
                "images/referenced.png",
                page=2,
                bbox=[100, 100, 500, 500],
                caption="Figure 2",
            ),
            _image_block(outside, page=2, bbox=[500, 100, 900, 500], caption="Figure 3"),
            _image_block(
                asset_dir / "missing.png",
                page=2,
                bbox=[100, 500, 500, 900],
                caption="Figure 4",
            ),
            # A traversal reference must be rejected even when its basename
            # matches a legitimate file already present in asset_dir.
            _image_block(
                "../images/referenced.png",
                page=2,
                bbox=[500, 500, 900, 900],
                caption="Figure 5",
            ),
        ],
    )

    assets = build_visual_assets(parsed, origin=tmp_path / "book.pdf")

    assert len(assets) == 1
    assert assets[0].components[0].path == referenced.resolve()
    assert assets[0].figure_id == "Figure 2"
    assert unreferenced.resolve() not in {
        component.path for asset in assets for component in asset.components
    }


def test_asset_preserves_page_hierarchy_and_semantic_anchor_precedence(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    image = asset_dir / "figure.png"
    _write_image(image)
    blocks = [
        # MinerU commonly emits both chapter and section headings at level 2.
        {"type": "text", "text": "Chapter 1 Numbers", "text_level": 2, "page_idx": 4},
        {"type": "text", "text": "1.2 Comparing values", "text_level": 2, "page_idx": 4},
        {"type": "text", "text": "See Figure 1.2-3 for the ordering.", "page_idx": 4},
        _image_block(
            image,
            page=4,
            bbox=[100, 200, 700, 700],
            caption="Figure 1.2-3",
            footnote="Values increase to the right.",
        ),
        {"type": "page_number", "text": "17", "page_idx": 4},
    ]

    [asset] = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert asset.index_role == "semantic"
    assert asset.grouping_state == "separate_assets"
    assert asset.chapter == "Chapter 1 Numbers"
    assert asset.section == "1.2 Comparing values"
    assert asset.pdf_page_index == 4
    assert asset.pdf_page_number == 5
    assert asset.printed_page_number == "17"
    assert asset.nearby_text_before == "See Figure 1.2-3 for the ordering."
    assert asset.nearby_text_after == ""
    assert asset.logical_bbox == (100.0, 200.0, 700.0, 700.0)


def test_repeated_tiny_unanchored_markers_are_layout_markers(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    blocks: list[dict] = []
    for page in range(7):
        path = asset_dir / f"marker-{page}.png"
        _write_image(path, dark=True, offset=page % 2)
        blocks.extend(
            [
                {"type": "text", "text": f"Lesson material {page}", "page_idx": page},
                _image_block(path, page=page, bbox=[120, 150 + page * 100, 150, 175 + page * 100]),
            ]
        )

    assets = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert len(assets) == 7
    assert {asset.index_role for asset in assets} == {"layout_marker"}


def test_unique_tiny_unanchored_image_remains_uncertain(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    repeated = asset_dir / "repeated.png"
    unique = asset_dir / "unique.png"
    _write_image(repeated)
    _write_image(unique, dark=True)
    blocks = [
        _image_block(repeated, page=1, bbox=[120, 300, 150, 325]),
        _image_block(unique, page=2, bbox=[700, 700, 730, 725]),
    ]

    assets = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert [asset.index_role for asset in assets] == ["uncertain", "uncertain"]


def test_contiguous_components_with_one_shared_figure_id_form_logical_group(
    tmp_path: Path,
) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    paths = [asset_dir / f"panel-{index}.png" for index in range(3)]
    for path in paths:
        _write_image(path)
    blocks = [
        {"type": "text", "text": "The development of numbers (图1.1-1).", "page_idx": 8},
        _image_block(
            paths[0],
            page=8,
            bbox=[86, 305, 305, 421],
            footnote="Counting created 1, 2, 3, ...",
        ),
        _image_block(
            paths[1],
            page=8,
            bbox=[355, 320, 548, 419],
            footnote="Zero represented an empty place.",
        ),
        _image_block(
            paths[2],
            page=8,
            bbox=[608, 326, 865, 422],
            caption="图1.1-1",
            footnote="Measurement created fractions.",
        ),
    ]

    [asset] = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert asset.figure_id == "图1.1-1"
    assert asset.grouping_state == "logical_group"
    assert [component.block_index for component in asset.components] == [1, 2, 3]
    assert [component.path for component in asset.components] == [path.resolve() for path in paths]
    assert asset.logical_bbox == (86.0, 305.0, 865.0, 422.0)


def test_component_figure_ids_with_shared_root_form_logical_group(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    first = asset_dir / "panel-a.png"
    second = asset_dir / "panel-b.png"
    _write_image(first)
    _write_image(second, dark=True)
    blocks = [
        _image_block(first, page=3, bbox=[100, 200, 400, 500], caption="Figure 2(a)"),
        _image_block(second, page=3, bbox=[450, 200, 750, 500], caption="Figure 2(b)"),
    ]

    [asset] = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert asset.grouping_state == "logical_group"
    assert asset.figure_id == "Figure 2"
    assert len(asset.components) == 2


def test_different_figure_ids_stay_separate(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    first = asset_dir / "first.png"
    second = asset_dir / "second.png"
    _write_image(first)
    _write_image(second, dark=True)
    blocks = [
        _image_block(first, page=3, bbox=[100, 200, 400, 500], caption="图1.1-4"),
        _image_block(second, page=3, bbox=[450, 200, 750, 500], caption="图1.1-5"),
    ]

    assets = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert [asset.figure_id for asset in assets] == ["图1.1-4", "图1.1-5"]
    assert all(asset.grouping_state == "separate_assets" for asset in assets)


def test_body_text_or_page_boundary_prevents_grouping(tmp_path: Path) -> None:
    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    paths = [asset_dir / f"component-{index}.png" for index in range(4)]
    for path in paths:
        _write_image(path)
    blocks = [
        _image_block(paths[0], page=3, bbox=[100, 200, 350, 450]),
        {"type": "text", "text": "Independent explanation", "page_idx": 3},
        _image_block(paths[1], page=3, bbox=[400, 200, 650, 450], caption="Figure 3"),
        _image_block(paths[2], page=4, bbox=[100, 200, 350, 450]),
        _image_block(paths[3], page=5, bbox=[400, 200, 650, 450], caption="Figure 4"),
    ]

    assets = build_visual_assets(_parsed(asset_dir, blocks), origin=tmp_path / "book.pdf")

    assert len(assets) == 4
    assert all(asset.grouping_state == "separate_assets" for asset in assets)
