"""Voice router tests — /tts and /stt request/response contracts."""

from __future__ import annotations

import io
from typing import Any
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import voice as voice_router
from deeptutor.services.voice import VoiceProviderError


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(voice_router.router, prefix="/api/v1/voice")
    return TestClient(app)


def test_tts_returns_audio_bytes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_synth(text: str, *, voice=None, response_format=None, **_: Any):
        captured["text"] = text
        captured["voice"] = voice
        captured["format"] = response_format
        return b"audio-bytes", "audio/mpeg"

    monkeypatch.setattr(voice_router, "synthesize_speech", fake_synth)
    resp = client.post("/api/v1/voice/tts", json={"text": "hello", "voice": "nova"})
    assert resp.status_code == 200
    assert resp.content == b"audio-bytes"
    assert resp.headers["content-type"] == "audio/mpeg"
    assert captured == {"text": "hello", "voice": "nova", "format": None}


def test_tts_wraps_pcm_bytes_as_browser_playable_wav(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm = b"\x00\x00\x01\x00" * 12

    async def fake_synth(text: str, *, voice=None, response_format=None, **_: Any):
        return pcm, "audio/pcm;rate=24000;channels=1"

    monkeypatch.setattr(voice_router, "synthesize_speech", fake_synth)
    resp = client.post("/api/v1/voice/tts", json={"text": "hello"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content.startswith(b"RIFF")
    with wave.open(io.BytesIO(resp.content), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes()) == pcm


def test_tts_rejects_empty_text(client: TestClient) -> None:
    resp = client.post("/api/v1/voice/tts", json={"text": ""})
    assert resp.status_code == 422  # pydantic min_length


def test_tts_provider_error_is_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_: Any, **__: Any):
        raise VoiceProviderError("upstream down")

    monkeypatch.setattr(voice_router, "synthesize_speech", boom)
    resp = client.post("/api/v1/voice/tts", json={"text": "hi"})
    assert resp.status_code == 502
    assert "upstream down" in resp.json()["detail"]


def test_tts_missing_config_is_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_config(*_: Any, **__: Any):
        raise ValueError("No active TTS model is configured.")

    monkeypatch.setattr(voice_router, "synthesize_speech", no_config)
    resp = client.post("/api/v1/voice/tts", json={"text": "hi"})
    assert resp.status_code == 400


def test_stt_returns_text(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_transcribe(audio: bytes, *, filename: str, content_type: str, language=None):
        captured["bytes"] = len(audio)
        captured["filename"] = filename
        return "hello world"

    monkeypatch.setattr(voice_router, "transcribe_audio", fake_transcribe)
    resp = client.post(
        "/api/v1/voice/stt",
        files={"file": ("clip.webm", b"audiobytes", "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"text": "hello world"}
    assert captured["filename"] == "clip.webm"
    assert captured["bytes"] == 10


def test_stt_rejects_empty_upload(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/voice/stt",
        files={"file": ("empty.webm", b"", "audio/webm")},
    )
    assert resp.status_code == 400
