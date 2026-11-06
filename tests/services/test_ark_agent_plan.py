"""One Agent Plan connection, all model services, and native speech wire contracts."""

import asyncio
import base64
from copy import deepcopy
import gzip
import io
import json
import struct
from types import SimpleNamespace
import wave

import aiohttp
import httpx
import pytest

from deeptutor.api.routers.settings import _connection_targets, _provider_choices
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.provider_runtime import (
    resolve_embedding_runtime_config,
    resolve_imagegen_runtime_config,
    resolve_llm_runtime_config,
    resolve_stt_runtime_config,
    resolve_tts_runtime_config,
    resolve_videogen_runtime_config,
)
from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.openai_compatible import OpenAICompatibleEmbeddingAdapter
from deeptutor.services.imagegen.adapters.openai_compat import OpenAICompatImagegenAdapter
from deeptutor.services.provider_registry import find_by_name
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.voice.adapters import get_stt_adapter, get_tts_adapter
from deeptutor.services.voice.adapters.ark_agent_plan import (
    ArkAgentPlanSTTAdapter,
    ArkAgentPlanTTSAdapter,
    _asr_url,
    _response_frame,
)
from deeptutor.services.voice.audio import pcm_to_wav
from deeptutor.services.voice.base import VoiceProviderError
from deeptutor.services.voice.config import STTConfig, TTSConfig
from deeptutor.services.voice.options import voice_options

PROVIDER = "volcengine_agent_plan"
ARK = "https://ark.cn-beijing.volces.com/api/plan/v3"
SPEECH = "https://openspeech.bytedance.com/api/v3/plan"
MODELS = {
    "llm": "doubao-seed-2.1-pro",
    "embedding": "doubao-embedding-vision",
    "imagegen": "doubao-seedream-5.0-flash",
    "videogen": "doubao-seedance-2.0",
    "tts": "seed-tts-2.0",
    "stt": "bigmodel",
}


def catalog(url="", api_format="auto"):
    return {
        "version": 1,
        "connections": [
            {
                "id": "plan",
                "provider": PROVIDER,
                "api_key": "plan-secret",
                "base_url": url,
                "api_format": api_format,
                "source_service": "llm",
            }
        ],
        "services": {
            service: {
                "active_profile_id": service,
                "active_model_id": service + "-model",
                "profiles": [
                    {
                        "id": service,
                        "name": service,
                        "provider_ref": {
                            "connection_id": "plan",
                            "binding": PROVIDER,
                            "default_base_url": (
                                SPEECH
                                if service in {"tts", "stt"}
                                else ARK + "/embeddings"
                                if service == "embedding"
                                else ARK
                            ),
                        },
                        "models": [{"id": service + "-model", "model": model, "dimension": "1024"}],
                    }
                ],
            }
            for service, model in MODELS.items()
        },
    }


@pytest.mark.parametrize(
    "url,api_format", [("", "auto"), (ARK, "auto"), (ARK.removesuffix("/v3"), "anthropic")]
)
def test_one_saved_key_routes_all_services_to_their_own_plan_endpoints(tmp_path, url, api_format):
    store = ModelCatalogService(tmp_path / "catalog.json")
    saved = store.save(catalog(url, api_format))
    before = deepcopy(saved)
    configs = {
        "llm": resolve_llm_runtime_config(saved, service=store),
        "embedding": resolve_embedding_runtime_config(saved, service=store),
        "imagegen": resolve_imagegen_runtime_config(saved, service=store),
        "videogen": resolve_videogen_runtime_config(saved, service=store),
        "tts": resolve_tts_runtime_config(saved, service=store),
        "stt": resolve_stt_runtime_config(saved, service=store),
    }
    for service, config in configs.items():
        assert config.api_key == "plan-secret"
        assert config.provider_name == PROVIDER
        assert config.model == MODELS[service]
        expected = (
            SPEECH
            if service in {"tts", "stt"}
            else ARK + "/embeddings"
            if service == "embedding"
            else ARK.removesuffix("/v3")
            if service == "llm" and api_format == "anthropic"
            else ARK
        )
        assert config.base_url == expected
    assert isinstance(get_tts_adapter(configs["tts"].adapter), ArkAgentPlanTTSAdapter)
    assert isinstance(get_stt_adapter(configs["stt"].adapter), ArkAgentPlanSTTAdapter)
    assert saved == before


def test_settings_offer_one_provider_with_all_service_targets():
    targets = [item for item in _connection_targets() if item["provider"] == PROVIDER]
    assert len(targets) == 1
    assert set(targets[0]["services"]) == set(MODELS)
    for service in MODELS:
        assert any(option["value"] == PROVIDER for option in _provider_choices()[service])
    spec = find_by_name(PROVIDER)
    assert spec.backend == "openai_compat"
    assert "anthropic" in spec.api_formats
    assert spec.default_api_base_for("anthropic") == ARK.removesuffix("/v3")
    assert voice_options(PROVIDER, "tts")["models"][0]["id"] == "seed-tts-2.0"
    assert voice_options(PROVIDER, "stt")["models"][0]["id"] == "bigmodel"


