"""Vocabulary storage and API contract tests."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from deeptutor.immersive_reading.models import DictionaryResult, VocabEntry
from deeptutor.immersive_reading.ecdict import ECDictionary
from deeptutor.immersive_reading.service import ImmersiveReadingService
from deeptutor.immersive_reading.vocabulary import (
    chapter_difficulty,
    cloze_sentence,
    ensure_cards,
    grade_review,
    review_queue,
    vocabulary_apkg,
    vocabulary_csv,
)
from deeptutor.services.path_service import PathService
from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


def _vocab_entry(word: str, **overrides) -> VocabEntry:
    values = {
        "id": f"id-{word.casefold()}",
        "word": word,
        "phonetic": "/test/",
        "chinese": "测试释义",
        "context_en": f"The {word} appeared in a useful sentence.",
        "context_zh": "这个有用的句子中出现了测试词。",
        "created_at": 100,
    }
    values.update(overrides)
    return VocabEntry(**values)


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


def test_vocabulary_review_and_export_router_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import deeptutor.api.routers.immersive_reading as router_module

    entry = _vocab_entry(
        "bright",
        cards=[
            {
                "id": "id-bright:cloze",
                "card_type": "cloze",
                "front": "The ____ appeared.",
                "back": "bright",
                "context_en": "The bright appeared.",
                "context_zh": "这个明亮的词出现了。",
                "choices": [],
                "answer": "bright",
                "created_at": 1,
                "updated_at": 1,
            }
        ],
    )
    export_path = tmp_path / "vocabulary.csv"
    export_path.write_text("Word\nbright\n", encoding="utf-8")

    class FakeService:
        def review_vocabulary(self, limit: int):
            assert limit == 10
            return [entry]

        def grade_vocabulary_review(self, entry_id: str, *, correct: bool):
            assert (entry_id, correct) == (entry.id, True)
            return entry

        def export_vocabulary_csv(self):
            return export_path

    app = FastAPI()
    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: FakeService())
    app.include_router(router_module.router, prefix="/api/v1/immersive-reading")
    client = TestClient(app)

    review = client.get("/api/v1/immersive-reading/vocabulary/review?limit=10")
    graded = client.post(
        "/api/v1/immersive-reading/vocabulary/review/grade",
        json={"entry_id": entry.id, "correct": True},
    )
    exported = client.get("/api/v1/immersive-reading/vocabulary/export/csv")

    assert review.status_code == 200, review.text
    assert review.json()["entries"][0]["cards"][0]["card_type"] == "cloze"
    assert graded.status_code == 200, graded.text
    assert graded.json()["entry"]["id"] == entry.id
    assert exported.status_code == 200, exported.text
    assert exported.text == "Word\nbright\n"
    assert exported.headers["content-type"].startswith("text/csv")


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
    chapter = pairing["chapter_map"][0]
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
        chapter_index=0,
        group_index=0,
    )

    assert entry.pairing_id == pairing["pairing_id"]
    assert entry.chapter_id == chapter["id"]
    assert entry.context_en == "The bright harbour slept."
    assert entry.context_zh == "明亮的港口睡着了。"
    assert [card.card_type for card in entry.cards] == ["cloze", "choice"]
    assert entry.cards[0].front == "The ____ harbour slept."
    assert entry.cards[0].context_zh == "明亮的港口睡着了。"
    assert service.list_vocabulary(pairing_id=pairing["pairing_id"]) == [entry]


def test_generated_cards_use_bilingual_context_and_stable_ids() -> None:
    bright = _vocab_entry("bright")
    harbour = _vocab_entry("harbour")

    generated = ensure_cards(bright, [bright, harbour])

    assert cloze_sentence("The Bright harbour slept.", "bright") == "The ____ harbour slept."
    assert [card.id for card in generated.cards] == ["id-bright:cloze", "id-bright:choice"]
    assert generated.cards[0].front == "The ____ appeared in a useful sentence."
    assert generated.cards[0].context_zh == "这个有用的句子中出现了测试词。"
    assert generated.cards[1].choices == ["bright", "harbour"]


def test_review_queue_prefers_due_age_then_frequent_words() -> None:
    due_old = _vocab_entry(
        "old", review={"due_at": 100, "interval_index": 2, "review_count": 3}
    )
    frequent = _vocab_entry(
        "frequent",
        occurrence_count=7,
        review={"due_at": 50, "interval_index": 1, "review_count": 4},
    )
    less_frequent = _vocab_entry(
        "common",
        occurrence_count=2,
        review={"due_at": 50, "interval_index": 1, "review_count": 2},
    )
    future = _vocab_entry("future", review={"due_at": 2_000})

    queued = review_queue([due_old, future, less_frequent, frequent], limit=2, now=1_000)

    assert [entry.word for entry in queued] == ["frequent", "common"]


def test_review_grading_uses_lightweight_spaced_repetition() -> None:
    now = 1_000_000.0
    entry = _vocab_entry("bright", review={"due_at": 0, "interval_index": 0})

    entries, correct_once = grade_review([entry], entry.id, correct=True, now=now)
    assert correct_once.review.interval_index == 1
    assert correct_once.review.due_at == now + 86_400

    entries, correct_twice = grade_review(
        entries, entry.id, correct=True, now=now + 10
    )
    assert correct_twice.review.interval_index == 2
    assert correct_twice.review.due_at == now + 10 + 3 * 86_400

    _, wrong = grade_review(entries, entry.id, correct=False, now=now + 20)
    assert wrong.review.interval_index == 1
    assert wrong.review.due_at == now + 20 + 86_400
    assert wrong.review.last_result == "wrong"


def test_csv_export_contains_bilingual_study_fields() -> None:
    entry = ensure_cards(
        _vocab_entry(
            "bright",
            definitions=[
                {
                    "part_of_speech": "adj.",
                    "definition": "full of light",
                    "chinese": "明亮的",
                    "example": "",
                    "synonyms": [],
                    "context_match": True,
                }
            ],
        ),
        [],
    )

    text = vocabulary_csv([entry]).decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))

    assert rows[0]["Word"] == "bright"
    assert rows[0]["Phonetic"] == "/test/"
    assert rows[0]["Original Sentence"] == entry.context_en
    assert rows[0]["Chinese Translation"] == entry.context_zh
    assert rows[0]["English Definition"] == "adj. full of light"
    assert rows[0]["Chinese Definition"] == "测试释义"


def test_apkg_export_contains_standard_collection_and_both_cards() -> None:
    entry = ensure_cards(_vocab_entry("bright"), [])

    package = vocabulary_apkg([entry])

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert archive.namelist() == ["collection.anki2", "media"]
        assert json.loads(archive.read("media")) == {}
        database = archive.read("collection.anki2")
    again = vocabulary_apkg([entry])
    with zipfile.ZipFile(io.BytesIO(again)) as archive:
        database_again = archive.read("collection.anki2")

    connection = sqlite3.connect(":memory:")
    connection.deserialize(database)
    col = connection.execute("SELECT models, decks FROM col").fetchone()
    note = connection.execute(
        "SELECT guid, mid, flds FROM notes"
    ).fetchone()
    cards = connection.execute("SELECT did, usn, ord FROM cards ORDER BY ord").fetchall()
    connection.deserialize(database_again)
    stable_note = connection.execute("SELECT guid FROM notes").fetchone()

    models = json.loads(col[0])
    model = next(iter(models.values()))
    target_deck = next(
        deck for deck in json.loads(col[1]).values() if deck["name"] == "DeepTutor Vocabulary"
    )
    assert model["name"] == "DeepTutor Vocabulary"
    assert [template["name"] for template in model["tmpls"]] == [
        "Context Cloze",
        "Context Choice",
    ]
    assert note[2].startswith("bright\x1f/test/")
    assert "这个有用的句子中出现了测试词。" in note[2]
    assert cards[0][0] == target_deck["id"]
    assert [(card[1], card[2]) for card in cards] == [(0, 0), (0, 1)]
    assert stable_note[0] == note[0]
    connection.close()


def test_chapter_difficulty_uses_frequency_and_oxford_fields(tmp_path: Path) -> None:
    source = tmp_path / "frequency.csv"
    source.write_text(
        "\n".join(
            [
                "word,phonetic,definition,translation,pos,exchange,frq,oxford",
                'harbour,"hɑrbər","""n. a sheltered port""","""n. 港口""",n,,450,1',
                'brilliant,"brɪljənt","""adj. very bright""","""adj. 明亮的""",adj,,4200,0',
                'ephemeral,"ɪfemərəl","""adj. lasting a short time""","""adj. 短暂的""",adj,,21000,0',
            ]
        ),
        encoding="utf-8",
    )
    database = tmp_path / "frequency.db"
    ECDictionary.import_csv(source, database)
    dictionary = ECDictionary(database)

    result = chapter_difficulty(
        "The brilliant ephemeral harbour kept its zebra secret.",
        dictionary,
        saved_words=("Harbour",),
    )

    by_word = {word.word: word for word in result.words}
    assert result.available is True
    assert result.distribution == {
        "core": 1,
        "common": 1,
        "low": 1,
        "unknown": 3,
    }
    assert by_word["harbour"].band == "core"
    assert by_word["harbour"].frequency_rank == 450
    assert by_word["ephemeral"].band == "low"
    assert by_word["zebra"].band == "unknown"
    dictionary.close()


def test_old_ecdict_schema_reports_unavailable_but_still_looks_up(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE entries (
          word TEXT PRIMARY KEY, sw TEXT NOT NULL, phonetic TEXT NOT NULL,
          definition TEXT NOT NULL, translation TEXT NOT NULL, pos TEXT NOT NULL,
          exchange TEXT NOT NULL
        );
        INSERT INTO entries VALUES ('harbour', 'harbour', '/hɑrbər/', 'n. port', 'n. 港口', 'n', '');
        """
    )
    connection.commit()
    connection.close()
    dictionary = ECDictionary(database)

    entry = dictionary.lookup("harbour")
    result = chapter_difficulty("The harbour slept.", dictionary)

    assert entry is not None and entry.translation == "n. 港口"
    assert entry.frq == 0 and entry.oxford == 0
    assert result.available is False
    assert "frequency fields are unavailable" in result.reason
    assert result.words[0].band == "unknown"
    dictionary.close()
