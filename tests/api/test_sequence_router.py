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
