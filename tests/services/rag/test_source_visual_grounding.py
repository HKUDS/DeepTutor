from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pymupdf
import pytest

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.source_visuals import page_image, retrieve_visual, source_state
from deeptutor.services.rag.visual_assets import VisualAssetStore, collect_visual_assets
from deeptutor.services.rag.visual_coverage import coverage_overview, record_coverage


@pytest.fixture
def textbook(tmp_path):
    kb = tmp_path / "kb"
    raw = kb / "raw"
    raw.mkdir(parents=True)
    source = raw / "textbook.pdf"
    pdf = pymupdf.open()
    images = tmp_path / "parse" / "images"
    images.mkdir(parents=True)
    blocks = []
    for i in range(100):
        path = images / f"figure-{i:03d}.png"
        picture = Image.new("RGB", (512, 320), "white")
        draw = ImageDraw.Draw(picture)
        for n in range(20):
            draw.text(
                (20 + (n % 4) * 120, 20 + (n // 4) * 55), f"{i}:{n} / 12 mm", fill=(i, 30, 70)
            )
        picture.save(path)
        page = pdf.new_page()
        page.insert_text((50, 50), f"Figure 1.{i}: Distinct explanation for source {i}")
        page.insert_image(pymupdf.Rect(50, 80, 562, 400), filename=str(path))
        blocks.append(
            {
                "type": "image",
                "img_path": str(path),
                "page_idx": i,
                "image_caption": [f"Figure 1.{i}"],
                "section": f"Chapter {i // 25}",
                "text": f"Distinct explanation for source {i}",
                "group_id": f"panel-{i}",
            }
        )
    page = pdf.new_page()
    page.insert_text((50, 50), "Figure 2.5: vector relationship A -> B, distance 12 mm")
    page.draw_line((60, 90), (240, 90))
    page.insert_text((60, 80), "A")
    page.insert_text((240, 80), "B")
    page = pdf.new_page()
    page.insert_text((50, 50), "Table 3.2: measured values")
    page.insert_text((50, 80), "Header: mass (kg) | speed (m/s)")
    page.insert_text((50, 100), "Row A: 2 | 12; note: measured at 20 C")
    table = images / "table.png"
    Image.new("RGB", (14, 11), (80, 120, 60)).save(table)
    page.insert_image(pymupdf.Rect(50, 120, 64, 131), filename=str(table))
    blocks.append(
        {
            "type": "table",
            "img_path": str(table),
            "page_idx": 101,
            "table_caption": ["Table 3.2"],
            "table_body": "<table><tr><th>mass (kg)</th><th>speed (m/s)</th></tr><tr><td>2</td><td>12</td></tr></table>",
            "table_footnote": ["Measured at 20 C"],
        }
    )
    page = pdf.new_page()
    page.insert_text((50, 50), "Figure 4.1: (a) first panel; (b) second panel")
    page.draw_rect(pymupdf.Rect(50, 80, 200, 200))
    page.draw_circle(pymupdf.Point(300, 140), 60)
    pdf.save(source, deflate=True)
    pdf.close()
    parsed = ParsedDocument(
        markdown="Textbook",
        blocks=blocks,
        asset_dir=images,
        parser_signature="synthetic-v1",
        engine="synthetic",
    )
    candidates = collect_visual_assets(parsed, source, kb)
    VisualAssetStore(kb).publish(candidates)
    record_coverage(parsed, source, kb, candidates)
    return kb, source, parsed, candidates


def test_complete_retention_exact_early_middle_late_and_cross_language(textbook):
    kb, source, parsed, candidates = textbook
    assert len(candidates) == 101
    for number in (0, 50, 99):
        evidence = retrieve_visual(kb, "kb", source_path=source.name, query=f"请解释图1.{number}")
        assert not evidence.error
        record, pixels = evidence.images[0]
        assert record["asset_id"] == candidates[number].record["asset_id"]
        assert pixels == candidates[number].path.read_bytes()
        assert record["group_id"] == f"panel-{number}"
        assert f"source {number}" in evidence.content
        assert "source_document_id" in evidence.sources[0]
        assert "/files/textbook.pdf" in evidence.sources[0]["url"]
        assert evidence.sources[0]["url"].endswith(f"#page={number + 1}")
    overview = coverage_overview(kb, source_path=source.name, offset=100, limit=20)
    assert overview["total_assets"] == 101
    assert len(overview["assets"]) == 1
    assert overview["documents"][0]["retained_count"] == 101
    assert not overview["documents"][0]["whole_document_verified"]


def test_table_headers_units_notes_and_reference_type_are_preserved(textbook):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, figure="表3.2")
    assert not evidence.error
    assert "<th>mass (kg)</th>" in evidence.content
    assert "<td>12</td>" in evidence.content
    assert "Measured at 20 C" in evidence.content
    assert evidence.images[0][0]["page_number"] == 102
    wrong_kind = retrieve_visual(kb, "kb", source_path=source.name, figure="Figure 3.2")
    assert wrong_kind.error == "not_found"
    assert not wrong_kind.images


def test_multi_panel_group_inspects_the_complete_original_page(textbook):
    kb, source, parsed, _ = textbook
    blocks = []
    for n in (0, 1):
        blocks.append(
            {
                "type": "image",
                "img_path": str(parsed.asset_dir / f"figure-{n:03d}.png"),
                "page_idx": 102,
                "image_caption": [f"Figure 4.1 ({chr(97 + n)})"],
                "group_id": "combined-4.1",
            }
        )
    panels = ParsedDocument(
        markdown="",
        blocks=blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="panels",
        engine="synthetic",
    )
    VisualAssetStore(kb).publish(collect_visual_assets(panels, source, kb))
    evidence = retrieve_visual(kb, "kb", source_path=source.name, figure="图4.1")
    assert not evidence.error
    assert evidence.sources[0]["page"] == 103
    assert "first panel" in evidence.content and "second panel" in evidence.content
    assert evidence.images[0][0]["kind"] == "source_page"


def test_vector_and_sparse_caption_resolve_original_page_without_cloud(textbook):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, figure="图2.5")
    assert not evidence.error
    assert evidence.images[0][0]["kind"] == "source_page"
    assert evidence.sources[0]["page"] == 101
    assert "distance 12 mm" in evidence.content
    assert evidence.model_message()["content"][1]["type"] == "image_url"
    crop = retrieve_visual(kb, "kb", source_path=source.name, page=101, region=[0, 0, 0.6, 0.3])
    assert not crop.error
    assert crop.images[0][0]["render_scale"] == 4
    assert "A -> B" in crop.content
    assert "region=" in crop.sources[0]["visual_asset_url"]
    assert crop.images[0][1] != evidence.images[0][1]


