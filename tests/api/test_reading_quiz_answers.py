"""Tests for the Immersive Reading Focus-Check answer endpoint.

The endpoint is where browser-graded reading quizzes become durable review
records: the server grades each submission against its own stored answer key
(the browser sends only the chosen index), records ``immersive_reading``
entries into the unified Question Notebook, and retains standalone quizzes without requiring a chat.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
reading_router = importlib.import_module("deeptutor.api.routers.reading_extensions").router

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

MATERIAL_ID = "m-atlas"
LOCATOR = 4


class _StubManifest:
    title = "Test Material"


class _StubReadingStore:
    def __init__(self) -> None:
        pass

    def manifest(self, material_id: str) -> Any:
        return _StubManifest()


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
    app.include_router(reading_router, prefix="/api/reading")
    return app


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "reading-quiz.db")
    monkeypatch.setattr(
        "deeptutor.api.routers.reading_extensions.assert_learning_material",
        lambda material_id: None,
    )
    monkeypatch.setattr(
        "deeptutor.services.session.get_sqlite_session_store",
        lambda: instance,
    )
    monkeypatch.setattr(
        "deeptutor.api.routers.reading_extensions.ReadingStore",
        _StubReadingStore,
    )
    return instance


def _quiz_questions() -> list[dict]:
    return [
        {
            "id": "q_1",
            "prompt": "Which ocean?",
            "choices": ["Pacific", "Atlantic"],
            "correct_choice_index": 1,
        },
        {
            "id": "q_2",
            "prompt": "2+2?",
            "choices": ["3", "4", "5"],
            "correct_choice_index": 1,
        },
    ]


def _answers(*pairs: tuple[str, int]) -> list[dict]:
    return [{"question_id": qid, "selected_index": index} for qid, index in pairs]


def _payload(**overrides) -> dict:
    values: dict = {
        "locator": LOCATOR,
        "section_title": "Atlas preface",
        "session_id": "reading-session",
        "turn_id": "",
        "answers": _answers(("q_1", 1), ("q_2", 0)),
    }
    values.update(overrides)
    return values


def test_focus_check_entries_land_in_unified_list(
    store: SQLiteSessionStore,
) -> None:
    asyncio.run(store.create_session(title="Reading", session_id="reading-session"))
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))

    with TestClient(_build_app(store)) as client:
        resp = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(),
        )
    assert resp.status_code == 200
    verdicts = {(item["question_id"]): item for item in resp.json()["answers"]}
    assert verdicts["q_1"]["is_correct"] is True
    assert verdicts["q_1"]["result"] == "correct"
    assert verdicts["q_2"]["is_correct"] is False
    assert verdicts["q_2"]["result"] == "incorrect"

    listing = asyncio.run(
        store.list_notebook_entries(session_id="reading-session", source="immersive_reading")
    )
    assert listing["total"] == 2
    by_id = {item["question_id"]: item for item in listing["items"]}
    assert by_id["q_1"]["result"] == "correct"
    assert by_id["q_1"]["is_correct"] is True
    assert by_id["q_2"]["result"] == "incorrect"
    for item in listing["items"]:
        assert item["source"] == "immersive_reading"
        assert item["assessment_type"] == "focus_check"
        assert item["material_id"] == MATERIAL_ID
        assert item["material_title"] == "Test Material"
        assert item["section_id"] == str(LOCATOR)
        assert item["section_title"] == "Atlas preface"
        assert item["question_type"] == "choice"
    # The stored reference answer is the server's own text, never a client value.
    assert by_id["q_1"]["correct_answer"] == "Atlantic"
    assert by_id["q_1"]["user_answer"] == "Atlantic"
    assert by_id["q_2"]["user_answer"] == "3"


def test_no_session_saves_with_document_provenance(store: SQLiteSessionStore) -> None:
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    with TestClient(_build_app(store)) as client:
        resp = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(session_id="", turn_id=""),
        )
    assert resp.status_code == 200
    assert resp.json()["answers"][0]["is_correct"] is True
    listing = asyncio.run(store.list_notebook_entries())
    assert listing["total"] == 2
    assert {item["session_id"] for item in listing["items"]} == {""}
    assert {item["origin_type"] for item in listing["items"]} == {"document_analysis"}
    assert {item["origin_ref"] for item in listing["items"]} == {f"reading:{MATERIAL_ID}"}
    assert asyncio.run(store.list_sessions()) == []


def test_missing_answer_key_is_409(store: SQLiteSessionStore) -> None:
    # Nothing was persisted when the quiz was generated.
    with TestClient(_build_app(store)) as client:
        resp = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(),
        )
    assert resp.status_code == 409


def test_grading_uses_server_key_not_client_submission(store: SQLiteSessionStore) -> None:
    asyncio.run(store.create_session(title="Reading", session_id="reading-session"))
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    payload = _payload(answers=_answers(("q_1", 1)))
    with TestClient(_build_app(store)) as client:
        resp = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=payload,
        )
    assert resp.status_code == 200
    assert resp.json()["answers"] == [
        {"question_id": "q_1", "is_correct": True, "result": "correct"}
    ]


def test_repeat_submission_is_idempotent(store: SQLiteSessionStore) -> None:
    asyncio.run(store.create_session(title="Reading", session_id="reading-session"))
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    with TestClient(_build_app(store)) as client:
        first = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(),
        )
        second = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(),
        )
    assert first.status_code == second.status_code == 200
    listing = asyncio.run(store.list_notebook_entries(session_id="reading-session"))
    assert listing["total"] == 2


def test_reading_submission_id_distinguishes_retry_from_new_attempt(
    store: SQLiteSessionStore,
) -> None:
    asyncio.run(store.create_session(title="Reading", session_id="reading-session"))
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    payload = _payload(answers=_answers(("q_1", 1)), submission_id="click-1")
    with TestClient(_build_app(store)) as client:
        assert (
            client.post(
                f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers", json=payload
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers", json=payload
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
                json={**payload, "submission_id": "click-2"},
            ).status_code
            == 200
        )
    attempts = asyncio.run(store.list_assessment_attempts("reading-session", question_id="q_1"))
    assert len(attempts) == 2
    assert [item["attempt_count"] for item in attempts] == [1, 2]


def test_reading_submission_id_is_scoped_to_session(store: SQLiteSessionStore) -> None:
    for session_id in ("reader-a", "reader-b"):
        asyncio.run(store.create_session(title=session_id, session_id=session_id))
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    with TestClient(_build_app(store)) as client:
        for session_id in ("reader-a", "reader-b"):
            response = client.post(
                f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
                json=_payload(
                    session_id=session_id,
                    answers=_answers(("q_1", 1)),
                    submission_id="same-browser-id",
                ),
            )
            assert response.status_code == 200
    assert len(asyncio.run(store.list_assessment_attempts("reader-a"))) == 1
    assert len(asyncio.run(store.list_assessment_attempts("reader-b"))) == 1


@pytest.mark.parametrize("selected_index", [-1, 2])
def test_invalid_selection_does_not_save_any_part_of_batch(store, selected_index):
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    with TestClient(_build_app(store)) as client:
        response = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(session_id="", answers=_answers(("q_2", 1), ("q_1", selected_index))),
        )
    assert response.status_code == 422
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


def test_missing_explicit_session_is_an_error(store):
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    with TestClient(_build_app(store)) as client:
        response = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers", json=_payload()
        )
    assert response.status_code == 404
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


def test_invalid_answer_key_is_not_graded(store):
    questions = _quiz_questions()
    questions[0]["correct_choice_index"] = -1
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, questions))
    with TestClient(_build_app(store)) as client:
        response = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(session_id=""),
        )
    assert response.status_code == 409
    assert asyncio.run(store.list_notebook_entries())["total"] == 0


def test_regenerated_quiz_rejects_the_previous_cards(store):
    persist = importlib.import_module(
        "deeptutor.api.routers.reading_extensions"
    )._persist_reading_quiz_pending
    first = {"questions": _quiz_questions()}
    second = {"questions": _quiz_questions()}
    asyncio.run(persist(MATERIAL_ID, LOCATOR, first))
    asyncio.run(persist(MATERIAL_ID, LOCATOR, second))
    old_id = first["questions"][0]["id"]
    assert old_id != second["questions"][0]["id"]
    with TestClient(_build_app(store)) as client:
        response = client.post(
            f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
            json=_payload(session_id="", answers=_answers((old_id, 1))),
        )
    assert response.status_code == 409


def test_standalone_submission_retry_keeps_one_origin_and_one_record(store):
    asyncio.run(store.put_reading_quiz_pending(MATERIAL_ID, LOCATOR, _quiz_questions()))
    with TestClient(_build_app(store)) as client:
        for _ in range(2):
            response = client.post(
                f"/api/reading/materials/{MATERIAL_ID}/extensions/quiz/answers",
                json=_payload(session_id="", answers=_answers(("q_1", 1))),
            )
            assert response.status_code == 200
    assert asyncio.run(store.list_notebook_entries())["total"] == 1
