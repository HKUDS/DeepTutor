"""Tests for bilingual reading positions, bookmarks, and navigation state."""

from pathlib import Path

import pytest

from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


@pytest.fixture
def setup_pairing(tmp_path: Path, monkeypatch):
    from deeptutor.immersive_reading.bilingual import service as service_module

    en_epub = tmp_path / "en.epub"
    zh_epub = tmp_path / "zh.epub"
    make_minimal_epub(
        en_epub,
        "Test Book",
        [
            ("Chapter 1", ["The cat sat on the mat.", "The dog ran fast."]),
            ("Chapter 2", ["The bird flew away.", "The fish swam below."]),
        ],
    )
    make_minimal_epub(
        zh_epub,
        "测试书",
        [
            ("第一章", ["猫坐在垫子上。", "狗跑得快。"]),
            ("第二章", ["鸟飞走了。", "鱼游到下面。"]),
        ],
    )

    for document_id in ("en", "zh"):
        document_dir = tmp_path / f"document_{document_id}"
        document_dir.mkdir()
        (document_dir / "original.epub").write_bytes(
            (en_epub if document_id == "en" else zh_epub).read_bytes()
        )

    class FakePathService:
        def get_immersive_reading_bilingual_dir(self):
            directory = tmp_path / "bilingual"
            directory.mkdir(parents=True, exist_ok=True)
            return directory

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = self.get_immersive_reading_pairing_root(pairing_id)
            root.mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            return tmp_path / f"document_{document_id}"

    monkeypatch.setattr(service_module, "get_path_service", lambda: FakePathService())
    service = service_module.BilingualPairingService()
    pairing = service.pair_documents("en", "zh")
    service.align(pairing["pairing_id"])
    return service, pairing["pairing_id"]


def test_reading_position_round_trip_and_clamping(setup_pairing):
    service, pairing_id = setup_pairing

    assert service.get_pairing(pairing_id)["last_read_at"] == 0

    position = service.update_reading_position(
        pairing_id,
        {
            "chapter_index": 99,
            "group_index": 99,
            "epub_cfi": "epubcfi(/6/4!/4/10/2)",
            "section_href": "chapter1.xhtml",
            "scroll_percent": 137,
            "text_fingerprint": "the cat sat on the mat.",
        },
    )

    assert position["chapter_index"] == 1
    assert position["chapter_id"] == "ch002"
    assert position["group_index"] <= 1
    assert position["scroll_percent"] == 100
    assert position["epub_cfi"] == "epubcfi(/6/4!/4/10/2)"
    assert service.load_reading_position(pairing_id) == position
    assert service.get_pairing(pairing_id)["last_read_at"] == position["updated_at"]


def test_bookmark_crud_and_default_content(setup_pairing):
    service, pairing_id = setup_pairing

    bookmark = service.add_bookmark(
        pairing_id,
        {"chapter_index": 0, "group_index": 0, "scroll_percent": 25},
    )
    section = service.get_bilingual_section(pairing_id, bookmark["chapter_id"])

    assert bookmark["title"].startswith(section["en_title"])
    assert bookmark["preview"]
    assert service.list_bookmarks(pairing_id) == [bookmark]

    renamed = service.rename_bookmark(pairing_id, bookmark["id"], "重要位置")
    assert renamed["title"] == "重要位置"

    service.delete_bookmark(pairing_id, bookmark["id"])
    assert service.list_bookmarks(pairing_id) == []
    with pytest.raises(ValueError, match="Bookmark not found"):
        service.delete_bookmark(pairing_id, bookmark["id"])


def test_navigation_records_distinct_positions_and_traverses_history(setup_pairing):
    service, pairing_id = setup_pairing

    service.record_navigation(
        pairing_id, {"chapter_index": 0, "group_index": 0, "scroll_percent": 0}
    )
    service.record_navigation(
        pairing_id, {"chapter_index": 1, "group_index": 1, "scroll_percent": 50}
    )
    duplicate = service.record_navigation(
        pairing_id, {"chapter_index": 1, "group_index": 1, "scroll_percent": 50.04}
    )
    assert duplicate["can_back"]
    assert not duplicate["can_forward"]
    assert len(duplicate["back_stack"]) == 1

    position, state = service.navigate_back(pairing_id)
    assert position["chapter_id"] == "ch001"
    assert state["can_forward"]
    assert state["current"] == position

    position, state = service.navigate_forward(pairing_id)
    assert position["chapter_id"] == "ch002"
    assert not state["can_forward"]
    assert state["current"] == position


def test_navigation_without_destination_conflicts(setup_pairing):
    service, pairing_id = setup_pairing

    with pytest.raises(ValueError, match="No back navigation destination"):
        service.navigate_back(pairing_id)
    with pytest.raises(ValueError, match="No forward navigation destination"):
        service.navigate_forward(pairing_id)


def test_missing_pairing_rejects_position_operations(setup_pairing):
    service, _ = setup_pairing

    with pytest.raises(ValueError, match="Bilingual pairing not found"):
        service.update_reading_position(
            "missing", {"chapter_index": 0, "group_index": 0, "scroll_percent": 0}
        )