def test_same_label_in_two_sources_never_silently_substitutes(textbook):
    kb, source, parsed, candidates = textbook
    other = source.with_name("other.pdf")
    other.write_bytes(source.read_bytes())
    second = collect_visual_assets(parsed, other, kb)
    VisualAssetStore(kb).publish(second)
    ambiguous = retrieve_visual(kb, "kb", query="Explain Figure 1.99")
    assert ambiguous.error == "ambiguous_reference"
    assert not ambiguous.images
    assert "other.pdf" in ambiguous.content and "textbook.pdf" in ambiguous.content
    selected = retrieve_visual(kb, "kb", asset_id=candidates[99].record["asset_id"])
    assert not selected.error
    assert selected.images[0][0]["source_path"] == source.name


def test_explicit_page_hash_and_region_are_not_silently_ignored(textbook):
    kb, source, _, candidates = textbook
    wrong_page = retrieve_visual(kb, "kb", source_path=source.name, figure="Figure 1.99", page=1)
    assert wrong_page.error == "not_found"
    wrong_hash = retrieve_visual(
        kb, "kb", asset_id=candidates[99].record["asset_id"], source_hash="other-source"
    )
    assert wrong_hash.error == "source_identity_mismatch"
    region = retrieve_visual(
        kb, "kb", asset_id=candidates[99].record["asset_id"], region=[0, 0, 0.6, 0.3]
    )
    assert not region.error
    assert region.images[0][0]["kind"] == "source_page"
    assert region.images[0][0]["page_number"] == 100


def test_followup_restart_reindex_and_changed_or_missing_source_identity(textbook):
    kb, source, parsed, candidates = textbook
    old = candidates[99].record["asset_id"]
    newer = ParsedDocument(
        markdown=parsed.markdown,
        blocks=parsed.blocks,
        asset_dir=parsed.asset_dir,
        parser_signature="synthetic-v2",
        engine="synthetic",
    )
    VisualAssetStore(kb).publish(collect_visual_assets(newer, source, kb))
    evidence = retrieve_visual(kb, "kb", asset_id=old)
    assert evidence.images[0][0]["asset_id"] == old
    before = source.read_bytes()
    source.write_bytes(before + b"changed")
    assert source_state(kb, candidates[99].record) == "changed"
    failed = retrieve_visual(kb, "kb", asset_id=old)
    assert failed.error == "source_changed" and not failed.images
    with pytest.raises(ValueError, match="changed"):
        page_image(kb, source.name, 1, expected_hash=candidates[0].record["source_document_id"])
    source.unlink()
    assert retrieve_visual(kb, "kb", asset_id=old).error == "source_missing"


