"""Security and transport tests for child-facing reading documents."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

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
    ):
        raise RuntimeError("placeholder model output")

    def _save_kids_quiz_cache(self, document_id: str, section_id: str, result) -> None:
        return None

    def get_section(self, document_id: str, section_id: str):
        assert document_id == "readingdoc001"
        assert section_id == "section-1"
        return {"content": "The plum is a little fruit. said Mac."}


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


def test_kids_epub_quiz_falls_back_to_real_story_words(tmp_path, monkeypatch):
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

    assert len(_fill_kids_quiz_to_three(object(), "doc", "section", "6-8", result).questions) == 3
