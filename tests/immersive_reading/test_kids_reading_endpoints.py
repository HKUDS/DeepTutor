"""Security and transport tests for child-facing reading documents."""

from pathlib import Path
import re
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import deeptutor.api.routers.kids as kids_router_module
from deeptutor.immersive_reading.models import (
    KidsBookAssignment,
    KidsQuizQuestion,
    KidsQuizResult,
)
from deeptutor.immersive_reading.service import _write_json, get_kids_manager


class FakeImmersiveReadingService:
    def __init__(self, epub_path: Path) -> None:
        self.epub_path = epub_path

    def original_path(self, document_id: str) -> Path:
        assert document_id == "readingdoc001"
        return self.epub_path


class FakeQuizReadingService:
    async def generate_kids_quiz(
        self,
        document_id: str,
        section_id: str,
        *,
        force_refresh: bool = False,
        age_band: str = "6-8",
        language: str = "en",
    ):
        assert document_id == "readingdoc001"
        assert section_id == "section-1"
        return KidsQuizResult(
            document_id=document_id,
            section_id=section_id,
            questions=[
                KidsQuizQuestion(
                    id="q1",
                    kind="comprehension",
                    question="What does the cat do?",
                    choices=["It sleeps.", "It drives."],
                    answer_index=0,
                    explanation="Look at the picture and words again.",
                ),
                KidsQuizQuestion(
                    id="q2",
                    kind="comprehension",
                    question="What does the plum look like?",
                    choices=["Little.", "Huge."],
                    answer_index=0,
                    explanation="Look closely at the size word.",
                ),
                KidsQuizQuestion(
                    id="q3",
                    kind="comprehension",
                    question="Who says it is little?",
                    choices=["Mac.", "A car."],
                    answer_index=0,
                    explanation="Find the name next to the words.",
                ),
            ],
            content_hash="test-hash",
            model="test-model",
            prompt_version="test-v1",
        )


class FailingQuizReadingService:
    async def generate_kids_quiz(
        self,
        document_id: str,
        section_id: str,
        *,
        force_refresh: bool = False,
        age_band: str = "6-8",
        language: str = "en",
    ):
        raise RuntimeError("placeholder model output")

    def _save_kids_quiz_cache(self, document_id: str, section_id: str, result) -> None:
        return None

    def get_section(self, document_id: str, section_id: str):
        assert document_id == "readingdoc001"
        assert section_id == "section-1"
        return {"content": "量子世界和我们每天看见的世界不一样。科学家用量子力学解释很小的粒子。"}


class FakeWordHintReadingService:
    def load_document(self, document_id: str):
        assert document_id == "readingdoc001"
        return SimpleNamespace(
            sections=[
                SimpleNamespace(
                    id="section-1",
                    title="Book 1 - Plums",
                    index=0,
                    checkpoint_kind="chapter",
                )
            ]
        )

    def get_section(self, document_id: str, section_id: str):
        assert document_id == "readingdoc001"
        assert section_id == "section-1"
        return {"content": "The little plum is on the mat."}


def test_kids_epub_requires_device_session(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )
    epub_path = tmp_path / "original.epub"
    epub_path.write_bytes(b"PK-child-epub")
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeImmersiveReadingService(epub_path),
    )

    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    endpoint = "/api/v1/kids/books/readingdoc001/epub"

    unauthenticated = client.get(endpoint)
    assert unauthenticated.status_code == 401

    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    assert selected.status_code == 200
    authorized = client.get(
        endpoint,
        headers={"Authorization": f"Bearer {selected.json()['token']}"},
    )
    assert authorized.status_code == 200
    assert authorized.content == b"PK-child-epub"
    assert authorized.headers["content-type"] == "application/epub+zip"