def install_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )


@pytest.mark.asyncio
async def test_missing_speaker_is_actionable_without_a_network_request(monkeypatch):
    from deeptutor.services.voice.preview import preview_failure_message

    def no_network(request):
        pytest.fail("Missing speaker must be rejected before synthesis")

    install_http(monkeypatch, no_network)
    with pytest.raises(VoiceProviderError) as error:
        await ArkAgentPlanTTSAdapter().synthesize(
            "Hello",
            TTSConfig(
                model="seed-tts-2.0",
                api_key="plan-secret",
                base_url=SPEECH,
            ),
        )
    assert (
        preview_failure_message(error.value)
        == "Enter a speaker ID before previewing this speech model."
    )


@pytest.mark.asyncio
async def test_embedding_posts_plan_text_model_and_configured_dimensions(monkeypatch):
    config = resolve_embedding_runtime_config(catalog())

    def handler(request):
        assert str(request.url) == ARK + "/embeddings"
        assert request.headers["Authorization"] == "Bearer plan-secret"
        assert json.loads(request.content) == {
            "input": ["Hello"],
            "model": "doubao-embedding-vision",
            "dimensions": 1024,
        }
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1] * 1024}],
                "usage": {},
            },
        )

    install_http(monkeypatch, handler)
    adapter = OpenAICompatibleEmbeddingAdapter(
        {
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "dimensions": config.dimension,
            "send_dimensions": config.send_dimensions,
        }
    )
    result = await adapter.embed(EmbeddingRequest(texts=["Hello"], model=config.model))
    assert len(result.embeddings) == 1 and len(result.embeddings[0]) == 1024


@pytest.mark.asyncio
async def test_image_and_video_use_the_same_key_on_plan_generation_endpoints(monkeypatch):
    seen = []

    def handler(request):
        assert request.headers["Authorization"] == "Bearer plan-secret"
        body = json.loads(request.content)
        seen.append(str(request.url))
        if request.url.path.endswith("/images/generations"):
            assert body["model"] == MODELS["imagegen"]
            return httpx.Response(200, json={"data": [{"b64_json": "aW1hZ2U="}]})
        assert request.url.path.endswith("/contents/generations/tasks")
        assert body["model"] == MODELS["videogen"]
        return httpx.Response(200, json={"id": "video-task"})

    install_http(monkeypatch, handler)
    images = await OpenAICompatImagegenAdapter().generate(
        "A cat",
        resolve_imagegen_runtime_config(catalog()),
    )
    assert images == [(b"image", "image/png")]
    assert (
        await AsyncTaskVideogenAdapter().submit_task(
            "A cat",
            resolve_videogen_runtime_config(catalog()),
        )
        == "video-task"
    )
    assert seen == [ARK + "/images/generations", ARK + "/contents/generations/tasks"]


@pytest.mark.asyncio
async def test_tts_uses_plan_key_and_ndjson_not_sse(monkeypatch):
    pcm = b"\x00\x00\x01\x00"

    def handler(request):
        assert str(request.url) == SPEECH + "/tts/unidirectional"
        assert request.headers["X-Api-Key"] == "plan-secret"
        assert request.headers["X-Api-Resource-Id"] == "seed-tts-2.0"
        assert "authorization" not in request.headers
        assert "X-Api-Access-Key" not in request.headers
        body = json.loads(request.content)["req_params"]
        assert body["speaker"] == "zh_female_vv_uranus_bigtts"
        assert body["audio_params"] == {"format": "pcm", "sample_rate": 24000}
        return httpx.Response(
            200,
            text="\n".join(
                [
                    json.dumps({"code": 0, "data": base64.b64encode(pcm).decode()}),
                    json.dumps({"code": 20000000}),
                ]
            ),
        )

    install_http(monkeypatch, handler)
    config = TTSConfig(
        model="seed-tts-2.0",
        api_key="plan-secret",
        base_url=SPEECH,
        voice="zh_female_vv_uranus_bigtts",
        response_format="wav",
    )
    audio, mime = await ArkAgentPlanTTSAdapter().synthesize("Hello", config)
    assert mime == "audio/wav"
    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.readframes(2) == pcm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        '{"code": 0, "data": "YWJj"}\n',  # Interrupted stream.
        '{"code": 20000000}\n',  # No audio.
        '{"code": 45000000, "message": "plan-secret"}\n',
        '{"code": 0, "data": "invalid!"}\n',
        "not json\n",
    ],
)
async def test_tts_rejects_failed_or_partial_stream_without_exposing_key(monkeypatch, body):
    install_http(monkeypatch, lambda request: httpx.Response(200, text=body))
    with pytest.raises(VoiceProviderError) as error:
        await ArkAgentPlanTTSAdapter().synthesize(
            "Hello",
            TTSConfig(
                model="seed-tts-2.0",
                api_key="plan-secret",
                base_url=SPEECH,
                voice="speaker",
            ),
        )
    assert "plan-secret" not in str(error.value)


