"""Tests for the native Volcengine (Doubao / Seed-TTS) TTS adapter.

The wire format here is not OpenAI-shaped — a base64 audio stream framed as
JSON documents, selected by headers — so these tests pin the request headers,
the request body, the stream parsing and every failure mode the adapter is
expected to turn into a ``VoiceProviderError``. No test reaches the network.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config
from deeptutor.services.voice import synthesize_speech
from deeptutor.services.voice.adapters import TTS_ADAPTERS
from deeptutor.services.voice.adapters.volcengine import (
    DEFAULT_ENDPOINT,
    DEFAULT_RESOURCE_ID,
    VolcengineTTSAdapter,
)
from deeptutor.services.voice.base import VoiceProviderError, VoiceProviderHTTPError
from deeptutor.services.voice.config import TTSConfig

ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


class _FakeStream:
    """Stands in for ``httpx.AsyncClient.stream``'s context manager."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        chunks: tuple[str, ...] = (),
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self._chunks = list(chunks)
        self._body = "".join(self._chunks).encode("utf-8")

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False

    async def aiter_text(self) -> Any:
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return self._body


def _capture_stream(
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
) -> dict[str, Any]:
    """Patch ``httpx.AsyncClient.stream``; ``response`` may be a callable."""
    captured: dict[str, Any] = {}

    def fake_stream(self: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> Any:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return response() if callable(response) else response

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)
    return captured


def _documents(*objects: dict[str, Any]) -> str:
    return "".join(json.dumps(obj, ensure_ascii=False) + "\n" for obj in objects)


def _audio_document(payload: bytes) -> dict[str, Any]:
    return {"code": 0, "message": "", "data": base64.b64encode(payload).decode("ascii")}


def _final_document() -> dict[str, Any]:
    return {"code": 20000000, "message": "ok", "data": None, "usage": {"text_words": 3}}


def _config(**overrides: Any) -> TTSConfig:
    values: dict[str, Any] = {
        "model": "seed-tts-2.0",
        "provider_name": "volcengine",
        "adapter": "volcengine_tts",
        "api_key": "volc-test-key",
        "base_url": ENDPOINT,
        "voice": "zh_female_yingyujiaoxue_uranus_bigtts",
        "response_format": "mp3",
    }
    values.update(overrides)
    return TTSConfig(**values)


def _catalog(**profile_overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "id": "p1",
        "binding": "volcengine",
        "base_url": "",
        "api_key": "volc-test-key",
        "models": [{"id": "m1", "model": "seed-tts-2.0", "voice": ""}],
    }
    profile.update(profile_overrides)
    return {
        "version": 1,
        "services": {
            "tts": {
                "active_profile_id": "p1",
                "active_model_id": "m1",
                "profiles": [profile],
            }
        },
    }


# ── registration and catalog resolution ───────────────────────────────────


def test_volcengine_adapter_is_registered() -> None:
    assert isinstance(TTS_ADAPTERS["volcengine_tts"], VolcengineTTSAdapter)


def test_resolve_volcengine_tts_config_fills_provider_defaults() -> None:
    cfg = resolve_tts_runtime_config(catalog=_catalog())

    assert cfg.provider_name == "volcengine"
    assert cfg.adapter == "volcengine_tts"
    assert cfg.base_url == DEFAULT_ENDPOINT
    assert cfg.model == "seed-tts-2.0"
    # The requested default voice comes from the provider spec.
    assert cfg.voice == "zh_female_yingyujiaoxue_uranus_bigtts"
    assert cfg.api_key == "volc-test-key"
    assert cfg.resource_id == ""


def test_resolve_volcengine_tts_config_reads_resource_id() -> None:
    cfg = resolve_tts_runtime_config(catalog=_catalog(resource_id="seed-tts-1.0"))
    assert cfg.resource_id == "seed-tts-1.0"


