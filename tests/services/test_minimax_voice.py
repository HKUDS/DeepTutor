"""MiniMax native speech wire format, failure handling and catalog integration."""

from copy import deepcopy
import json

import httpx
import pytest

from deeptutor.services.config.provider_runtime import TTS_PROVIDERS, resolve_tts_runtime_config
from deeptutor.services.voice import synthesize_speech
from deeptutor.services.voice.adapters.minimax import MiniMaxTTSAdapter
from deeptutor.services.voice.base import VoiceProviderError
from deeptutor.services.voice.config import TTSConfig
from deeptutor.services.voice.options import voice_model_options, voice_options


def transport(monkeypatch, handler):
    """Intercept actual HTTP requests without calling the speech service."""
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


def config(**overrides):
    """Build a speech configuration with non-secret test credentials."""
    values = {
        "model": "speech-2.8-hd",
        "api_key": "test-key",
        "base_url": "https://api.minimax.io/v1",
        "voice": "custom-voice",
    }
    return TTSConfig(**(values | overrides))


def success(audio="494433"):
    """Return the documented non-streaming completion envelope."""
    return {"base_resp": {"status_code": 0}, "data": {"status": 2, "audio": audio}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.minimax.io/v1",
        "https://api.minimaxi.com/v1/",
        "https://api.minimax.io/v1/t2a_v2",
    ],
)
@pytest.mark.parametrize(
    "fmt,mime",
    [
        ("mp3", "audio/mpeg"),
        ("wav", "audio/wav"),
        ("flac", "audio/flac"),
        ("pcm", "audio/pcm;rate=16000;channels=1"),
    ],
)
async def test_native_request_and_decoded_audio(monkeypatch, base_url, fmt, mime):
    def handle(request):
        assert request.method == "POST"
        assert request.url.path == "/v1/t2a_v2"
        assert request.url.host == httpx.URL(base_url).host
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["x-request-source"] == "test"
        assert json.loads(request.content) == {
            "model": "speech-2.8-hd",
            "text": "Hello",
            "stream": False,
            "output_format": "hex",
            "voice_setting": {"voice_id": "custom-voice", "speed": 1.25},
            "audio_setting": {"format": fmt, "sample_rate": 16000, "channel": 1},
            "language_boost": "English",
        }
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    assert await MiniMaxTTSAdapter().synthesize(
        "Hello",
        config(
            base_url=base_url,
            response_format=fmt,
            sample_rate=16000,
            speed=1.25,
            language="English",
            extra_headers={"X-Request-Source": "test"},
        ),
    ) == (b"ID3", mime)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"base_resp": None},
        {"base_resp": {"status_code": 1004, "status_msg": "private-text test-key"}},
        {"base_resp": {"status_code": 0}, "data": None},
        {"base_resp": {"status_code": 0}, "data": {"status": 1, "audio": "494433"}},
        success(None),
        success(""),
        success(" "),
        success("not-hex"),
        success("123"),
    ],
)
async def test_rejects_failed_partial_empty_and_malformed_responses(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, text=json.dumps(body)))
    with pytest.raises(VoiceProviderError) as caught:
        await MiniMaxTTSAdapter().synthesize("private-text", config())
    assert "private-text" not in str(caught.value)
    assert "test-key" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, "private-text test-key"), (200, "not-json")])
async def test_http_and_invalid_json_failures_do_not_echo_body(monkeypatch, status, body):
    transport(monkeypatch, lambda r: httpx.Response(status, text=body))
    with pytest.raises(VoiceProviderError) as caught:
        await MiniMaxTTSAdapter().synthesize("private-text", config())
    assert body not in str(caught.value)


@pytest.mark.asyncio
async def test_timeout_is_a_voice_provider_error(monkeypatch):
    def handle(request):
        raise httpx.ReadTimeout("private-text", request=request)

    transport(monkeypatch, handle)
    with pytest.raises(VoiceProviderError, match="timed out"):
        await MiniMaxTTSAdapter().synthesize("Hello", config())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"api_key": ""},
        {"api_key": "***"},
        {"voice": ""},
        {"response_format": "aac"},
        {"sample_rate": 48000},
        {"speed": 0.25},
        {"speed": 2.1},
        {"speed": float("nan")},
    ],
)
async def test_invalid_settings_fail_before_http(monkeypatch, overrides):
    def handle(request):
        pytest.fail("Invalid configuration must not issue an HTTP request")

    transport(monkeypatch, handle)
    with pytest.raises(VoiceProviderError):
        await MiniMaxTTSAdapter().synthesize("Hello", config(**overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", " ", "a" * 10000])
async def test_invalid_text_fails_before_http(monkeypatch, text):
    def handle(request):
        pytest.fail("Invalid text must not issue an HTTP request")

    transport(monkeypatch, handle)
    with pytest.raises(VoiceProviderError):
        await MiniMaxTTSAdapter().synthesize(text, config())


def catalog():
    """Use the same provider connection shape as Settings."""
    return {
        "version": 1,
        "connections": [{"id": "speech", "provider": "minimax", "api_key": "test-key"}],
        "services": {
            "tts": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "provider_ref": {"connection_id": "speech", "binding": "minimax"},
                        "models": [{"id": "m", "model": "speech-2.8-hd"}],
                    }
                ],
            }
        },
    }


@pytest.mark.asyncio
async def test_catalog_defaults_drive_read_aloud_and_request_overrides(monkeypatch):
    c = catalog()
    before = deepcopy(c)
    resolved = resolve_tts_runtime_config(c)
    assert resolved.adapter == resolved.provider_name == "minimax"
    assert resolved.model == TTS_PROVIDERS["minimax"].default_model == "speech-2.8-hd"
    assert resolved.base_url == "https://api.minimax.io/v1"
    assert resolved.voice == "English_expressive_narrator"
    assert resolved.response_format == "mp3"

    def handle(request):
        body = json.loads(request.content)
        assert body["text"] == "Hello world"
        assert body["voice_setting"] == {"voice_id": "custom-voice"}
        assert body["audio_setting"]["format"] == "wav"
        assert body["language_boost"] == "auto"
        return httpx.Response(200, json=success())

    transport(monkeypatch, handle)
    assert await synthesize_speech(
        "# Hello **world**",
        catalog=c,
        voice="custom-voice",
        response_format="wav",
        math_speak=False,
    ) == (b"ID3", "audio/wav")
    assert c == before


def test_settings_offer_speech_models_and_constrain_unknown_models():
    options = voice_options("minimax", "tts")
    assert [model["id"] for model in options["models"]] == [
        "speech-2.8-hd",
        "speech-2.8-turbo",
        "speech-2.6-hd",
        "speech-2.6-turbo",
        "speech-02-hd",
        "speech-02-turbo",
        "speech-01-hd",
        "speech-01-turbo",
    ]
    assert options["docs_url"] == "https://platform.minimax.io/docs/api-reference/speech-t2a-http"
    fallback = voice_model_options("minimax", "tts", "private-model")
    assert fallback["formats"] == ["mp3", "wav", "flac", "pcm"]
    assert fallback["voices"] == []
    assert fallback["speed"]["min"] == 0.5
    assert fallback["speed"]["max"] == 2