def server_frame(data, *, final=False, compressed=True):
    payload = json.dumps(data).encode()
    if compressed:
        payload = gzip.compress(payload)
    return (
        bytes((0x11, 0x93 if final else 0x91, 0x11 if compressed else 0x10, 0))
        + struct.pack(">iI", -3 if final else 1, len(payload))
        + payload
    )


class FakeSocket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.uploaded = asyncio.Event()
        self.closed = False
        self._response = SimpleNamespace(headers={"X-Tt-Logid": "test-log"})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send_bytes(self, frame):
        self.sent.append(frame)
        if frame[1] & 2:
            self.uploaded.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.uploaded.wait()
        if not self.frames:
            raise StopAsyncIteration
        return SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=self.frames.pop(0))


def install_socket(monkeypatch, frames):
    socket = FakeSocket(frames)
    calls = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def ws_connect(self, url, **kwargs):
            calls.append((url, kwargs))
            return socket

    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    return socket, calls


@pytest.mark.asyncio
async def test_asr_normalizes_audio_sends_sequenced_frames_and_returns_final_timestamps(
    monkeypatch,
):
    socket, calls = install_socket(
        monkeypatch,
        [
            server_frame({"result": {"text": "partial"}}),
            server_frame(
                {
                    "result": {
                        "text": "Hello",
                        "utterances": [
                            {"text": "Hello", "start_time": 100, "end_time": 500},
                        ],
                    }
                },
                final=True,
            ),
        ],
    )
    pcm = b"\x01\x00" * 4000
    cues = await ArkAgentPlanSTTAdapter().transcribe_cues(
        pcm_to_wav(pcm, 16000),
        STTConfig(model="bigmodel", api_key="plan-secret", base_url=SPEECH),
    )
    assert calls[0][0] == "wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream"
    headers = calls[0][1]["headers"]
    assert headers["X-Api-Key"] == "plan-secret"
    assert headers["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
    request = json.loads(gzip.decompress(socket.sent[0][12:]))
    assert request["audio"]["format"] == "pcm"
    assert request["request"]["model_name"] == "bigmodel"
    assert [struct.unpack_from(">i", frame, 4)[0] for frame in socket.sent] == [1, 2, -3]
    assert b"".join(gzip.decompress(frame[12:]) for frame in socket.sent[1:]) == pcm
    assert (cues[0].text, cues[0].start_seconds, cues[0].end_seconds) == ("Hello", 0.1, 0.5)
    assert socket.closed


@pytest.mark.asyncio
async def test_asr_does_not_return_partial_text_on_disconnect(monkeypatch):
    socket, _ = install_socket(monkeypatch, [server_frame({"result": {"text": "partial"}})])
    with pytest.raises(VoiceProviderError, match="before recognition completed"):
        await ArkAgentPlanSTTAdapter().transcribe(
            pcm_to_wav(b"\0\0", 16000), STTConfig(model="bigmodel", api_key="key", base_url=SPEECH)
        )
    assert socket.closed


@pytest.mark.parametrize("frame", [b"", b"\x11\x91\x11\0", server_frame([]), server_frame({})[:-1]])
def test_asr_rejects_malformed_frames(frame):
    with pytest.raises(ValueError):
        _response_frame(frame)


@pytest.mark.parametrize("compressed", [False, True])
def test_asr_accepts_silence_and_uncompressed_final_responses(compressed):
    data, final = _response_frame(
        server_frame({"code": 20000003}, final=True, compressed=compressed)
    )
    assert final and data["result"]["text"] == ""


def test_asr_rejects_server_errors_without_echoing_payload():
    frame = b"\x11\xf0\x11\0" + struct.pack(">II", 45000001, 11) + b"plan-secret"
    with pytest.raises(VoiceProviderError, match="45000001") as error:
        _response_frame(frame)
    assert "plan-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_asr_timeout_closes_socket(monkeypatch):
    socket, _ = install_socket(monkeypatch, [])

    async def never_receive():
        await asyncio.Event().wait()

    # Special methods are looked up on the class.
    monkeypatch.setattr(FakeSocket, "__anext__", lambda self: never_receive())
    with pytest.raises(VoiceProviderError, match="timed out"):
        await ArkAgentPlanSTTAdapter().transcribe(
            pcm_to_wav(b"\0\0", 16000),
            STTConfig(model="bigmodel", api_key="key", base_url=SPEECH, request_timeout=0.01),
        )
    assert socket.closed


@pytest.mark.parametrize(
    "base,expected",
    [
        (SPEECH, "wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream"),
        ("http://gateway.test/plan", "ws://gateway.test/plan/sauc/bigmodel_nostream"),
        (
            "wss://gateway.test/plan/sauc/bigmodel_async",
            "wss://gateway.test/plan/sauc/bigmodel_async",
        ),
    ],
)
def test_asr_preserves_custom_endpoint(base, expected):
    assert _asr_url(base) == expected
