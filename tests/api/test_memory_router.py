from __future__ import annotations

import importlib

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
router = importlib.import_module("deeptutor.api.routers.memory").router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/memory")
    return app


def test_memory_router_returns_single_document(monkeypatch) -> None:
    class FakeMemoryService:
        def read_snapshot(self):
            return type(
                "Snapshot",
                (),
                {
                    "content": "## Preferences\n- Prefer concise answers.",
                    "exists": True,
                    "updated_at": "2026-03-13T12:00:00+08:00",
                },
            )()

    monkeypatch.setattr("deeptutor.api.routers.memory.get_memory_service", lambda: FakeMemoryService())

    with TestClient(_build_app()) as client:
        response = client.get("/api/v1/memory")

    assert response.status_code == 200
    assert response.json() == {
        "content": "## Preferences\n- Prefer concise answers.",
        "exists": True,
        "updated_at": "2026-03-13T12:00:00+08:00",
    }


def test_memory_router_refreshes_from_session(monkeypatch) -> None:
    class FakeStore:
        async def get_session(self, session_id: str):
            if session_id == "missing":
                return None
            return {"session_id": session_id}

    class FakeMemoryService:
        async def refresh_from_session(self, session_id, language="en"):
            return type(
                "Result",
                (),
                {
                    "content": "## Preferences\n- Prefer concise answers.\n\n## Context\n- Working on memory.",
                    "changed": True,
                    "updated_at": "2026-03-13T12:10:00+08:00",
                },
            )()

    monkeypatch.setattr("deeptutor.api.routers.memory.get_sqlite_session_store", lambda: FakeStore())
    monkeypatch.setattr("deeptutor.api.routers.memory.get_memory_service", lambda: FakeMemoryService())

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/memory/refresh",
            json={"session_id": "unified_1", "language": "en"},
        )

    assert response.status_code == 200
    assert response.json()["changed"] is True
    assert response.json()["exists"] is True
    assert "## Context" in response.json()["content"]


def test_memory_router_updates_document(monkeypatch) -> None:
    class FakeMemoryService:
        def write_memory(self, content: str):
            return type(
                "Snapshot",
                (),
                {
                    "content": content,
                    "exists": bool(content),
                    "updated_at": "2026-03-13T12:20:00+08:00",
                },
            )()

    monkeypatch.setattr("deeptutor.api.routers.memory.get_memory_service", lambda: FakeMemoryService())

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/v1/memory",
            json={"content": "## Preferences\n- Prefer concise answers."},
        )

    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert response.json()["content"] == "## Preferences\n- Prefer concise answers."
