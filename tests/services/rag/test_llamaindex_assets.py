"""Tests for LlamaIndex figure freeze, retrieval sources, and page matching."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from deeptutor.services.rag.pipelines.llamaindex.assets import (
    ImageAssetSource,
    attach_figure_fields,
    freeze_image_assets,
    index_asset_url,
    load_asset_manifest,
    match_images_for_source,
    page_from_filename,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_page_from_filename_recognizes_parser_exports() -> None:
    assert page_from_filename("page-3.png") == "3"
    assert page_from_filename("doc_page_12_img_1.png") == "12"
    assert page_from_filename("figure-1.png") == ""


def test_freeze_copies_into_version_assets_and_writes_manifest(tmp_path: Path) -> None:
    origin = tmp_path / "paper.pdf"
    origin.write_bytes(b"%PDF")
    cache = tmp_path / "parse_cache" / "images"
    cache.mkdir(parents=True)
    source_file = cache / "page-2.png"
    source_file.write_bytes(PNG)

    storage_dir = tmp_path / "kb" / "version-1"
    node = SimpleNamespace(
        image_path=str(source_file),
        image_mimetype="image/png",
        metadata={
            "file_name": "paper.pdf",
            "content_type": "image",
            "image_description": "A circuit diagram",
        },
    )

    payload = freeze_image_assets(
        storage_dir,
        [ImageAssetSource(path=source_file, origin=origin, page="2")],
        [node],
    )

    frozen = storage_dir / "assets" / "paper.pdf" / "page-2.png"
    assert frozen.is_file()
    assert frozen.read_bytes() == PNG
    assert node.image_path == str(frozen)
    assert node.metadata["asset_rel_path"] == "paper.pdf/page-2.png"
    assert "parse_cache" not in node.metadata["asset_rel_path"]

    records = payload["assets"]
    assert len(records) == 1
    assert records[0]["origin_name"] == "paper.pdf"
    assert records[0]["page"] == "2"
    assert records[0]["rel_path"] == "paper.pdf/page-2.png"

    reloaded = load_asset_manifest(storage_dir)
    assert reloaded["assets"][0]["rel_path"] == "paper.pdf/page-2.png"


def test_match_images_prefers_same_page_and_caps(tmp_path: Path) -> None:
    storage_dir = tmp_path / "version-1"
    origin = tmp_path / "notes.pdf"
    origin.write_bytes(b"%PDF")
    images = tmp_path / "imgs"
    images.mkdir()
    sources = []
    for name, page in (("page-1.png", "1"), ("page-2.png", "2"), ("page-2b.png", "2")):
        path = images / name
        path.write_bytes(PNG)
        sources.append(ImageAssetSource(path=path, origin=origin, page=page))
    freeze_image_assets(storage_dir, sources, [])
    manifest = load_asset_manifest(storage_dir)

    page_two = match_images_for_source(
        manifest, origin_name="notes.pdf", page="2", kb_name="circuits", cap=3
    )
    assert len(page_two) == 2
    assert all("/api/knowledge-bases/circuits/index-assets/" in item["image_url"] for item in page_two)
    assert all("parse_cache" not in item["image_url"] for item in page_two)
    assert all(not str(item["image_url"]).startswith("/") or item["image_url"].startswith("/api/") for item in page_two)

    no_page = match_images_for_source(
        manifest, origin_name="notes.pdf", page="", kb_name="circuits", cap=2
    )
    assert len(no_page) == 2


def test_attach_figure_fields_emits_image_url_and_related_figures(tmp_path: Path) -> None:
    origin = tmp_path / "paper.pdf"
    origin.write_bytes(b"%PDF")
    cache = tmp_path / "page-1.png"
    cache.write_bytes(PNG)
    storage_dir = tmp_path / "version-1"
    freeze_image_assets(
        storage_dir,
        [ImageAssetSource(path=cache, origin=origin, page="1")],
        [],
    )
    manifest = load_asset_manifest(storage_dir)

    image_item = attach_figure_fields(
        {
            "title": "paper.pdf",
            "content": "[Image] paper.pdf",
            "source": str(origin),
            "page": "1",
            "chunk_id": "img-1",
            "score": 0.91,
            "content_type": "image",
        },
        meta={
            "file_name": "paper.pdf",
            "file_path": str(origin),
            "content_type": "image",
            "image_description": "A gate diagram",
            "asset_rel_path": "paper.pdf/page-1.png",
            "page": "1",
        },
        kb_name="circuits",
        manifest=manifest,
        image_mimetype="image/png",
    )
    text_item = attach_figure_fields(
        {
            "title": "paper.pdf",
            "content": "NAND gates are universal.",
            "source": str(origin),
            "page": "1",
            "chunk_id": "txt-1",
            "score": 0.8,
            "content_type": "text",
        },
        meta={
            "file_name": "paper.pdf",
            "file_path": str(origin),
            "asset_origin": "paper.pdf",
            "page": "1",
        },
        kb_name="circuits",
        manifest=manifest,
    )

    assert image_item["content_type"] == "image"
    assert image_item["image_url"] == index_asset_url("circuits", "paper.pdf/page-1.png")
    assert image_item["image_description"] == "A gate diagram"
    assert "image_path" not in image_item
    assert text_item["images"]
    assert text_item["images"][0]["image_url"] == image_item["image_url"]
    dumped = str(image_item) + str(text_item)
    assert str(cache) not in dumped
    assert "parse_cache" not in dumped
