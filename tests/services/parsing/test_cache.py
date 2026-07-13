from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.parsing import cache


def test_source_hash_keys_on_bytes_not_name(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    a.write_bytes(b"hello")
    b = tmp_path / "b.pdf"  # different name, same bytes
    b.write_bytes(b"hello")
    c = tmp_path / "c.pdf"
    c.write_bytes(b"world")
    assert cache.source_hash_from_path(a) == cache.source_hash_from_path(b)
    assert cache.source_hash_from_path(a) != cache.source_hash_from_path(c)


def test_reserve_lookup_manifest_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    assert cache.lookup(root, "h1", "s1") is None

    workdir = cache.reserve(root, "h1", "s1")
    (workdir / "doc.md").write_text("# hi", encoding="utf-8")
    # No manifest yet → still a miss (half-written dir never reads as ready).
    assert cache.lookup(root, "h1", "s1") is None

    cache.write_manifest(workdir, {"engine": "x"})
    assert cache.lookup(root, "h1", "s1") == workdir


def test_reserve_clears_stale_incomplete_dir(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    first = cache.reserve(root, "h", "s")
    (first / "junk.txt").write_text("partial", encoding="utf-8")
    # No manifest → next reserve wipes the incomplete dir.
    second = cache.reserve(root, "h", "s")
    assert second == first
    assert not (second / "junk.txt").exists()


def test_load_ir_reads_markdown_blocks_images(tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "doc.md").write_text("# title", encoding="utf-8")
    (workdir / "doc_content_list.json").write_text(
        json.dumps([{"type": "text", "text": "t"}]), encoding="utf-8"
    )
    (workdir / "images").mkdir()

    markdown, blocks, asset_dir = cache.load_ir(workdir)
    assert markdown == "# title"
    assert blocks == [{"type": "text", "text": "t"}]
    assert asset_dir == workdir / "images"


def test_load_ir_markdown_only(tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "doc.md").write_text("# only md", encoding="utf-8")
    markdown, blocks, asset_dir = cache.load_ir(workdir)
    assert markdown == "# only md"
    assert blocks is None
    assert asset_dir is None


def test_load_ir_handles_nested_auto_dir(tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    auto = workdir / "exam" / "auto"
    auto.mkdir(parents=True)
    (auto / "exam.md").write_text("# nested", encoding="utf-8")
    markdown, _blocks, _assets = cache.load_ir(workdir)
    assert markdown == "# nested"
