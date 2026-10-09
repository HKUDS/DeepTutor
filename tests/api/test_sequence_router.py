"""The sequence routes return a problem without its answer order."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import sequence
from deeptutor.learning.sequence.schema import SequenceError


def _client():
    app = FastAPI()
    app.include_router(sequence.router, prefix="/api/solution-sequence")
    return TestClient(app)


def test_create_returns_the_service_payload(monkeypatch):
    async def fake_generate(knowledge_base, topic, _store):
        assert knowledge_base == "calculus"
        assert topic == "chain rule"
        return {
            "problem_id": "problem-000000000001",
            "question": "Differentiate.",
            "formulas": [],
            "steps": [],
            "placed_ids": [],
            "solved": False,
            "explanation": None,
            "progress": {"solved": 0, "goal": 5},
            "sources": [],
        }

    monkeypatch.setattr(sequence, "generate_problem", fake_generate)
    response = _client().post(
        "/api/solution-sequence/problems",
        json={"knowledge_base": "calculus", "topic": "chain rule"},
    )
    assert response.status_code == 200
    assert response.json()["explanation"] is None
    assert "correct_ids" not in response.json()


def test_create_maps_a_grounding_failure(monkeypatch):
    async def fake_generate(_knowledge_base, _topic, _store):
        raise SequenceError(
            422, "That knowledge base did not return enough material for this topic."
        )

    monkeypatch.setattr(sequence, "generate_problem", fake_generate)
    response = _client().post(
        "/api/solution-sequence/problems",
        json={"knowledge_base": "calculus", "topic": "chain rule"},
    )
    assert response.status_code == 422
    assert "enough material" in response.json()["detail"]


def test_place_rejects_without_revealing_the_expected_step(monkeypatch):
    def fake_place(_store, problem_id, step_id, index):
        assert problem_id == "problem-000000000001"
        assert step_id == "s_wrong"
        assert index == 0
        return {
            "accepted": False,
            "problem": {"problem_id": problem_id, "placed_ids": [], "solved": False},
        }

    monkeypatch.setattr(sequence, "place_step", fake_place)
    response = _client().post(
        "/api/solution-sequence/problems/problem-000000000001/place",
        json={"step_id": "s_wrong", "index": 0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert "correct" not in body


def test_missing_outline_uses_the_not_read_message(monkeypatch):
    def fake_read(_store, knowledge_base):
        assert knowledge_base == "calculus"
        raise SequenceError(404, "This knowledge base has not been read yet.")

    monkeypatch.setattr(sequence, "read_outline", fake_read)
    response = _client().get(
        "/api/solution-sequence/outlines",
        params={"knowledge_base": "calculus"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "This knowledge base has not been read yet."


def test_create_outline_returns_the_service_payload(monkeypatch):
    async def fake_build(knowledge_base, _store):
        assert knowledge_base == "calculus"
        return {
            "knowledge_base": "calculus",
            "source": "files",
            "modules": [
                {
                    "id": "m_abc",
                    "category": "",
                    "name": "Chain rule",
                    "topic": "chain rule",
                    "solved": 0,
                    "goal": 5,
                }
            ],
        }

    monkeypatch.setattr(sequence, "build_outline", fake_build)
    response = _client().post(
        "/api/solution-sequence/outlines",
        json={"knowledge_base": "calculus"},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "files"
    # The outline leaves an empty category empty; the client names it, so the
    # label reaches the learner in their own language.
    assert response.json()["modules"][0]["category"] == ""
    assert "correct_ids" not in response.json()


def test_check_returns_marks_without_the_answer_key(monkeypatch):
    def fake_check(_store, problem_id, step_ids):
        assert problem_id == "problem-000000000001"
        assert step_ids == ["s_wrong"]
        return {
            "solved": False,
            "marks": ["incorrect"],
            "problem": {
                "problem_id": problem_id,
                "placed_ids": [],
                "solved": False,
                "explanation": None,
            },
        }

    monkeypatch.setattr(sequence, "check_answer", fake_check)
    response = _client().post(
        "/api/solution-sequence/problems/problem-000000000001/check",
        json={"step_ids": ["s_wrong"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["marks"] == ["incorrect"]
    assert "correct_ids" not in body


def test_hint_body_is_optional(monkeypatch):
    seen = {}

    async def fake_hint(_store, problem_id, step_ids=None):
        seen["problem_id"] = problem_id
        seen["step_ids"] = step_ids
        return {"hint": "Look at the outer function."}

    monkeypatch.setattr(sequence, "hint", fake_hint)
    client = _client()
    empty = client.post("/api/solution-sequence/problems/problem-000000000001/hint")
    assert empty.status_code == 200
    assert seen["step_ids"] is None
    sent = client.post(
        "/api/solution-sequence/problems/problem-000000000001/hint",
        json={"step_ids": ["s_one"]},
    )
    assert sent.status_code == 200
    assert seen["step_ids"] == ["s_one"]