@pytest.mark.asyncio
async def test_synthesize_speech_facade_dispatches_to_volcengine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog selection alone is enough to reach this adapter."""
    stream = _FakeStream(chunks=(_documents(_audio_document(b"facade"), _final_document()),))
    captured = _capture_stream(monkeypatch, stream)

    audio, content_type = await synthesize_speech("# Hi\n\n**bold**", catalog=_catalog())

    assert audio == b"facade"
    assert content_type == "audio/mpeg"
    # Markdown is cleaned before it reaches the provider, as for every other one.
    assert captured["json"]["req_params"]["text"] == "Hi\n\nbold"
    assert captured["headers"]["X-Api-Key"] == "volc-test-key"


# ── happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_concatenates_streamed_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(
        chunks=(
            _documents(_audio_document(b"first-"), _audio_document(b"second")),
            _documents(_final_document()),
        )
    )
    captured = _capture_stream(monkeypatch, stream)

    audio, content_type = await VolcengineTTSAdapter().synthesize("hello", _config())

    assert audio == b"first-second"
    assert content_type == "audio/mpeg"
    assert captured["method"] == "POST"
    assert captured["url"] == ENDPOINT

    headers = captured["headers"]
    assert headers["X-Api-Key"] == "volc-test-key"
    assert headers["X-Api-Resource-Id"] == DEFAULT_RESOURCE_ID
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Api-Request-Id"]  # a UUID, present but free-form

    body = captured["json"]
    assert body["user"]["uid"]
    assert body["req_params"]["text"] == "hello"
    assert body["req_params"]["speaker"] == "zh_female_yingyujiaoxue_uranus_bigtts"
    assert body["req_params"]["audio_params"] == {"format": "mp3", "sample_rate": 24000}
    # The model is selected by header, not in the body.
    assert "model" not in body["req_params"]


@pytest.mark.asyncio
async def test_synthesize_reassembles_documents_split_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _documents(_audio_document(b"split-audio"), _final_document())
    midpoint = len(payload) // 2
    stream = _FakeStream(chunks=(payload[:midpoint], payload[midpoint:]))
    _capture_stream(monkeypatch, stream)

    audio, _ = await VolcengineTTSAdapter().synthesize("hello", _config())
    assert audio == b"split-audio"


@pytest.mark.asyncio
async def test_synthesize_accepts_sse_framing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pointing the base URL at the /sse variant must work unchanged."""
    stream = _FakeStream(
        chunks=(
            'event: 352\ndata: {"code":0,"message":"","data":"'
            + base64.b64encode(b"sse-audio").decode("ascii")
            + '"}\n',
            'event: 152\ndata: {"code":20000000,"message":"OK","data":null}\n',
        )
    )
    _capture_stream(monkeypatch, stream)

    audio, _ = await VolcengineTTSAdapter().synthesize("hello", _config(base_url=f"{ENDPOINT}/sse"))
    assert audio == b"sse-audio"


# ── failures ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(status_code=401, chunks=('{"error":"unauthorized"}',))
    _capture_stream(monkeypatch, stream)

    with pytest.raises(VoiceProviderHTTPError) as excinfo:
        await VolcengineTTSAdapter().synthesize("hello", _config())

    assert excinfo.value.status_code == 401
    assert "unauthorized" in str(excinfo.value)