def test_kids_epub_quiz_stars_are_idempotent_per_section(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )

    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeQuizReadingService(),
    )

    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    headers = {"Authorization": f"Bearer {selected.json()['token']}"}
    endpoint = "/api/v1/kids/books/readingdoc001/quiz/submit"
    payload = {"section_id": "section-1", "answers": [0, 0, 0]}

    first = client.post(endpoint, json=payload, headers=headers)
    second = client.post(endpoint, json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["new_stars_awarded"] == 3
    assert first.json()["total_stars"] == 3
    assert second.json()["new_stars_awarded"] == 0
    assert second.json()["total_stars"] == 3
    assert "answer_index" not in first.text


def test_kids_epub_quiz_partial_score_does_not_award_stars_or_complete(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeQuizReadingService(),
    )

    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    headers = {"Authorization": f"Bearer {selected.json()['token']}"}

    response = client.post(
        "/api/v1/kids/books/readingdoc001/quiz/submit",
        json={"section_id": "section-1", "answers": [0, 1, 0]},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] == 2
    assert payload["total"] == 3
    assert payload["stars"] == 0
    assert payload["new_stars_awarded"] == 0
    assert payload["total_stars"] == 0
    assert payload["completed_section_ids"] == []


def test_kids_epub_quiz_falls_back_to_story_comprehension(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FailingQuizReadingService(),
    )

    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    headers = {"Authorization": f"Bearer {selected.json()['token']}"}
    response = client.post(
        "/api/v1/kids/books/readingdoc001/quiz",
        json={"section_id": "section-1"},
        headers=headers,
    )

    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 3
    assert all(question["kind"] == "comprehension" for question in questions)
    assert all(re.search(r"[\u4e00-\u9fff]", question["question"]) for question in questions)
    assert all(
        any(re.search(r"[\u4e00-\u9fff]", choice) for choice in question["choices"])
        for question in questions
    )
    assert not any(
        re.search(r'What does ".+" mean\?', question["question"]) for question in questions
    )
    assert all(question["question"] != "str" for question in questions)
    assert all(set(question["choices"]) != {"a", "b", "c", "d"} for question in questions)
    assert "answer_index" not in response.text


def test_kids_quiz_resolves_legacy_epub_chapter_href():
    from deeptutor.api.routers.kids import _resolve_kids_reading_section

    ir = SimpleNamespace(
        load_document=lambda _document_id: SimpleNamespace(
            sections=[
                SimpleNamespace(
                    id=f"section_{i:04d}",
                    title=f"Front {i}",
                    index=i,
                    checkpoint_kind="none",
                )
                for i in range(4)
            ]
            + [
                SimpleNamespace(
                    id="section_0005",
                    title="Book 1 - Plums",
                    index=4,
                    checkpoint_kind="chapter",
                )
            ]
        )
    )

    assert _resolve_kids_reading_section(ir, "doc", "chap01.html").id == "section_0005"


def test_kids_quiz_is_capped_at_three_questions():
    from deeptutor.api.routers.kids import _fill_kids_quiz_to_three

    questions = [
        KidsQuizQuestion(
            id=f"q{i}",
            kind="sight_word",
            question=f"Question {i}?",
            choices=["One", "Two"],
            answer_index=0,
            explanation="Look again.",
        )
        for i in range(4)
    ]
    result = KidsQuizResult(
        document_id="readingdoc001",
        section_id="section-1",
        questions=questions,
        content_hash="test-hash",
        model="test-model",
        prompt_version="test-v1",
    )

    filled = _fill_kids_quiz_to_three(object(), "doc", "section", "6-8", "en", result)
    assert len(filled.questions) == 3
    assert all(question.kind != "sight_word" for question in filled.questions)


def _word_hint_client(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeWordHintReadingService(),
    )
    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    selected = client.post("/api/v1/kids/select-profile", json={"profile_id": profile.id})
    return client, {"Authorization": f"Bearer {selected.json()['token']}"}


def test_kids_word_hint_progressive_contract(tmp_path, monkeypatch):
    client, headers = _word_hint_client(tmp_path, monkeypatch)
    endpoint = "/api/v1/kids/books/readingdoc001/word-hint"

    initial = client.post(
        endpoint,
        json={"word": "plum", "section_id": "section-1", "context": "The little plum."},
        headers=headers,
    )
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload["english_hint"]
    assert "chinese" not in initial_payload
    assert "choices" not in initial_payload
    assert "answer" not in initial_payload

    choices = client.post(
        f"{endpoint}/choices",
        json={"hint_id": initial_payload["hint_id"]},
        headers=headers,
    )
    assert choices.status_code == 200
    choice_payload = choices.json()
    assert len(choice_payload["choices"]) == 3
    assert all(not re.search(r"[\u4e00-\u9fff]", choice) for choice in choice_payload["choices"])

    wrong_choice = "not one of the choices"
    first_wrong = client.post(
        f"{endpoint}/check",
        json={"hint_id": initial_payload["hint_id"], "choice": wrong_choice, "attempt": 1},
        headers=headers,
    )
    first_payload = first_wrong.json()
    assert first_payload["correct"] is False
    assert "chinese" not in first_payload
    assert "correct_choice" not in first_payload

    second_wrong = client.post(
        f"{endpoint}/check",
        json={"hint_id": initial_payload["hint_id"], "choice": wrong_choice, "attempt": 2},
        headers=headers,
    )
    second_payload = second_wrong.json()
    assert second_payload["correct"] is False
    assert second_payload["correct_choice"]
    assert re.search(r"[\u4e00-\u9fff]", second_payload["chinese"])


def test_kids_word_hint_rejects_unauthorized_section(tmp_path, monkeypatch):
    client, headers = _word_hint_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/kids/books/readingdoc001/word-hint",
        json={"word": "plum", "section_id": "missing-section", "context": ""},
        headers=headers,
    )
    assert response.status_code == 404


def test_kids_word_hint_uses_simple_dictionary_for_pictures(tmp_path, monkeypatch):
    client, headers = _word_hint_client(tmp_path, monkeypatch)
    endpoint = "/api/v1/kids/books/readingdoc001/word-hint"

    initial = client.post(
        endpoint,
        json={"word": "pictures", "section_id": "section-1", "context": ""},
        headers=headers,
    )
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["available"] is True
    assert "visual representation" not in payload["english_hint"]

    choices = client.post(
        f"{endpoint}/choices",
        json={"hint_id": payload["hint_id"]},
        headers=headers,
    ).json()["choices"]
    assert len(choices) == 3
    assert all(len(choice) <= 80 for choice in choices)
    assert all(not re.search(r"[\u4e00-\u9fff]", choice) for choice in choices)


def test_kids_word_hint_rejects_ecdict_only_word(tmp_path, monkeypatch):
    client, headers = _word_hint_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/kids/books/readingdoc001/word-hint",
        json={"word": "sepulchral", "section_id": "section-1", "context": ""},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"available": False, "word": "sepulchral"}
