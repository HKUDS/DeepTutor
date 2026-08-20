"""Dashboard suggestion endpoints.

The point of these tests is route *order*: ``/{entry_id}`` at the bottom of the
dashboard router matches any single segment, so a literal path declared after
it would silently become a lookup for an activity entry named "suggestions".
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import dashboard


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/v1/dashboard")
    return TestClient(app)


def test_suggestions_is_not_swallowed_by_the_entry_route(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deeptutor.services.suggestions as service

    async def _get() -> dict[str, Any]:
        # The language is resolved server-side from the learner's model-output
        # setting; the endpoint takes no parameter for it.
        return {
            "suggestions": [{"label": "复习链式法则", "prompt": "再讲一遍链式法则"}],
            "language": "zh",
            "generated_at": 1.0,
            "fingerprint": "abc",
            "stale": False,
        }

    monkeypatch.setattr(service, "get_suggestions", _get)

    response = client.get("/api/v1/dashboard/suggestions")

    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "zh"
    assert body["suggestions"][0]["label"] == "复习链式法则"


def test_refresh_returns_a_fresh_set(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.suggestions as service
    from deeptutor.services.suggestions import Suggestion, SuggestionSet

    async def _refresh() -> SuggestionSet:
        return SuggestionSet(
            suggestions=(Suggestion(label="Practise eigenvalues", prompt="Give me five"),),
            language="en",
            generated_at=2.0,
            fingerprint="def",
        )

    monkeypatch.setattr(service, "refresh_suggestions", _refresh)

    response = client.post("/api/v1/dashboard/suggestions/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is False
    assert body["suggestions"][0]["prompt"] == "Give me five"


def test_an_actual_entry_id_still_reaches_the_entry_route(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Store:
        async def get_session_with_messages(self, entry_id: str):
            return {"session_id": entry_id, "title": "Chain rule", "capability": "chat"}

    monkeypatch.setattr(dashboard, "get_session_store", lambda: _Store())

    response = client.get("/api/v1/dashboard/sess-123")

    assert response.status_code == 200
    assert response.json()["id"] == "sess-123"
