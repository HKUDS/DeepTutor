"""Visual-asset cleanup is owned by ``remove_raw_document``.

Deleted documents leave extracted figures and manifest entries behind unless
someone reclaims them, and the vector index cannot help: figures live in
``visual_assets/``, outside every provider. The HTTP delete route used to do
this itself; the GitHub and web source syncs only call
``remove_raw_document``, so the shared deletion layer is the only place all
three paths can be fixed once.
"""

from __future__ import annotations

from io import BytesIO
import json
import logging
from pathlib import Path

from PIL import Image
import pytest

from deeptutor.knowledge.add_documents import remove_raw_document
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.visual_assets import (
    VisualAssetStore,
    collect_visual_assets,
)


def _make_kb(tmp_path: Path) -> Path:
    kb_dir = tmp_path / "kb"
    (kb_dir / "raw").mkdir(parents=True)
    return kb_dir


def _make_source(kb_dir: Path, relative: str) -> Path:
    source = kb_dir / "raw" / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(f"source bytes for {relative}".encode())
    return source


def _publish_figure(kb_dir: Path, source: Path, *, tag: str) -> str:
    """Publish one figure through the real indexing path; return its asset id."""
    assets = kb_dir.parent / "parse-cache" / tag
    assets.mkdir(parents=True)
    image = assets / "figure.png"
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color=(17, 99, 211)).save(buffer, format="PNG")
    image.write_bytes(buffer.getvalue())
    parsed = ParsedDocument(
        markdown="![figure](figure.png)",
        blocks=[{"type": "image", "img_path": str(image), "image_caption": [tag]}],
        asset_dir=assets,
        source_hash=f"source-hash-{tag}",
        parser_signature=f"parser-signature-{tag}",
        engine="mineru",
    )
    candidates = collect_visual_assets(parsed, source, kb_dir)
    assert len(candidates) == 1
    VisualAssetStore(kb_dir).publish(candidates)
    return candidates[0].record["asset_id"]


def _asset_file(kb_dir: Path, asset_id: str) -> Path:
    return VisualAssetStore(kb_dir).root / f"{asset_id}.png"


def test_remove_raw_document_reclaims_asset_file_and_manifest_entry(tmp_path: Path) -> None:
    kb_dir = _make_kb(tmp_path)
    # A nested raw/ path pins the shared key rule: indexing records the POSIX
    # path relative to raw/, so cleanup must match that exact key.
    doc = _make_source(kb_dir, "papers/2024/lesson.pdf")
    asset_id = _publish_figure(kb_dir, doc, tag="lesson")
    store = VisualAssetStore(kb_dir)
    assert asset_id in store.records()

    removal = remove_raw_document(kb_dir, doc)

    assert removal.rel_path == "papers/2024/lesson.pdf"
    assert not doc.exists()
    assert asset_id not in store.records()
    assert not _asset_file(kb_dir, asset_id).exists()


def test_remove_raw_document_keeps_other_documents_assets(tmp_path: Path) -> None:
    kb_dir = _make_kb(tmp_path)
    removed = _make_source(kb_dir, "removed.pdf")
    kept = _make_source(kb_dir, "kept.pdf")
    removed_asset = _publish_figure(kb_dir, removed, tag="removed")
    kept_asset = _publish_figure(kb_dir, kept, tag="kept")
    store = VisualAssetStore(kb_dir)

    remove_raw_document(kb_dir, removed)

    assert removed_asset not in store.records()
    assert kept_asset in store.records()
    assert _asset_file(kb_dir, kept_asset).exists()
    assert kept.exists()


def test_delete_without_visual_assets_creates_no_directory(tmp_path: Path) -> None:
    kb_dir = _make_kb(tmp_path)
    doc = _make_source(kb_dir, "plain.txt")
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {"plain.txt": "deadbeef"}}), encoding="utf-8"
    )

    remove_raw_document(kb_dir, doc)

    assert not doc.exists()
    assert not (kb_dir / "visual_assets").exists()


@pytest.mark.parametrize("failure", ["remove_source", "manifest_read"])
def test_asset_cleanup_failure_does_not_block_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    kb_dir = _make_kb(tmp_path)
    doc = _make_source(kb_dir, "broken.pdf")
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {"broken.pdf": "deadbeef"}}), encoding="utf-8"
    )
    if failure == "remove_source":

        def fail_remove(self, _path: str) -> None:
            raise OSError("manifest is unreadable")

        monkeypatch.setattr(VisualAssetStore, "remove_source", fail_remove)
    else:

        def fail_read(self) -> dict:
            raise OSError("manifest is unreadable")

        monkeypatch.setattr(VisualAssetStore, "_read_manifest", fail_read)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.add_documents"):
        removal = remove_raw_document(kb_dir, doc)

    # The raw delete still happens and the swallowed failure is diagnosable.
    assert not doc.exists()
    assert removal.was_indexed is True
    assert any(
        record.levelno == logging.WARNING and "visual assets" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize("caller", ["github_source/sync.py", "web_source/sync.py"])
def test_shared_helper_is_sufficient_for_sync_deletions(tmp_path: Path, caller: str) -> None:
    """Both syncs only call ``remove_raw_document``; that alone must reclaim."""
    kb_dir = _make_kb(tmp_path)
    doc = _make_source(kb_dir, "page.md")
    asset_id = _publish_figure(kb_dir, doc, tag="page")
    store = VisualAssetStore(kb_dir)
    assert asset_id in store.records()

    # Exactly what both sync paths do: resolve the target under raw/ and call
    # remove_raw_document. Neither calls remove_source itself.
    remove_raw_document(kb_dir, doc)

    assert not doc.exists(), f"{caller} left the raw file behind"
    assert asset_id not in store.records(), f"{caller} left the manifest entry behind"
    assert not _asset_file(kb_dir, asset_id).exists(), f"{caller} left the image behind"
