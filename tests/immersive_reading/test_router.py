"""HTTP contract tests for the immersive-reading router."""

from __future__ import annotations

import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def client(reading_service, monkeypatch) -> TestClient:
    import deeptutor.api.routers.immersive_reading as router_module

    router_module._search_jobs.clear()
    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: reading_service)
    monkeypatch.setattr(reading_service, "fast_index_needs_build", lambda _document_id: False)
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/immersive-reading")
    return TestClient(app)


def test_health_returns_service_identity(client: TestClient) -> None:
    response = client.get("/api/v1/immersive-reading/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "immersive-reading"}


def test_get_section_returns_source_content(client: TestClient, imported_document: dict) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    response = client.get(
        f"/api/v1/immersive-reading/documents/{document_id}/sections/{section_id}"
    )

    assert response.status_code == 200
    assert response.json()["section"]["title"] == "Chapter 1"
    assert "brass compass" in response.json()["content"]


def test_progress_endpoint_persists_reader_position(client: TestClient, imported_document: dict) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    response = client.put(
        f"/api/v1/immersive-reading/documents/{document_id}/progress",
        json={"section_id": section_id, "scroll_percent": 72.5},
    )

    assert response.status_code == 200
    assert response.json()["progress"]["current_section_id"] == section_id
    assert response.json()["progress"]["scroll_percent"] == 72.5


def test_skip_section_endpoint_records_intent(client: TestClient, imported_document: dict) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    response = client.post(
        f"/api/v1/immersive-reading/documents/{document_id}/skip-section",
        json={"section_id": section_id},
    )

    assert response.status_code == 200
    assert response.json()["progress"]["skipped_section_ids"] == [section_id]


def test_exact_search_endpoint_returns_hits(client: TestClient, imported_document: dict) -> None:
    response = client.post(
        f"/api/v1/immersive-reading/documents/{imported_document['id']}/search",
        json={"query": "brass compass", "mode": "exact"},
    )

    assert response.status_code == 200
    assert len(response.json()["hits"]) == 3
    assert response.json()["resolved_mode"] == "exact"
    assert response.json()["fallback_used"] is False


def test_search_rejects_invalid_mode(client: TestClient, imported_document: dict) -> None:
    response = client.post(
        f"/api/v1/immersive-reading/documents/{imported_document['id']}/search",
        json={"query": "compass", "mode": "unsupported"},
    )

    assert response.status_code == 422


def test_missing_document_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/immersive-reading/documents/missing")

    assert response.status_code == 404
