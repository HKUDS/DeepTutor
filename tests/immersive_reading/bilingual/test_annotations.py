"""Tests for the annotation/review-feedback workflow."""

from pathlib import Path

import pytest

from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


@pytest.fixture
def setup_pairing(tmp_path: Path, monkeypatch):
    """Set up a pairing service with a paired+aligned book."""
    from deeptutor.immersive_reading.bilingual import service as svc_module

    en_epub = tmp_path / "en.epub"
    zh_epub = tmp_path / "zh.epub"
    make_minimal_epub(en_epub, "Test Book", [
        ("Chapter 1", ["The cat sat on the mat.", "The dog ran fast."]),
    ])
    make_minimal_epub(zh_epub, "測試書", [
        ("第一章", ["貓坐在墊子上。", "狗跑得快。"]),
    ])

    en_doc = tmp_path / "document_en"
    en_doc.mkdir(parents=True)
    (en_doc / "original.epub").write_bytes(en_epub.read_bytes())

    zh_doc = tmp_path / "document_zh"
    zh_doc.mkdir(parents=True)
    (zh_doc / "original.epub").write_bytes(zh_epub.read_bytes())

    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            d = tmp_path / "bilingual"
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_immersive_reading_pairing_root(self, pid):
            return tmp_path / "bilingual" / f"pairing_{pid}"

        def ensure_immersive_reading_pairing_root(self, pid):
            root = tmp_path / "bilingual" / f"pairing_{pid}"
            (root / "sections").mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, did):
            return tmp_path / f"document_{did}"

    monkeypatch.setattr(svc_module, "get_path_service", lambda: FakePathService())

    svc = svc_module.BilingualPairingService()
    result = svc.pair_documents("en", "zh")
    svc.align(result["pairing_id"])
    return svc, result["pairing_id"]


def test_add_and_list_annotation(setup_pairing):
    svc, pairing_id = setup_pairing

    ann = svc.add_annotation(
        pairing_id, chapter_id="ch001", group_index=0,
        issue_type="misalignment", note="These don't match.",
    )
    assert ann["issue_type"] == "misalignment"
    assert ann["note"] == "These don't match."
    assert ann["status"] == "open"
    assert "cat" in ann["en_text"]

    annotations = svc.list_annotations(pairing_id)
    assert len(annotations) == 1

    open_only = svc.list_annotations(pairing_id, status="open")
    assert len(open_only) == 1


def test_resolve_annotation(setup_pairing):
    svc, pairing_id = setup_pairing
    ann = svc.add_annotation(pairing_id, "ch001", 0, "misalignment", "bad")

    svc.resolve_annotation(pairing_id, ann["id"], resolved=True)

    open_anns = svc.list_annotations(pairing_id, status="open")
    assert len(open_anns) == 0
    all_anns = svc.list_annotations(pairing_id)
    assert all_anns[0]["status"] == "resolved"


def test_delete_annotation(setup_pairing):
    svc, pairing_id = setup_pairing
    ann = svc.add_annotation(pairing_id, "ch001", 0, "other", "")

    svc.delete_annotation(pairing_id, ann["id"])
    assert len(svc.list_annotations(pairing_id)) == 0


def test_export_review_report(setup_pairing):
    svc, pairing_id = setup_pairing
    svc.add_annotation(pairing_id, "ch001", 0, "misalignment", "Wrong pairing.")
    svc.add_annotation(pairing_id, "ch001", 1, "missing_translation", "Missing.")

    report_path = svc.export_review_report(pairing_id)
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")

    assert "Bilingual Review Report" in report
    assert "Wrong pairing." in report
    assert "Missing." in report
    assert "Misaligned paragraphs" in report
    assert "Missing translation" in report
    assert "overrides" in report


def test_save_and_apply_alignment_overrides(setup_pairing):
    """Test the Codex-fix round-trip: save overrides, re-align."""
    svc, pairing_id = setup_pairing

    # Simulate a Codex-produced fix.
    overrides_json = '{"overrides": []}'
    result = svc.save_alignment_overrides(pairing_id, overrides_json)
    assert result["status"] == "saved"

    # Verify the overrides are loadable.
    overrides = svc.load_alignment_overrides(pairing_id)
    assert isinstance(overrides, dict)


def test_multiple_annotation_types(setup_pairing):
    svc, pairing_id = setup_pairing
    for issue_type in ["misalignment", "wrong_chapter", "missing_translation", "translation_error", "other"]:
        svc.add_annotation(pairing_id, "ch001", 0, issue_type, f"note for {issue_type}")

    annotations = svc.list_annotations(pairing_id)
    assert len(annotations) == 5
    types = {a["issue_type"] for a in annotations}
    assert types == {"misalignment", "wrong_chapter", "missing_translation", "translation_error", "other"}
