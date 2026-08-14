"""Tests for the bilingual pairing service."""

from pathlib import Path

import pytest

from deeptutor.immersive_reading.bilingual.service import (
    _auto_chapter_map,
    _detect_target_lang,
    _read_epub_chapters,
)
from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


@pytest.fixture
def en_epub(tmp_path: Path) -> Path:
    path = tmp_path / "english.epub"
    make_minimal_epub(path, "Test Book", [
        ("Chapter One", ["The cat sat on the mat."]),
        ("Chapter Two", ["The dog ran fast."]),
        ("Chapter Three", ["Birds fly high."]),
    ])
    return path


@pytest.fixture
def zh_epub(tmp_path: Path) -> Path:
    path = tmp_path / "chinese.epub"
    make_minimal_epub(path, "測試書", [
        ("第一章", ["貓坐在墊子上。"]),
        ("第二章", ["狗跑得快。"]),
        ("第三章", ["鳥高飛。"]),
    ])
    return path


def test_read_epub_chapters(en_epub: Path):
    title, chapters = _read_epub_chapters(en_epub)
    assert title == "Test Book"
    assert len(chapters) == 3
    assert chapters[0]["title"] == "Chapter One"
    assert chapters[0]["href"] == "chapter0.xhtml"


def test_auto_chapter_map(en_epub: Path, zh_epub: Path):
    _, en_chapters = _read_epub_chapters(en_epub)
    _, zh_chapters = _read_epub_chapters(zh_epub)
    chapter_map = _auto_chapter_map(en_chapters, zh_chapters)
    assert len(chapter_map) == 3
    assert chapter_map[0][0] == "ch001"
    assert chapter_map[0][1] == "chapter0.xhtml"
    assert chapter_map[0][2] == "chapter0.xhtml"


def test_detect_target_lang_traditional(zh_epub: Path):
    lang = _detect_target_lang(zh_epub)
    # The test fixture uses Traditional Chinese characters.
    assert lang in ("zh-Hant", "zh-Hans")


def test_pair_documents(en_epub: Path, zh_epub: Path, tmp_path: Path, monkeypatch):
    """Test the full pair -> align -> get_section flow using a temp workspace."""
    from deeptutor.immersive_reading.bilingual import service as svc_module

    # Create a fake path service that returns tmp paths.
    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            d = tmp_path / "bilingual"
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = tmp_path / "bilingual" / f"pairing_{pairing_id}"
            (root / "sections").mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            d = tmp_path / f"document_{document_id}"
            d.mkdir(parents=True, exist_ok=True)
            return d

    # Set up fake document roots with the test EPUBs.
    en_doc_root = tmp_path / "document_en001"
    en_doc_root.mkdir(parents=True)
    (en_doc_root / "original.epub").write_bytes(en_epub.read_bytes())

    zh_doc_root = tmp_path / "document_zh001"
    zh_doc_root.mkdir(parents=True)
    (zh_doc_root / "original.epub").write_bytes(zh_epub.read_bytes())

    monkeypatch.setattr(svc_module, "get_path_service", lambda: FakePathService())

    pairing_service = svc_module.BilingualPairingService()

    # Pair
    result = pairing_service.pair_documents("en001", "zh001")
    assert result["en_title"] == "Test Book"
    assert result["chapter_count"] == 3
    assert not result["aligned"]

    # Align
    result = pairing_service.align(result["pairing_id"])
    assert result["aligned"]

    # Get section
    section = pairing_service.get_bilingual_section(result["pairing_id"], "ch001")
    assert section["pairs"] >= 1
    assert len(section["groups"]) >= 1

    # Update chapter map (drop one chapter)
    chapter_map = result["chapter_map"][:2]
    result = pairing_service.update_chapter_map(result["pairing_id"], chapter_map)
    assert result["chapter_count"] == 2
    assert not result["aligned"]

    # Re-align
    result = pairing_service.align(result["pairing_id"])
    assert result["aligned"]


def test_pair_documents_dedup(en_epub: Path, zh_epub: Path, tmp_path: Path, monkeypatch):
    """Pairing the same two books twice must return the existing pairing."""
    from deeptutor.immersive_reading.bilingual import service as svc_module

    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            d = tmp_path / "bilingual"
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = tmp_path / "bilingual" / f"pairing_{pairing_id}"
            (root / "sections").mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            return tmp_path / f"document_{document_id}"

    (tmp_path / "document_en003").mkdir(parents=True)
    (tmp_path / "document_en003" / "original.epub").write_bytes(en_epub.read_bytes())
    (tmp_path / "document_zh003").mkdir(parents=True)
    (tmp_path / "document_zh003" / "original.epub").write_bytes(zh_epub.read_bytes())

    monkeypatch.setattr(svc_module, "get_path_service", lambda: FakePathService())

    svc = svc_module.BilingualPairingService()
    first = svc.pair_documents("en003", "zh003")
    second = svc.pair_documents("en003", "zh003")

    # Second call returns the same pairing — no duplicate is created.
    assert first["pairing_id"] == second["pairing_id"]
    assert len(svc.list_pairings()) == 1


def test_export_epub(en_epub: Path, zh_epub: Path, tmp_path: Path, monkeypatch):
    """Test EPUB export from a pairing."""
    from deeptutor.immersive_reading.bilingual import service as svc_module

    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            d = tmp_path / "bilingual"
            d.mkdir(parents=True, exist_ok=True)
            return d

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = tmp_path / "bilingual" / f"pairing_{pairing_id}"
            (root / "sections").mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            return tmp_path / f"document_{document_id}"

    en_doc_root = tmp_path / "document_en002"
    en_doc_root.mkdir(parents=True)
    (en_doc_root / "original.epub").write_bytes(en_epub.read_bytes())

    zh_doc_root = tmp_path / "document_zh002"
    zh_doc_root.mkdir(parents=True)
    (zh_doc_root / "original.epub").write_bytes(zh_epub.read_bytes())

    monkeypatch.setattr(svc_module, "get_path_service", lambda: FakePathService())

    svc = svc_module.BilingualPairingService()
    result = svc.pair_documents("en002", "zh002")
    svc.align(result["pairing_id"])

    epub_path = svc.export_epub(result["pairing_id"])
    assert epub_path.exists()
    assert epub_path.suffix == ".epub"