def test_coverage_exclusions_unverified_zero_images_and_pure_read(textbook):
    kb, source, parsed, candidates = textbook
    (parsed.asset_dir / "oversize.png").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    (parsed.asset_dir / "broken.png").write_bytes(b"not pixels")
    record_coverage(parsed, source, kb, candidates)
    report = coverage_overview(kb, source_path=source.name)["documents"][0]
    assert {issue["reason"] for issue in report["issues"]} >= {
        "exceeds_5_mib",
        "unsupported_or_invalid_pixels",
        "table_structure_requires_source_verification",
    }
    report_files = {p: p.read_bytes() for p in (kb / "visual_assets").rglob("*") if p.is_file()}
    coverage_overview(kb, source_path=source.name)
    assert all(p.read_bytes() == data for p, data in report_files.items())
    blank = ParsedDocument(markdown="plain text", engine="text_only")
    record_coverage(blank, source, kb, [])
    report = coverage_overview(kb, source_path=source.name)["documents"][0]
    assert report["validated_count"] == 0
    assert not report["whole_document_verified"]
    assert report["page_fallback"]


@pytest.mark.parametrize("region", [[0, 0, 2, 1], [1, 0, 0, 1], [0, 0, float("nan"), 1], [0, 1]])
def test_invalid_regions_are_visible_failures(textbook, region):
    kb, source, _, _ = textbook
    evidence = retrieve_visual(kb, "kb", source_path=source.name, page=1, region=region)
    assert evidence.error == "page_unavailable" and not evidence.images


def test_source_access_is_bounded_to_managed_kb(textbook, tmp_path):
    kb, source, _, _ = textbook
    outside = tmp_path / "private.pdf"
    outside.write_bytes(source.read_bytes())
    (source.parent / "link.pdf").symlink_to(outside)
    for path in ("../private.pdf", str(outside), "link.pdf"):
        with pytest.raises(ValueError):
            page_image(kb, path, 1)


def test_real_rag_tool_exact_grounding_pixels_and_text_only_fallback(textbook, monkeypatch):
    from deeptutor.tools.builtin import RAGTool

    kb, source, _, candidates = textbook
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_for_rag",
        lambda _: SimpleNamespace(base_dir=kb.parent, name=kb.name),
    )
    result = asyncio.run(
        RAGTool().execute(
            kb_name=kb.name, query="解释图1.99", source_path=source.name, _vision_supported=True
        )
    )
    assert result.success and result.model_message
    assert result.sources[0]["visual_asset_id"] == candidates[99].record["asset_id"]
    assert "data:image/png;base64," in result.model_message["content"][1]["image_url"]["url"]
    assert "base64" not in json.dumps(result.metadata)
    text_only = asyncio.run(
        RAGTool().execute(kb_name=kb.name, query="Explain Figure 1.99", source_path=source.name)
    )
    assert text_only.success and text_only.model_message is None
    assert "cannot inspect pixels" in text_only.content
    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", lambda _: None)
    denied = asyncio.run(RAGTool().execute(kb_name=kb.name, query="Explain Figure 1.99"))
    assert not denied.success and not denied.sources


def test_coverage_and_page_http_routes_retain_source_guard_and_hash(textbook, monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import knowledge

    kb, source, _, candidates = textbook
    monkeypatch.setattr(knowledge, "_resolve_kb_raw_dir", lambda _: source.parent)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    client = TestClient(app)
    overview = client.get(
        "/api/knowledge-bases/kb/visual-coverage", params={"source_path": source.name}
    )
    assert overview.status_code == 200
    assert overview.json()["total_assets"] == 101
    page = client.get(
        "/api/knowledge-bases/kb/source-page",
        params={
            "source_path": source.name,
            "page": 101,
            "source_hash": candidates[0].record["source_document_id"],
        },
    )
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.headers["x-source-document-id"] == candidates[0].record["source_document_id"]
    invalid = client.get(
        "/api/knowledge-bases/kb/source-page", params={"source_path": "../secret.pdf", "page": 1}
    )
    assert invalid.status_code == 422

    def deny(_):
        raise HTTPException(status_code=403, detail="Access denied")

    monkeypatch.setattr(knowledge, "_resolve_kb_raw_dir", deny)
    assert client.get("/api/knowledge-bases/kb/visual-coverage").status_code == 403
    assert (
        client.get(
            "/api/knowledge-bases/kb/source-page", params={"source_path": source.name, "page": 1}
        ).status_code
        == 403
    )
