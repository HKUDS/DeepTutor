from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import settings
from deeptutor.services.voice import preview
from deeptutor.services.voice.base import VoiceProviderError


def fixture_catalog(secret="secret"):
    return {
        "version": 1,
        "connections": [
            {"id": "c", "provider": "volcengine_speech", "api_key": secret, "app_id": "app"}
        ],
        "services": {
            "tts": {
                "active_profile_id": "p",
                "active_model_id": "old",
                "profiles": [
                    {
                        "id": "p",
                        "provider_ref": {"connection_id": "c", "binding": "volcengine_speech"},
                        "models": [
                            {"id": "old", "model": "seed-tts-1.0"},
                            {
                                "id": "new",
                                "model": "seed-tts-2.0",
                                "voice": "draft-speaker",
                                "language": "ja",
                                "speed": "1.2",
                            },
                        ],
                    }
                ],
            }
        },
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(
        settings,
        "get_model_catalog_service",
        lambda: SimpleNamespace(load=fixture_catalog, resolve_connections=deepcopy),
    )
    monkeypatch.setattr(
        settings,
        "get_settings_draft_service",
        lambda: SimpleNamespace(load=lambda: {"catalog": fixture_catalog("draft-secret")}),
    )
    app = FastAPI()
    app.include_router(settings.router, prefix="/settings")
    return TestClient(app)


def test_preview_uses_unsaved_selection_and_draft_secrets_without_writes(client, monkeypatch):
    async def synth(text, config):
        assert text == "こんにちは"
        assert config.model == "seed-tts-2.0"
        assert config.voice == "draft-speaker" and config.language == "ja"
        assert config.speed == 1.2 and config.api_key == "draft-secret" and config.app_id == "app"
        return b"\0\0", "audio/pcm;rate=16000;channels=1"

    monkeypatch.setattr(preview, "get_tts_adapter", lambda name: SimpleNamespace(synthesize=synth))
    catalog = fixture_catalog("***")
    before = deepcopy(catalog)
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": catalog, "profile_id": "p", "model_id": "new", "text": "こんにちは"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"RIFF")
    assert catalog == before


@pytest.mark.parametrize(
    "model,text,status", [("missing", "Hello", 400), ("new", " ", 400), ("new", "x" * 501, 422)]
)
def test_preview_rejects_invalid_selection_or_text(client, model, text, status):
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": fixture_catalog(), "profile_id": "p", "model_id": model, "text": text},
    )
    assert response.status_code == status


def test_preview_never_echoes_upstream_credentials(client, monkeypatch):
    async def synth(*args):
        raise VoiceProviderError("echo draft-secret Authorization: Bearer secret")

    monkeypatch.setattr(preview, "get_tts_adapter", lambda name: SimpleNamespace(synthesize=synth))
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": fixture_catalog(), "profile_id": "p", "model_id": "new", "text": "Hello"},
    )
    assert response.status_code == 502
    assert "secret" not in response.text and "Authorization" not in response.text


def test_preview_requires_admin(client, monkeypatch):
    from fastapi import HTTPException

    def denied():
        raise HTTPException(status_code=403)

    monkeypatch.setattr(settings, "_require_settings_admin", denied)
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": fixture_catalog(), "profile_id": "p", "model_id": "new", "text": "Hello"},
    )
    assert response.status_code == 403
