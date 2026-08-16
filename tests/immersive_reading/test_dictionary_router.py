import pytest

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient


@pytest.fixture
def client(monkeypatch):
    import deeptutor.api.routers.immersive_reading as router_module

    class FakeService:
        async def lookup_dictionary(self, word, context):
            assert word == "bright"
            assert "harbour" in context
            return {
                "word": word,
                "phonetic": "/braɪt/",
                "definitions": [
                    {
                        "part_of_speech": "adj.",
                        "definition": "full of light",
                        "chinese": "明亮的",
                        "example": "The harbour was bright.",
                        "synonyms": ["luminous"],
                        "context_match": True,
                    }
                ],
                "chinese": "明亮的",
                "context_note": "Fits the harbour scene.",
            }

        def dictionary_status(self):
            return {
                "installed": True,
                "path": "/tmp/ecdict.db",
                "entries": 3,
                "size_bytes": 128,
                "error": "",
            }

    app = FastAPI()
    monkeypatch.setattr(router_module, "get_immersive_reading_service", lambda: FakeService())
    app.include_router(router_module.router, prefix="/api/v1/immersive-reading")
    return TestClient(app)


def test_dictionary_returns_structured_context_result(client):
    response = client.post(
        "/api/v1/immersive-reading/dictionary",
        json={"word": "bright", "context": "The bright harbour slept."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["definitions"][0]["context_match"] is True
    assert payload["chinese"] == "明亮的"


def test_dictionary_rejects_empty_word(client):
    response = client.post("/api/v1/immersive-reading/dictionary", json={"word": ""})

    assert response.status_code == 422


def test_dictionary_status_reports_offline_database(client):
    response = client.get("/api/v1/immersive-reading/dictionary/status")

    assert response.status_code == 200
    assert response.json() == {
        "installed": True,
        "path": "/tmp/ecdict.db",
        "entries": 3,
        "size_bytes": 128,
        "error": "",
    }
