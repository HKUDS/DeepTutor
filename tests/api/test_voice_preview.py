from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import settings
from deeptutor.services.voice import preview
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError


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


def test_preview_uses_the_draft_timeout_without_a_hidden_sixty_second_cap(client, monkeypatch):
    async def synth(text, config):
        assert config.request_timeout == 180
        return b"audio", "audio/mpeg"

    monkeypatch.setattr(preview, "get_tts_adapter", lambda name: SimpleNamespace(synthesize=synth))
    catalog = fixture_catalog()
    catalog["services"]["tts"]["profiles"][0]["models"][1]["request_timeout"] = "180"
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": catalog, "profile_id": "p", "model_id": "new", "text": "Hello"},
    )
    assert response.status_code == 200


def test_preview_timeout_explains_the_setting_without_echoing_the_provider(client, monkeypatch):
    import httpx

    async def synth(*args):
        raise VoiceProviderError("secret") from httpx.ReadTimeout("upstream-secret")

    monkeypatch.setattr(preview, "get_tts_adapter", lambda name: SimpleNamespace(synthesize=synth))
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": fixture_catalog(), "profile_id": "p", "model_id": "new", "text": "Hello"},
    )
    assert response.status_code == 504
    assert "Request timeout (seconds)" in response.text
    assert "secret" not in response.text


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


@pytest.mark.parametrize(
    "status,diagnosis",
    [
        (401, "authentication failed"),
        (403, "access was denied"),
        (404, "not found"),
        (400, "parameters were rejected"),
        (422, "parameters were rejected"),
        (429, "quota or rate limit"),
        (503, "temporarily unavailable"),
    ],
)
def test_preview_explains_provider_failure_without_echoing_its_body(
    client, monkeypatch, status, diagnosis
):
    async def synth(*args):
        raise VoiceProviderHTTPError(
            "echo draft-secret Authorization: Bearer secret",
            status_code=status,
            body='{"message":"draft-secret"}',
        )

    monkeypatch.setattr(preview, "get_tts_adapter", lambda name: SimpleNamespace(synthesize=synth))
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": fixture_catalog(), "profile_id": "p", "model_id": "new", "text": "Hello"},
    )
    assert response.status_code == 502
    assert diagnosis in response.json()["detail"]
    assert "secret" not in response.text and "Authorization" not in response.text


def test_preview_synthesizes_the_unsaved_qwen_audio_plus_configuration(client, monkeypatch):
    """Run the screenshot's configuration through the real resolver and adapter."""
    catalog = fixture_catalog()
    catalog["connections"][0].update(
        provider="dashscope", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    catalog["services"]["tts"]["profiles"][0]["provider_ref"]["binding"] = "dashscope"
    catalog["services"]["tts"]["profiles"][0]["models"][1] = {
        "id": "new",
        "model": "qwen-audio-3.0-tts-plus",
        "voice": "longanlingxin",
        "response_format": "mp3",
    }
    before = deepcopy(catalog)

    async def post(_self, url, **kwargs):
        assert url == "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
        assert kwargs["json"] == {
            "model": "qwen-audio-3.0-tts-plus",
            "input": {
                "text": "你好，我是你的学习伙伴。",
                "voice": "longanlingxin",
                "format": "mp3",
                "sample_rate": 24000,
            },
        }
        return httpx.Response(
            200, json={"output": {"audio": {"url": "https://cdn.example/audio.mp3"}}}
        )

    async def get(_self, url, **kwargs):
        assert url == "https://cdn.example/audio.mp3"
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    response = client.post(
        "/settings/voice/preview",
        json={
            "catalog": catalog,
            "profile_id": "p",
            "model_id": "new",
            "text": "你好，我是你的学习伙伴。",
        },
    )
    assert response.status_code == 200 and response.content == b"ID3audio"
    assert response.headers["content-type"] == "audio/mpeg"
    assert catalog == before


@pytest.mark.parametrize("failure", ["timeout", "connection", "invalid_response", "download"])
def test_dashscope_preview_reports_the_failed_stage_without_exposing_credentials(
    client, monkeypatch, failure
):
    catalog = fixture_catalog()
    catalog["connections"][0].update(
        provider="dashscope", base_url="https://dashscope.aliyuncs.com/api/v1"
    )
    catalog["services"]["tts"]["profiles"][0]["provider_ref"]["binding"] = "dashscope"
    catalog["services"]["tts"]["profiles"][0]["models"][1] = {
        "id": "new",
        "model": "qwen3-tts-flash",
        "voice": "Cherry",
    }

    async def post(*args, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout("echo draft-secret")
        if failure == "connection":
            raise httpx.ConnectError("echo draft-secret")
        if failure == "invalid_response":
            return httpx.Response(200, text="draft-secret")
        return httpx.Response(
            200, json={"output": {"audio": {"url": "https://cdn.example/audio.wav"}}}
        )

    async def get(*args, **kwargs):
        return httpx.Response(403, text="draft-secret")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    response = client.post(
        "/settings/voice/preview",
        json={"catalog": catalog, "profile_id": "p", "model_id": "new", "text": "Hello"},
    )
    expected = {
        "timeout": "timed out",
        "connection": "Could not connect",
        "invalid_response": "invalid response",
        "download": "audio download failed",
    }
    assert response.status_code == (504 if failure == "timeout" else 502)
    assert expected[failure] in response.json()["detail"]
    assert "secret" not in response.text
