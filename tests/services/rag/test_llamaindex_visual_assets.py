from __future__ import annotations

from pathlib import Path

from deeptutor.services.parsing.types import ParsedDocument


def test_structured_visual_assets_only_include_safe_referenced_files(
    tmp_path: Path, caplog
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex.visual_assets import (
        build_structured_visual_assets,
    )

    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    referenced = asset_dir / "figure.png"
    referenced.write_bytes(b"image")
    unreferenced = asset_dir / "unused.png"
    unreferenced.write_bytes(b"unused")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")

    parsed = ParsedDocument(
        markdown="Body",
        asset_dir=asset_dir,
        source_hash="source-hash",
        parser_signature="parser-v1",
        blocks=[
            {
                "type": "image",
                "img_path": str(referenced),
                "page_idx": 2,
                "bbox": [10, 20, 30, 40],
                "image_caption": ["Figure 1"],
            },
            {"type": "image", "img_path": str(asset_dir / "missing.png")},
            {"type": "image", "img_path": str(outside)},
            {"type": "image", "img_path": "../outside.png"},
            {"type": "text", "img_path": str(unreferenced), "text": "not visual"},
        ],
    )

    assets = build_structured_visual_assets(parsed, origin=tmp_path / "book.pdf")

    assert "Skipped unsafe or missing structured visual reference" in caplog.text
    assert len(assets) == 1
    asset = assets[0]
    assert asset.path == referenced
    assert asset.resource_type == "image"
    assert asset.block_index == 0
    assert asset.page_index == 2
    assert asset.bbox == (10.0, 20.0, 30.0, 40.0)
    assert asset.caption == "Figure 1"
    assert asset.source_hash == "source-hash"
    assert asset.parser_signature == "parser-v1"
    assert len(asset.asset_id) == 64


def test_structured_table_asset_preserves_parser_text(tmp_path: Path) -> None:
    from deeptutor.services.rag.pipelines.llamaindex.visual_assets import (
        build_structured_visual_assets,
    )

    asset_dir = tmp_path / "images"
    asset_dir.mkdir()
    table = asset_dir / "table.png"
    table.write_bytes(b"image")
    parsed = ParsedDocument(
        markdown="Body",
        asset_dir=asset_dir,
        source_hash="source-hash",
        parser_signature="parser-v1",
        blocks=[
            {
                "type": "table",
                "img_path": str(table),
                "table_caption": ["Table 1"],
                "table_body": "Year | Value\n2026 | 42",
            }
        ],
    )

    asset = build_structured_visual_assets(parsed, origin=tmp_path / "book.pdf")[0]

    assert asset.text == "Year | Value\n2026 | 42"
