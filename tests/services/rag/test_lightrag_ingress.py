from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from deeptutor.services.parsing import cache as parsing_cache
from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.pipelines.lightrag import ingress, sidecar

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "lightrag_bridge"
REQUIRES_LIGHTRAG = pytest.mark.skipif(
    importlib.util.find_spec("lightrag") is None,
    reason="requires the optional rag-lightrag extra",
)


def _structured(asset_dir: Path | None = None) -> ParsedDocument:
    return ParsedDocument(
        markdown="# Fixture\n\nBody",
        blocks=[
            {
                "type": "text",
                "text": "Fixture",
                "text_level": 1,
                "page_idx": 0,
                "bbox": [1, 2, 3, 4],
            },
            {"type": "text", "text": "Body", "page_idx": 0},
            {"type": "list", "list_items": ["one", "two"], "page_idx": 0},
            {
                "type": "code",
                "code_body": "print('ok')",
                "code_caption": ["Fixture code"],
                "code_footnote": ["Code note"],
                "page_idx": 0,
            },
            {
                "type": "table",
                "table_body": "<table><tr><td>A</td></tr></table>",
                "table_caption": ["Table caption"],
                "page_idx": 1,
            },
            {
                "type": "image",
                "img_path": "images/chart.png",
                "image_caption": ["Chart caption"],
                "page_idx": 1,
            },
            {"type": "equation", "text": "x^2", "page_idx": 1},
        ],
        asset_dir=asset_dir,
        source_hash="source-sha",
        parser_signature="mineru-signature",
        engine="mineru",
    )


def test_freeze_is_an_independent_digest_verified_bundle(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"original pdf")
    assets = tmp_path / "parser-assets"
    (assets / "images").mkdir(parents=True)
    original_asset = assets / "images" / "chart.png"
    original_asset.write_bytes(b"image")
    working = tmp_path / "version-1"

    staged = ingress.freeze_document(working, source, _structured(assets))
    manifest, bundle = ingress.load_verified_bundle(working, "paper.pdf")

    assert staged.source_path.read_bytes() == b"original pdf"
    assert os.stat(staged.source_path).st_ino != os.stat(source).st_ino
    frozen_asset = bundle / manifest["assets"][0]["path"]
    assert frozen_asset.read_bytes() == b"image"
    assert os.stat(frozen_asset).st_ino != os.stat(original_asset).st_ino
    assert manifest["process_options"] == "Pite"
    assert manifest["chunk_options"] == {"paragraph_semantic": {"chunk_token_size": 1200}}

    source.write_bytes(b"mutated pdf")
    original_asset.write_bytes(b"mutated image")
    assert staged.source_path.read_bytes() == b"original pdf"
    assert frozen_asset.read_bytes() == b"image"
    ingress.load_verified_bundle(working, "paper.pdf")


