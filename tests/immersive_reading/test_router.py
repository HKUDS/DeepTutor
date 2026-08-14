"""HTTP contract tests for the immersive-reading router."""

from __future__ import annotations

import pytest

from deeptutor.book.models import CharacterGraph, CharacterNode
from deeptutor.immersive_reading.models import DictionaryResult
from deeptutor.services.llm.exceptions import LLMAPIError, LLMTimeoutError
from tests.immersive_reading.epub_fixtures import build_epub

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


def test_character_graph_current_scope_uses_only_selected_section(
    client: TestClient, imported_document: dict, monkeypatch
) -> None:
    import deeptutor.book.character_graph as graph_module

    captured: dict = {}

    async def fake_extract_character_graph(**kwargs):
        captured.update(kwargs)
        return CharacterGraph(nodes=[CharacterNode(id="ada", name="Ada")])

    monkeypatch.setattr(graph_module, "extract_character_graph", fake_extract_character_graph)
    section_id = imported_document["sections"][2]["id"]

    response = client.post(
        f"/api/v1/immersive-reading/documents/{imported_document['id']}/character-graph",
        json={"section_id": section_id, "scope": "current"},
    )

    assert response.status_code == 200
    assert captured["included_chapter_ids"] == [section_id]
    assert "old harbor" in captured["text"]
    assert "old observatory" not in captured["text"]
    assert response.json()["graph"]["nodes"][0]["name"] == "Ada"


def test_character_graph_through_current_includes_prior_sections(
    client: TestClient, imported_document: dict, monkeypatch
) -> None:
    import deeptutor.book.character_graph as graph_module

    captured: dict = {}

    async def fake_extract_character_graph(**kwargs):
        captured.update(kwargs)
        return CharacterGraph()

    monkeypatch.setattr(graph_module, "extract_character_graph", fake_extract_character_graph)
    section_id = imported_document["sections"][2]["id"]

    response = client.post(
        f"/api/v1/immersive-reading/documents/{imported_document['id']}/character-graph",
        json={"section_id": section_id, "scope": "through_current", "force_refresh": True},
    )

    expected_ids = [section["id"] for section in imported_document["sections"][:3]]
    assert response.status_code == 200
    assert captured["included_chapter_ids"] == expected_ids
    assert "old observatory" in captured["text"]
    assert "old harbor" in captured["text"]


def test_character_graph_rejects_unknown_section(
    client: TestClient, imported_document: dict
) -> None:
    response = client.post(
        f"/api/v1/immersive-reading/documents/{imported_document['id']}/character-graph",
        json={"section_id": "missing-section", "scope": "current"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Section not found"


def test_original_epub_is_served_inline_with_epub_mime(client: TestClient, reading_service) -> None:
    document = reading_service.import_document("compass.epub", build_epub())

    response = client.get(f"/api/v1/immersive-reading/documents/{document['id']}/original")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/epub+zip")
    disposition = response.headers.get("content-disposition", "").lower()
    assert "inline" in disposition
    assert "attachment" not in disposition


def test_epub_progress_endpoint_persists_cfi_and_href(client: TestClient, reading_service) -> None:
    document = reading_service.import_document("compass.epub", build_epub())

    response = client.put(
        f"/api/v1/immersive-reading/documents/{document['id']}/epub-progress",
        json={
            "epub_cfi": "epubcfi(/6/8!/4/2/1:0)",
            "section_href": "chapter-2.xhtml",
            "scroll_percent": 33,
        },
    )

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["epub_cfi"] == "epubcfi(/6/8!/4/2/1:0)"
    assert progress["section_href"] == "chapter-2.xhtml"
    assert progress["current_section_id"] == document["sections"][1]["id"]
    assert progress["scroll_percent"] == 33


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (LLMAPIError("model missing", status_code=503, provider="ollama"), 503),
        (LLMTimeoutError("timed out", provider="ollama"), 504),
        (LLMAPIError("invalid json", status_code=None, provider="ollama"), 502),
    ],
)
def test_dictionary_error_statuses(
    client: TestClient, reading_service, monkeypatch, error, status
) -> None:
    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(reading_service, "lookup_word", fail)
    response = client.post(
        "/api/v1/immersive-reading/dictionary",
        json={"word": "technical"},
    )
    assert response.status_code == status


def test_dictionary_success_keeps_dictionary_result_shape(
    client: TestClient, reading_service, monkeypatch
) -> None:
    async def succeed(*_args, **_kwargs):
        return DictionaryResult(word="technical")

    monkeypatch.setattr(reading_service, "lookup_word", succeed)
    response = client.post(
        "/api/v1/immersive-reading/dictionary",
        json={"word": "technical", "context": "technical manual"},
    )
    assert response.status_code == 200
    assert response.json()["word"] == "technical"
