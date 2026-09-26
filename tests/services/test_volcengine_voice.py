"""Native wire contracts: auth, resource selection, streaming termination and ASR."""

import base64
from copy import deepcopy
import io
import json
import wave

import httpx
import pytest

from deeptutor.services.config.provider_runtime import (
    resolve_stt_runtime_config,
    resolve_tts_runtime_config,
)
from deeptutor.services.voice.adapters.volcengine import VolcengineSTTAdapter, VolcengineTTSAdapter
from deeptutor.services.voice.audio import pcm_to_wav
from deeptutor.services.voice.base import VoiceProviderError
from deeptutor.services.voice.config import STTConfig, TTSConfig
from deeptutor.services.voice.options import voice_model_options


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


def tts(**kwargs):
    return TTSConfig(
        model="seed-tts-2.0",
        api_key="speech-secret",
        base_url="https://openspeech.bytedance.com/api/v3",
        voice="zh_female_vv_uranus_bigtts",
        **kwargs,
    )


def event(code=0, data=None):
    return "data: " + json.dumps({"code": code, "data": data}) + "\n\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("app_id,header", [("", "X-Api-Key"), ("legacy", "X-Api-Access-Key")])
async def test_tts_native_auth_resource_language_speed_and_complete_wav(
    monkeypatch, app_id, header
):
    pcm = b"\x00\x00\x01\x00"

    def handle(request):
        assert str(request.url).endswith("/api/v3/tts/unidirectional/sse")
        assert request.headers[header] == "speech-secret"
        assert request.headers["X-Api-Resource-Id"] == "seed-tts-2.0"
        assert "authorization" not in request.headers
        if app_id:
            assert request.headers["X-Api-App-Id"] == app_id
            assert "X-Api-App-Key" not in request.headers
        body = json.loads(request.content)
        params = body["req_params"]
        assert params["audio_params"] == {"format": "pcm", "sample_rate": 16000, "speech_rate": 25}
        assert json.loads(params["additions"]) == {
            "explicit_language": "ja",
            "context_texts": ["Speak gently."],
        }
        assert params["speaker"] == "zh_female_vv_uranus_bigtts"
        return httpx.Response(
            200, text="event: 352\n" + event(data=base64.b64encode(pcm).decode()) + event(20000000)
        )

    transport(monkeypatch, handle)
    audio, mime = await VolcengineTTSAdapter().synthesize(
        "こんにちは",
        tts(
            app_id=app_id,
            response_format="wav",
            sample_rate=16000,
            speed=1.25,
            language="ja",
            instructions="Speak gently.",
        ),
    )
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getframerate() == 16000
        assert wav.readframes(2) == pcm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        event(data="YWJj"),
        event(45000000),
        event(data="invalid!!!") + event(20000000),
        event(20000000),
        "data: not-json\n\n",
    ],
)
async def test_tts_rejects_partial_failed_empty_and_malformed_streams(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, text=body))
    with pytest.raises(VoiceProviderError):
        await VolcengineTTSAdapter().synthesize("hello", tts())


@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", ["", "legacy"])
async def test_stt_base64_upload_and_timestamps(monkeypatch, app_id):
    audio = pcm_to_wav(b"\x00\x00" * 160, 16000)

    def handle(request):
        assert str(request.url).endswith("/auc/bigmodel/recognize/flash")
        assert request.headers["X-Api-Resource-Id"] == "volc.bigasr.auc_turbo"
        assert request.headers["X-Api-Sequence"] == "-1"
        assert request.headers["X-Api-Access-Key" if app_id else "X-Api-Key"] == "speech-secret"
        if app_id:
            assert request.headers["X-Api-App-Key"] == app_id
            assert "X-Api-App-Id" not in request.headers
        body = json.loads(request.content)
        assert base64.b64decode(body["audio"]["data"]) == audio
        assert body["audio"]["language"] == "ja-JP"
        assert body["request"] == {"model_name": "bigmodel", "show_utterances": True}
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={
                "result": {
                    "text": "Hello",
                    "utterances": [{"start_time": 120, "end_time": 1200, "text": "Hello"}],
                }
            },
        )

    transport(monkeypatch, handle)
    config = STTConfig(
        model="bigmodel",
        api_key="speech-secret",
        app_id=app_id,
        language="ja-JP",
        base_url="https://openspeech.bytedance.com/api/v3",
    )
    cues = await VolcengineSTTAdapter().transcribe_cues(audio, config)
    assert (cues[0].start_seconds, cues[0].end_seconds, cues[0].text) == (0.12, 1.2, "Hello")