def test_absolute_cached_image_path_is_rewritten_to_frozen_asset(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    assets = tmp_path / "images"
    assets.mkdir()
    image = assets / "figure.png"
    image.write_bytes(b"image")
    parsed = ParsedDocument(
        markdown="figure",
        blocks=[{"type": "image", "img_path": str(image)}],
        asset_dir=assets,
        engine="mineru",
    )

    staged = ingress.freeze_document(tmp_path / "version-1", source, parsed)
    manifest, bundle = ingress.load_verified_bundle(tmp_path / "version-1", staged.canonical_name)
    frozen_blocks = json.loads((bundle / manifest["blocks"]["path"]).read_text())

    assert frozen_blocks[0]["img_path"] == "figure.png"
    assert parsed.blocks[0]["img_path"] == str(image)
    assert (bundle / "assets" / "figure.png").read_bytes() == b"image"


def test_bundle_tamper_and_unsafe_names_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("notes", encoding="utf-8")
    working = tmp_path / "version-1"
    staged = ingress.freeze_document(
        working,
        source,
        ParsedDocument(markdown="notes", engine="text_only", source_hash="h", parser_signature="s"),
    )
    assert staged.process_options == "F"
    (staged.bundle_dir / "markdown.utf8").write_text("tampered", encoding="utf-8")
    with pytest.raises(ingress.IngressError, match="Digest mismatch"):
        ingress.load_verified_bundle(working, "notes.md")
    with pytest.raises(ingress.IngressError, match="Invalid canonical basename"):
        ingress.load_verified_bundle(working, "../notes.md")


def test_bundle_payload_rejects_a_symlinked_parent(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("notes", encoding="utf-8")
    working = tmp_path / "version-1"
    staged = ingress.freeze_document(
        working,
        source,
        ParsedDocument(markdown="notes", engine="text_only"),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_text("notes", encoding="utf-8")
    markdown = staged.bundle_dir / "markdown.utf8"
    markdown.unlink()
    nested = staged.bundle_dir / "nested"
    nested.symlink_to(outside, target_is_directory=True)
    manifest = json.loads(staged.manifest_path.read_text(encoding="utf-8"))
    manifest["markdown"]["path"] = "nested/payload"
    staged.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ingress.IngressError, match="symbolic link"):
        ingress.load_verified_bundle(working, "notes.md")


def test_source_and_assets_reject_links(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    hardlink = tmp_path / "hardlink.pdf"
    os.link(source, hardlink)
    with pytest.raises(ingress.IngressError, match="hard-linked"):
        ingress.freeze_document(tmp_path / "version-hardlink", source, _structured())

    ordinary = tmp_path / "ordinary.pdf"
    ordinary.write_bytes(b"pdf")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "outside.png").write_bytes(b"image")
    (assets / "link.png").symlink_to(assets / "outside.png")
    with pytest.raises(ingress.IngressError, match="symbolic link"):
        ingress.freeze_document(tmp_path / "version-symlink", ordinary, _structured(assets))


def test_same_canonical_basename_is_rejected_before_enqueue(tmp_path: Path) -> None:
    first = tmp_path / "a" / "same.md"
    second = tmp_path / "b" / "same.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    parsed = ParsedDocument(markdown="content", engine="text_only")
    working = tmp_path / "version-1"
    ingress.freeze_document(working, first, parsed)
    with pytest.raises(ingress.IngressError, match="basename already exists"):
        ingress.freeze_document(working, second, parsed)


@REQUIRES_LIGHTRAG
def test_sidecar_maps_structured_fields_and_positions(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"pdf")
    assets = tmp_path / "parser-assets"
    (assets / "images").mkdir(parents=True)
    (assets / "images" / "chart.png").write_bytes(b"image")
    working = tmp_path / "version-1"
    staged = ingress.freeze_document(working, source, _structured(assets))
    manifest, bundle = ingress.load_verified_bundle(working, staged.canonical_name)

    document = sidecar.build_ir(manifest, bundle)

    assert document.document_name == "paper.pdf"
    assert document.doc_title == "Fixture"
    assert document.split_option == {"parser": "mineru", "parser_signature": "mineru-signature"}
    assert len(document.assets) == 1
    assert document.assets[0].source.read_bytes() == b"image"
    block = document.blocks[0]
    assert block.heading == "Fixture"
    assert block.level == 1
    assert "one\ntwo" in block.content_template
    assert "print('ok')" in block.content_template
    assert "Fixture code" in block.content_template
    assert "Code note" in block.content_template
    assert block.tables[0].html.startswith("<table>")
    assert block.drawings[0].caption == "Chart caption"
    assert block.equations[0].latex == "x^2"
    assert block.positions[0].anchor == "1"
    assert block.positions[0].range == [1.0, 2.0, 3.0, 4.0]


@REQUIRES_LIGHTRAG
def test_sidecar_unknown_content_is_preserved_or_rejected(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    blocks = bundle / "blocks.json"
    manifest = {
        "canonical_filename": "doc.pdf",
        "parser": {"engine": "mineru", "parser_signature": "s"},
        "blocks": {"path": "blocks.json"},
        "assets": [],
    }
    blocks.write_text(json.dumps([{"type": "new_semantic", "text": "keep me"}]), encoding="utf-8")
    assert "keep me" in sidecar.build_ir(manifest, bundle).blocks[0].content_template
    blocks.write_text(json.dumps([{"type": "new_semantic"}]), encoding="utf-8")
    with pytest.raises(sidecar.SidecarMappingError, match="no preservable text"):
        sidecar.build_ir(manifest, bundle)


@REQUIRES_LIGHTRAG
def test_sidecar_asset_traversal_is_rejected(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    blocks = bundle / "blocks.json"
    blocks.write_text(
        json.dumps([{"type": "image", "img_path": "../outside.png"}]), encoding="utf-8"
    )
    manifest = {
        "canonical_filename": "doc.pdf",
        "parser": {},
        "blocks": {"path": "blocks.json"},
        "assets": [],
    }
    with pytest.raises(sidecar.SidecarMappingError, match="escapes"):
        sidecar.build_ir(manifest, bundle)


@REQUIRES_LIGHTRAG
def test_official_legacy_mineru_golden_maps_without_private_builder(tmp_path: Path) -> None:
    golden = FIXTURES / "mineru-legacy-official-example" / "content_list.json"
    provenance = json.loads(
        (golden.parent / "deeptutor-fixture-provenance.json").read_text(encoding="utf-8")
    )
    blocks = json.loads(golden.read_text(encoding="utf-8"))
    # The official example's image bytes are not distributed with its docs;
    # the authenticated current capture covers AssetSpec. The exact legacy
    # table/equation/text records remain untouched here.
    bridge_blocks = [block for block in blocks if block.get("type") != "image"]
    source = tmp_path / "legacy.pdf"
    source.write_bytes(b"legacy fixture source")
    working = tmp_path / "version-1"

    staged = ingress.freeze_document(
        working,
        source,
        ParsedDocument(
            markdown="# Legacy fixture",
            blocks=bridge_blocks,
            engine="mineru",
            source_hash=provenance["content_sha256"],
            parser_signature=provenance["commit"],
        ),
    )
    manifest, bundle = ingress.load_verified_bundle(working, staged.canonical_name)
    document = sidecar.build_ir(manifest, bundle)

    assert provenance["kind"] == "official-legacy-schema-example"
    assert document.doc_title == "The response of flow duration curves to afforestation"
    block = document.blocks[0]
    assert block.tables[0].caption.startswith("Table 2")
    assert "Q _ { \\% }" in block.equations[0].latex
    assert {position.anchor for position in block.positions} == {"1", "3", "6"}


@REQUIRES_LIGHTRAG
def test_authenticated_current_mineru_golden_maps_from_public_artifacts(tmp_path: Path) -> None:
    capture = FIXTURES / "mineru-v2-current"
    provenance = json.loads(
        (capture / "deeptutor-fixture-provenance.json").read_text(encoding="utf-8")
    )
    source = (capture / provenance["source"]["path"]).resolve()

    assert provenance["capture_schema"] == 1
    assert provenance["authenticated"] is True
    assert provenance["service"] == "https://mineru.net/api/v4"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == provenance["source"]["sha256"]
    for relative, expected_digest in provenance["artifacts"].items():
        artifact = capture / relative
        assert artifact.is_file()
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_digest

    markdown, blocks, asset_dir = parsing_cache.load_ir(capture)
    assert blocks is not None
    assert asset_dir is not None
    assert {block["type"] for block in blocks} == {"text", "equation", "table", "chart"}

    staged = ingress.freeze_document(
        tmp_path / "version-1",
        source,
        ParsedDocument(
            markdown=markdown,
            blocks=blocks,
            asset_dir=asset_dir,
            engine="mineru",
            source_hash=provenance["source"]["sha256"],
            parser_signature=provenance["model_version"],
        ),
    )
    manifest, bundle = ingress.load_verified_bundle(tmp_path / "version-1", staged.canonical_name)
    document = sidecar.build_ir(manifest, bundle)

    assert document.doc_title == "original"
    assert document.blocks[0].heading == "DeepTutor LightRAG Bridge Fixture"
    assert document.blocks[0].tables[0].caption == "Table 1. Retrieval engine paths"
    assert "E = m c" in document.blocks[0].equations[0].latex
    assert document.blocks[0].drawings[0].caption == "Figure 1. Synthetic trend chart."
    assert len(document.assets) == 1
    assert (
        document.assets[0].source.read_bytes()
        == (asset_dir / Path(blocks[-1]["img_path"]).name).read_bytes()
    )