@pytest.mark.asyncio
async def test_synthesize_raises_on_in_body_error(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(
        chunks=(
            _documents(
                _audio_document(b"partial"),
                {"code": 55000000, "message": "resource ID is mismatched", "data": None},
            ),
        )
    )
    _capture_stream(monkeypatch, stream)

    with pytest.raises(VoiceProviderError) as excinfo:
        await VolcengineTTSAdapter().synthesize("hello", _config())

    assert "55000000" in str(excinfo.value)
    # The opaque code is annotated with the likely cause.
    assert "resource id" in str(excinfo.value)


@pytest.mark.asyncio
async def test_synthesize_reports_unactivated_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(
        chunks=(
            _documents(
                {
                    "code": 45000000,
                    "message": "speaker permission denied: get resource id: access denied",
                }
            ),
        )
    )
    _capture_stream(monkeypatch, stream)

    with pytest.raises(VoiceProviderError, match="speaker permission denied"):
        await VolcengineTTSAdapter().synthesize("hello", _config())


@pytest.mark.asyncio
async def test_synthesize_raises_on_empty_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(chunks=(_documents(_final_document()),))
    _capture_stream(monkeypatch, stream)

    with pytest.raises(VoiceProviderError, match="empty audio"):
        await VolcengineTTSAdapter().synthesize("hello", _config())


@pytest.mark.asyncio
async def test_synthesize_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> Any:
        raise httpx.ConnectError("connection refused")

    _capture_stream(monkeypatch, explode)

    with pytest.raises(VoiceProviderError, match="request error"):
        await VolcengineTTSAdapter().synthesize("hello", _config())


@pytest.mark.asyncio
async def test_synthesize_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> Any:
        raise httpx.ReadTimeout("timed out")

    _capture_stream(monkeypatch, explode)

    with pytest.raises(VoiceProviderError, match="timed out"):
        await VolcengineTTSAdapter().synthesize("hello", _config())


@pytest.mark.asyncio
async def test_synthesize_raises_on_invalid_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _FakeStream(chunks=(_documents({"code": 0, "message": "", "data": "!!!not-base64"}),))
    _capture_stream(monkeypatch, stream)

    with pytest.raises(VoiceProviderError, match="unreadable audio chunk"):
        await VolcengineTTSAdapter().synthesize("hello", _config())


# ── configuration ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"base_url": ""}, "No endpoint URL configured"),
        ({"voice": ""}, "No Volcengine voice"),
        ({"api_key": ""}, "No Volcengine credentials"),
    ],
)
async def test_synthesize_requires_configuration(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(VoiceProviderError, match=match):
        await VolcengineTTSAdapter().synthesize("hello", _config(**overrides))


@pytest.mark.asyncio
async def test_legacy_console_credentials_via_extra_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _FakeStream(chunks=(_documents(_audio_document(b"legacy"), _final_document()),))
    captured = _capture_stream(monkeypatch, stream)

    config = _config(
        api_key="",
        extra_headers={"X-Api-App-Id": "123456789", "X-Api-Access-Key": "legacy-token"},
    )
    audio, _ = await VolcengineTTSAdapter().synthesize("hello", config)

    assert audio == b"legacy"
    assert captured["headers"]["X-Api-App-Id"] == "123456789"
    assert captured["headers"]["X-Api-Access-Key"] == "legacy-token"
    # The new-console header is not sent alongside the legacy pair.
    assert "X-Api-Key" not in captured["headers"]


@pytest.mark.asyncio
async def test_resource_id_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond() -> _FakeStream:
        return _FakeStream(chunks=(_documents(_audio_document(b"a"), _final_document()),))

    captured = _capture_stream(monkeypatch, respond)

    adapter = VolcengineTTSAdapter()
    # An explicit resource id wins over a model that also names one.
    await adapter.synthesize("hi", _config(model="seed-tts-2.0", resource_id="seed-tts-1.0"))
    assert captured["headers"]["X-Api-Resource-Id"] == "seed-tts-1.0"

    # A resource-id-shaped model stands in for one, so switching the catalog
    # model moves the request to the matching voice family.
    await adapter.synthesize("hi", _config(model="seed-tts-1.0"))
    assert captured["headers"]["X-Api-Resource-Id"] == "seed-tts-1.0"

    # A free-text model label is not sent as a resource id.
    await adapter.synthesize("hi", _config(model="Doubao Seed-TTS"))
    assert captured["headers"]["X-Api-Resource-Id"] == DEFAULT_RESOURCE_ID

    # Extra headers are merged last, so they can override the resource id.
    await adapter.synthesize("hi", _config(extra_headers={"X-Api-Resource-Id": "seed-icl-2.0"}))
    assert captured["headers"]["X-Api-Resource-Id"] == "seed-icl-2.0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("speed", "expected"),
    [(None, None), (1.0, None), (1.5, 50), (0.5, -50), (2.0, 100), (3.0, 100), (0.1, -50)],
)
async def test_speed_maps_to_speech_rate(
    monkeypatch: pytest.MonkeyPatch, speed: float | None, expected: int | None
) -> None:
    stream = _FakeStream(chunks=(_documents(_audio_document(b"a"), _final_document()),))
    captured = _capture_stream(monkeypatch, stream)

    await VolcengineTTSAdapter().synthesize("hi", _config(speed=speed))

    audio_params = captured["json"]["req_params"]["audio_params"]
    assert audio_params.get("speech_rate") == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response_format", "wire_format", "content_type"),
    [
        ("mp3", "mp3", "audio/mpeg"),
        ("opus", "ogg_opus", "audio/opus"),
        ("pcm", "pcm", "audio/pcm;rate=24000;channels=1"),
        # wav is requested as PCM and reported as such: the service repeats the
        # RIFF header per chunk, which a concatenated body cannot carry.
        ("wav", "pcm", "audio/pcm;rate=24000;channels=1"),
        ("", "mp3", "audio/mpeg"),
    ],
)
async def test_format_mapping(
    monkeypatch: pytest.MonkeyPatch,
    response_format: str,
    wire_format: str,
    content_type: str,
) -> None:
    stream = _FakeStream(chunks=(_documents(_audio_document(b"a"), _final_document()),))
    captured = _capture_stream(monkeypatch, stream)

    _, resolved = await VolcengineTTSAdapter().synthesize(
        "hi", _config(response_format=response_format)
    )

    assert captured["json"]["req_params"]["audio_params"]["format"] == wire_format
    assert resolved == content_type


@pytest.mark.asyncio
async def test_unsupported_format_is_rejected_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected() -> Any:
        raise AssertionError("no request should be made")

    _capture_stream(monkeypatch, unexpected)

    with pytest.raises(VoiceProviderError, match="cannot produce `flac`"):
        await VolcengineTTSAdapter().synthesize("hi", _config(response_format="flac"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        (DEFAULT_ENDPOINT, DEFAULT_ENDPOINT),
        ("https://openspeech.bytedance.com", DEFAULT_ENDPOINT),
        ("https://openspeech.bytedance.com/", DEFAULT_ENDPOINT),
        (
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
            "https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse",
        ),
        # A deployment that fronts the service on another path keeps it.
        ("https://tts.internal.example.com/volc/v3", "https://tts.internal.example.com/volc/v3"),
    ],
)
async def test_endpoint_resolution(
    monkeypatch: pytest.MonkeyPatch, base_url: str, expected: str
) -> None:
    stream = _FakeStream(chunks=(_documents(_audio_document(b"a"), _final_document()),))
    captured = _capture_stream(monkeypatch, stream)

    await VolcengineTTSAdapter().synthesize("hi", _config(base_url=base_url))
    assert captured["url"] == expected
