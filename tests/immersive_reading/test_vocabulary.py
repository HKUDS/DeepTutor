"""Vocabulary storage and API contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.immersive_reading.models import DictionaryResult, VocabEntry
from deeptutor.immersive_reading.service import ImmersiveReadingService
from deeptutor.services.path_service import PathService
from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


def test_vocabulary_router_accepts_bilingual_source_and_filter(monkeypatch: pytest.MonkeyPatch):
    import deeptutor.api.routers.immersive_reading as router_module

    saved: list[VocabEntry] = []

    class FakeService:
        async def add_word(self, word, **kwargs):
            entry = VocabEntry(id="vocab001", word=word, pairing_id=kwargs["pairing_id"], **{
                key: value
                for key, value in kwargs.items()
                if key in {"document_id", "document_title", "section_title", "chapter_id"}
            })
            saved.append(entry)
            return entry

        def list_vocabulary(self, document_id=None, pairing_id=None):
            assert pairing_id == "pair001"
            return saved

    app = FastAPI()
    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: FakeService())
    app.include_router(router_module.router, prefix="/api/v1/immersive-reading")
    client = TestClient(app)

    response = client.post(
        "/api/v1/immersive-reading/vocabulary",
        json={
            "word": "bright",
            "context": "The bright harbour slept.",
            "document_id": "en001",
            "document_title": "English Book",
            "section_title": "Chapter 2",
            "pairing_id": "pair001",
            "chapter_id": "ch002",
            "chapter_index": 2,
            "group_index": 7,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["entry"]["pairing_id"] == "pair001"

    listing = client.get("/api/v1/immersive-reading/vocabulary?pairing_id=pair001")
    assert listing.status_code == 200
    assert listing.json()["entries"][0]["chapter_id"] == "ch002"


@pytest.mark.asyncio
async def test_add_word_merges_duplicates_and_updates_bilingual_source(
    reading_service: ImmersiveReadingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def first_lookup(word: str, context: str):
        return DictionaryResult(
            word=word,
            phonetic="/brɪt/",
            definitions=[
                {
                    "part_of_speech": "adj.",
                    "definition": "having light",
                    "chinese": "明亮的",
                    "example": "",
                    "synonyms": [],
                    "context_match": True,
                }
            ],
            chinese="明亮的",
            context_note="The harbour is bright.",
        )

    monkeypatch.setattr(reading_service, "lookup_word", first_lookup)
    first = await reading_service.add_word(
        "Bright",
        context="The bright harbour slept.",
        document_id="en001",
        document_title="English Book",
        section_title="Chapter 1",
        pairing_id="pair001",
        chapter_id="ch001",
        chapter_index=2,
        group_index=4,
    )
    assert first.occurrence_count == 1
    assert first.pairing_id == "pair001"
    assert first.chapter_index == 2
    assert first.group_index == 4

    async def second_lookup(word: str, context: str):
        return DictionaryResult(
            word=word,
            phonetic="/braɪt/",
            definitions=[],
            chinese="聪明的",
            context_note="The bright child asked a question.",
        )

    monkeypatch.setattr(reading_service, "lookup_word", second_lookup)
    second = await reading_service.add_word(
        "bright",
        context="The bright child asked a question.",
        document_id="en001",
        document_title="English Book",
        section_title="Chapter 3",
        pairing_id="pair001",
        chapter_id="ch003",
        chapter_index=5,
        group_index=7,
    )

    assert second.id == first.id
    assert second.occurrence_count == 2
    assert second.phonetic == "/braɪt/"
    assert second.definitions == first.definitions
    assert second.chapter_id == "ch003"
    assert reading_service.list_vocabulary(pairing_id="pair001") == [second]
    assert reading_service.list_vocabulary(pairing_id="missing") == []


def test_list_vocabulary_validates_legacy_entries(
    reading_service: ImmersiveReadingService,
) -> None:
    vocabulary_path = reading_service._vocabulary_path()
    vocabulary_path.parent.mkdir(parents=True, exist_ok=True)
    vocabulary_path.write_text(
        '[{"id":"legacy","word":"harbour","created_at":123,"mn4_exported":false}]',
        encoding="utf-8",
    )

    entries = reading_service.list_vocabulary()

    assert len(entries) == 1
    assert entries[0].pairing_id == ""
    assert entries[0].chapter_index == 0
    assert entries[0].occurrence_count == 1


@pytest.mark.asyncio
async def test_imported_bilingual_pairing_feeds_vocabulary_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.immersive_reading.bilingual.service as bilingual_module
    import deeptutor.immersive_reading.service as reading_module

    paths = PathService(workspace_root=tmp_path / "runtime-data")
    monkeypatch.setattr(reading_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(bilingual_module, "get_path_service", lambda: paths)
    ImmersiveReadingService._dict_cache.clear()
    service = ImmersiveReadingService()

    en_epub = tmp_path / "english.epub"
    zh_epub = tmp_path / "chinese.epub"
    make_minimal_epub(en_epub, "Test Book", [
        ("Chapter One", ["The bright harbour slept."]),
        ("Chapter Two", ["The dog ran fast."]),
    ])
    make_minimal_epub(zh_epub, "测试书", [
        ("第一章", ["明亮的港口睡着了。"]),
        ("第二章", ["狗跑得快。"]),
    ])
    en_document = service.import_document("english.epub", en_epub.read_bytes())
    zh_document = service.import_document("chinese.epub", zh_epub.read_bytes())

    pairing_service = bilingual_module.BilingualPairingService()
    pairing = pairing_service.pair_documents(en_document["id"], zh_document["id"])
    pairing = pairing_service.align(pairing["pairing_id"])
    chapter = pairing["chapter_map"][1]
    section = pairing_service.get_bilingual_section(pairing["pairing_id"], chapter["id"])
    assert section["groups"]

    async def lookup(word: str, context: str):
        return DictionaryResult(word=word, chinese="明亮的")

    monkeypatch.setattr(service, "lookup_word", lookup)
    entry = await service.add_word(
        "bright",
        context=section["groups"][0]["en"][0],
        document_id=en_document["id"],
        document_title=en_document["title"],
        section_title=chapter["en_title"],
        pairing_id=pairing["pairing_id"],
        chapter_id=chapter["id"],
        chapter_index=1,
        group_index=0,
    )

    assert entry.pairing_id == pairing["pairing_id"]
    assert entry.chapter_id == chapter["id"]
    assert service.list_vocabulary(pairing_id=pairing["pairing_id"]) == [entry]