@pytest.mark.asyncio
@pytest.mark.parametrize("code,success", [("20000003", True), ("45000001", False), (None, False)])
async def test_stt_checks_business_status_even_on_http_200(monkeypatch, code, success):
    transport(
        monkeypatch,
        lambda r: httpx.Response(200, headers={"X-Api-Status-Code": code} if code else {}, json={}),
    )
    config = STTConfig(model="bigmodel", api_key="key", base_url="https://speech.test/api/v3")
    call = VolcengineSTTAdapter().transcribe(pcm_to_wav(b"\0\0", 16000), config)
    if success:
        assert await call == ""
    else:
        with pytest.raises(VoiceProviderError):
            await call


def catalog(provider="volcengine_speech", model="seed-tts-2.0"):
    return {
        "version": 1,
        "connections": [
            {
                "id": "speech",
                "provider": provider,
                "api_key": "secret",
                "app_id": "legacy",
                "base_url": "",
            }
        ],
        "services": {
            "tts": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "provider_ref": {"connection_id": "speech", "binding": provider},
                        "models": [{"id": "m", "model": model}],
                    }
                ],
            }
        },
    }


def test_model_specific_defaults_and_shared_legacy_credentials():
    c = catalog()
    before = deepcopy(c)
    config = resolve_tts_runtime_config(c)
    assert config.provider_name == "volcengine_speech"
    assert config.app_id == "legacy" and config.api_key == "secret"
    assert config.base_url == "https://openspeech.bytedance.com/api/v3"
    assert config.voice == "zh_female_vv_uranus_bigtts"
    assert resolve_tts_runtime_config(catalog(model="seed-tts-1.0")).voice.endswith("moon_bigtts")
    assert (
        resolve_tts_runtime_config(
            catalog("openrouter", "google/gemini-3.1-flash-tts-preview")
        ).voice
        == "Kore"
    )
    assert (
        resolve_tts_runtime_config(catalog("groq", "canopylabs/orpheus-v1-english")).response_format
        == "wav"
    )
    assert c == before
    c["services"]["stt"] = deepcopy(c["services"]["tts"])
    c["services"]["stt"]["profiles"][0]["models"][0]["model"] = "bigmodel"
    assert resolve_stt_runtime_config(c).app_id == "legacy"


def test_voice_choices_are_per_model_and_unknown_models_have_no_false_voice_defaults():
    assert "marin" not in [
        v["id"] for v in voice_model_options("openai", "tts", "tts-1-hd")["voices"]
    ]
    assert "marin" in [
        v["id"]
        for v in voice_model_options("openai", "tts", "gpt-4o-mini-tts-2025-12-15")["voices"]
    ]
    assert voice_model_options("openrouter", "tts", "private/voice-model")["voices"] == []
    assert voice_model_options("dashscope", "tts", "qwen3-tts-instruct-flash")["instructions"]
    assert voice_model_options("siliconflow", "tts", "FunAudioLLM/CosyVoice2-0.5B")["voices"][0][
        "id"
    ].endswith(":alex")


@pytest.mark.parametrize(
    "suffix,service",
    [
        ("tts/unidirectional/sse", "tts"),
        ("auc/bigmodel/recognize/flash", "stt"),
    ],
)
def test_native_full_endpoint_is_preserved_and_shared_base_is_derived(suffix, service):
    from deeptutor.services.config.provider_links import provider_endpoint
    from deeptutor.services.voice.base import join_audio_path

    base = "https://speech.example/api/v3"
    endpoint = f"{base}/{suffix}"
    assert join_audio_path(endpoint + "?region=test", suffix) == endpoint + "?region=test"
    assert provider_endpoint(endpoint, service, "stt" if service == "tts" else "tts") == base


@pytest.mark.asyncio
async def test_preview_enforces_model_text_limit_before_sending():
    from deeptutor.services.voice.preview import synthesize_preview

    with pytest.raises(ValueError, match="at most 200"):
        await synthesize_preview(
            catalog("groq", "canopylabs/orpheus-v1-english"), "p", "m", "x" * 201
        )


def test_native_speech_credentials_and_model_options_survive_catalog_save(tmp_path):
    from deeptutor.services.config.model_catalog import (
        ModelCatalogService,
        redact_catalog_secrets,
        restore_catalog_secrets,
    )

    store = ModelCatalogService(tmp_path / "catalog.json")
    saved = store.save(catalog())
    restored = restore_catalog_secrets(redact_catalog_secrets(saved), saved)
    loaded = store.save(restored)
    config = resolve_tts_runtime_config(loaded, service=store)
    assert config.api_key == "secret"
    assert config.app_id == "legacy"
    assert config.adapter == "volcengine"
    assert config.model == "seed-tts-2.0"
