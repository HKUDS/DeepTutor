"""xAI Grok Voice and Mistral Voxtral adapter tests."""

from __future__ import annotations

import json

import httpx
import pytest

from deeptutor.services.config.provider_runtime import STT_PROVIDERS, TTS_PROVIDERS
from deeptutor.services.voice.adapters.mistral import MistralSTTAdapter, MistralTTSAdapter
from deeptutor.services.voice.adapters.xai import XaiSTTAdapter, XaiTTSAdapter
from deeptutor.services.voice.config import STTConfig, TTSConfig
from deeptutor.services.voice.options import voice_options


def transport(monkeypatch, handler):
    """Run the adapter against an in-process HTTP transport."""
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )


def tts_config(**overrides) -> TTSConfig:
    values = {
        "model": "grok-tts",
        "api_key": "test-key",
        "base_url": "https://api.x.ai/v1",
        "voice": "ara",
        "language": "fr",
    }
    return TTSConfig(**(values | overrides))


def stt_config(**overrides) -> STTConfig:
    values = {
        "model": "grok-voice-transcribe-2.0",
        "api_key": "test-key",
        "base_url": "https://api.x.ai/v1",
        "language": "fr",
    }
    return STTConfig(**(values | overrides))


def test_voice_provider_specs() -> None:
    assert TTS_PROVIDERS["xai"].adapter == "xai_tts"
    assert TTS_PROVIDERS["mistral"].adapter == "mistral_tts"
    assert STT_PROVIDERS["xai"].adapter == "xai_stt"
    assert STT_PROVIDERS["mistral"].adapter == "mistral_stt"


def test_xai_voice_options() -> None:
    tts = voice_options("xai", "tts")
    stt = voice_options("xai", "stt")

    assert [model["id"] for model in tts["models"]] == ["grok-tts"]
    assert "mp3" in tts["models"][0]["formats"]
    assert [model["id"] for model in stt["models"]] == ["grok-voice-transcribe-2.0"]


def test_mistral_voice_options() -> None:
    tts = voice_options("mistral", "tts")
    stt = voice_options("mistral", "stt")

    assert [model["id"] for model in tts["models"]] == ["voxtral-mini-tts-2603"]
    assert "opus" in tts["models"][0]["formats"]
    assert [model["id"] for model in stt["models"]] == [
        "voxtral-mini-latest",
        "voxtral-small-latest",
    ]


@pytest.mark.asyncio
async def test_xai_tts_payload(monkeypatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/tts"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "text": "Bonjour",
            "voice_id": "ara",
            "language": "fr",
            "output_format": {
                "codec": "mp3",
                "sample_rate": 24000,
                "bit_rate": 128000,
            },
        }
        return httpx.Response(200, content=b"ID3", headers={"content-type": "audio/mpeg"})

    transport(monkeypatch, handle)
    assert await XaiTTSAdapter().synthesize("Bonjour", tts_config()) == (
        b"ID3",
        "audio/mpeg",
    )


@pytest.mark.asyncio
async def test_xai_stt_multipart(monkeypatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/stt"
        assert b'name="model"' in request.content
        assert b'name="language"' in request.content
        assert b'name="file"' in request.content
        return httpx.Response(200, json={"text": "Bonjour"})

    transport(monkeypatch, handle)
    text = await XaiSTTAdapter().transcribe(
        b"RIFF",
        stt_config(),
        filename="sample.wav",
        content_type="audio/wav",
    )
    assert text == "Bonjour"


@pytest.mark.asyncio
async def test_mistral_tts_payload(monkeypatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        assert json.loads(request.content) == {
            "model": "voxtral-mini-tts-2603",
            "input": "Bonjour",
            "response_format": "mp3",
            "voice_id": "eve",
        }
        return httpx.Response(200, content=b"ID3")

    transport(monkeypatch, handle)
    assert await MistralTTSAdapter().synthesize(
        "Bonjour",
        TTSConfig(
            model="voxtral-mini-tts-2603",
            api_key="test-key",
            base_url="https://api.mistral.ai/v1",
            voice="eve",
        ),
    ) == (b"ID3", "audio/mpeg")


@pytest.mark.asyncio
async def test_mistral_stt_transcribes_directly_without_remote_upload(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/audio/transcriptions":
            assert b'name="file"' in request.content
            assert b'filename="sample.wav"' in request.content
            assert b"RIFF" in request.content
            assert b'name="file_url"' not in request.content
            return httpx.Response(200, json={"text": "Bonjour"})
        raise AssertionError(f"unexpected request: {request.url}")

    transport(monkeypatch, handle)
    text = await MistralSTTAdapter().transcribe(
        b"RIFF",
        STTConfig(
            model="voxtral-mini-latest",
            api_key="test-key",
            base_url="https://api.mistral.ai/v1",
            language="fr",
        ),
        filename="sample.wav",
        content_type="audio/wav",
    )
    assert text == "Bonjour"
    assert calls == [
        ("POST", "/v1/audio/transcriptions"),
    ]


@pytest.mark.asyncio
async def test_mistral_error_does_not_echo_upstream_body(monkeypatch):
    from deeptutor.services.voice.base import VoiceProviderHTTPError

    transport(monkeypatch, lambda request: httpx.Response(401, text="secret-recording-content"))
    with pytest.raises(VoiceProviderHTTPError) as caught:
        await MistralSTTAdapter().transcribe(
            b"audio",
            STTConfig(
                model="voxtral-mini-latest", api_key="test", base_url="https://api.mistral.ai/v1"
            ),
        )
    assert "secret-recording-content" not in str(caught.value)
