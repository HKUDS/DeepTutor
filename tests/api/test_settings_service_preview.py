from copy import deepcopy
import json
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import settings
from deeptutor.services.settings import service_preview
from deeptutor.services.voice import discovery


def catalog(key="secret"):
    return {
        "version": 1,
        "services": {
            name: {
                "active_profile_id": "p",
                "active_model_id": "old",
                "profiles": [
                    {
                        "id": "p",
                        "binding": "minimax",
                        "api_key": key,
                        "models": [
                            {"id": "old", "model": "old"},
                            {"id": "m", "model": "speech-2.8-hd"},
                        ],
                    }
                ],
            }
            for name in ("tts", "search", "stt", "imagegen", "videogen")
        },
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(
        settings,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=catalog, resolve_connections=deepcopy),
    )
    monkeypatch.setattr(
        settings,
        "get_settings_draft_service",
        lambda: SimpleNamespace(load=lambda: {"catalog": catalog("draft-secret")}),
    )
    app = FastAPI()
    app.include_router(settings.router, prefix="/settings")
    return TestClient(app)


def test_preview_restores_draft_secrets_and_never_applies(client, monkeypatch):
    async def events(draft, service, profile, model, text, audio, content_type):
        assert draft["services"]["search"]["profiles"][0]["api_key"] == "draft-secret"
        assert draft["services"]["search"]["active_model_id"] == "old"
        assert service == "search" and profile == "p" and text == "test query"
        yield {"type": "result", "kind": "search", "text": "", "results": []}

    monkeypatch.setattr(service_preview, "preview_events", events)
    response = client.post(
        "/settings/services/search/preview",
        json={"catalog": catalog("***"), "profile_id": "p", "text": "test query"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.text)["results"] == []


def test_voice_lookup_uses_draft_credentials(client, monkeypatch):
    async def discover(draft, profile, model):
        assert draft["services"]["tts"]["profiles"][0]["api_key"] == "draft-secret"
        assert profile == "p" and model == "m"
        return {"status": "unsupported", "voices": [], "scope": "none"}

    monkeypatch.setattr(discovery, "discover_voices", discover)
    response = client.post(
        "/settings/voice/voices",
        json={"catalog": catalog("***"), "profile_id": "p", "model_id": "m"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unsupported"


@pytest.mark.parametrize(
    "service,payload,status",
    [
        ("search", {"text": " "}, 400),
        ("llm", {"text": "test"}, 400),
        ("stt", {"audio": "not-base64", "content_type": "audio/wav"}, 400),
        ("imagegen", {"text": "test", "model_id": "missing"}, 400),
        ("search", {"text": "a" * 2001}, 422),
    ],
)
def test_invalid_previews_fail_before_calling_provider(client, service, payload, status):
    response = client.post(
        f"/settings/services/{service}/preview",
        json={"catalog": catalog(), "profile_id": "p", **payload},
    )
    assert response.status_code == status


@pytest.mark.parametrize("path", ["/settings/voice/voices", "/settings/services/search/preview"])
def test_preview_and_discovery_require_settings_admin(client, monkeypatch, path):
    def deny():
        raise HTTPException(status_code=403, detail="Admin required")

    monkeypatch.setattr(settings, "_require_settings_admin", deny)
    response = client.post(
        path, json={"catalog": catalog(), "profile_id": "p", "model_id": "m", "text": "test"}
    )
    assert response.status_code == 403
