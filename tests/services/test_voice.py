"""Tests for the voice (TTS/STT) service layer.

Covers Markdown cleaning, the OpenAI-compatible adapters' wire shape, the
OpenRouter base64-JSON STT branch, Azure auth headers, and catalog-driven
config resolution.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from typing import Any

import aiohttp
import httpx
import pytest

from deeptutor.services.config.provider_runtime import (
    resolve_stt_runtime_config,
    resolve_tts_runtime_config,
)
from deeptutor.services.voice import synthesize_speech, transcribe_audio
from deeptutor.services.voice.adapters.dashscope import (
    DashScopeSTTAdapter,
    DashScopeTTSAdapter,
)
from deeptutor.services.voice.adapters.openai_compat import (
    OpenAICompatSTTAdapter,
    OpenAICompatTTSAdapter,
    OpenRouterTTSAdapter,
)
from deeptutor.services.voice.base import (
    build_auth_headers,
    join_audio_path,
    normalize_stt_content_type,
    strip_markdown_for_speech,
)
from deeptutor.services.voice.config import STTConfig, TTSConfig


def _capture_post(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> dict[str, Any]:
    """Patch ``httpx.AsyncClient.post`` to record args and return ``response``."""
    captured: dict[str, Any] = {}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        captured["headers"] = kwargs.get("headers")
        response.request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return captured


def _capture_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: Any,
    get: Any,
) -> dict[str, Any]:
    captured: dict[str, Any] = {"posts": [], "gets": []}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["posts"].append({"url": url, **kwargs})
        response = post(url, kwargs) if callable(post) else post
        response.request = httpx.Request("POST", url)
        return response

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["gets"].append({"url": url, **kwargs})
        response = get(url, kwargs) if callable(get) else get
        response.request = httpx.Request("GET", url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return captured


@dataclass
class _FakeWSMessage:
    data: dict[str, Any]
    type: aiohttp.WSMsgType = aiohttp.WSMsgType.TEXT

    def json(self) -> dict[str, Any]:
        return self.data


class _FakeWebSocket:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = list(messages)
        self.strings: list[str] = []
        self.chunks: list[bytes] = []

    async def send_str(self, value: str) -> None:
        self.strings.append(value)

    async def send_bytes(self, value: bytes) -> None:
        self.chunks.append(value)

    async def receive(self) -> _FakeWSMessage:
        return _FakeWSMessage(self.messages.pop(0))


# ── text cleaning ─────────────────────────────────────────────────────────


def test_strip_markdown_drops_code_and_unwraps_links() -> None:
    md = "# Title\n\nHello **world**, read [the docs](http://x).\n\n```py\nprint(1)\n```\n- one\n- two"
    out = strip_markdown_for_speech(md)
    assert "Title" in out and "Hello world" in out and "the docs" in out
    assert "print(1)" not in out  # fenced code dropped
    assert "**" not in out and "[" not in out and "#" not in out


def test_strip_markdown_truncates_on_boundary() -> None:
    out = strip_markdown_for_speech("Sentence one. Sentence two. Sentence three.", max_chars=20)
    assert len(out) <= 20
    assert out.endswith(".")


def test_strip_markdown_unwraps_latex_dollars() -> None:
    out = strip_markdown_for_speech("The identity is $E = mc^2$ and $$\\int x dx$$.")
    assert "$" not in out
    assert "\\" not in out
    assert "E = mc squared" in out
    assert "integral x dx" in out


def test_strip_markdown_unwraps_latex_parens_and_brackets() -> None:
    out = strip_markdown_for_speech(r"See \(a + b\) and \[c + d\].")
    assert "a + b" in out
    assert "c + d" in out
    assert "\\(" not in out
    assert "\\[" not in out


def test_strip_markdown_drops_unpaired_dollars() -> None:
    out = strip_markdown_for_speech("A leftover $ delimiter should not be spoken.")
    assert "$" not in out
    assert "leftover" in out
    assert "delimiter" in out


def test_strip_markdown_verbalizes_fractions_roots_and_greek() -> None:
    out = strip_markdown_for_speech(r"Take $\frac{1}{2}$ of $\sqrt{x}$ and $\alpha + \beta$.")
    assert "$" not in out
    assert "\\" not in out
    assert "{" not in out and "}" not in out
    assert "1 over 2" in out
    assert "square root of x" in out
    cube = strip_markdown_for_speech(r"$\sqrt[3]{x}$")
    assert "cube root of x" in cube
    assert "alpha" in out
    assert "beta" in out


def test_strip_markdown_verbalizes_nested_fraction() -> None:
    out = strip_markdown_for_speech(r"$\frac{1}{\frac{2}{3}}$")
    assert "1 over (2 over 3)" in out
    assert "\\frac" not in out


def test_strip_markdown_verbalizes_sum_limits() -> None:
    out = strip_markdown_for_speech(r"$$\sum_{i=1}^{n} i$$")
    assert "sum from i = 1 to n" in out
    assert "_" not in out
    assert "^" not in out


def test_strip_markdown_preserves_snake_case_outside_math() -> None:
    out = strip_markdown_for_speech("See file_name and $x_i$.")
    assert "file_name" in out
    assert "x sub i" in out
    assert "$" not in out


def test_strip_markdown_verbalizes_trig_and_inequality() -> None:
    out = strip_markdown_for_speech(r"If $\sin \theta \leq 1$ then done.")
    assert "sine" in out
    assert "theta" in out
    assert "less than or equal to 1" in out


def test_strip_markdown_leaves_windows_paths_alone() -> None:
    out = strip_markdown_for_speech(r"Saved at C:\Users\antmi\notes.md")
    assert r"C:\Users\antmi\notes.md" in out


def test_strip_markdown_keeps_windows_paths_beside_loose_tex() -> None:
    out = strip_markdown_for_speech(
        r"Saved at C:\Users\alpha\notes.md and \\server\share\beta.txt; use \frac{1}{2}."
    )
    assert r"C:\Users\alpha\notes.md" in out
    assert r"\\server\share\beta.txt" in out
    assert "1 over 2" in out


def test_strip_markdown_math_speak_off_keeps_inner_tex() -> None:
    out = strip_markdown_for_speech(
        r"The identity is $E = mc^2$ and $\frac{1}{2}$.",
        math_speak=False,
    )
    assert "$" not in out
    assert "E = mc^2" in out
    assert r"\frac{1}{2}" in out
    assert "squared" not in out
    assert "over" not in out


def test_join_audio_path_appends_and_preserves_full_url() -> None:
    assert join_audio_path("https://api.openai.com/v1", "audio/speech").endswith("/v1/audio/speech")
    full = "https://r.azure.com/openai/deployments/tts/audio/speech?api-version=2025"
    assert join_audio_path(full, "audio/speech") == full


def test_normalize_stt_content_type_strips_codec_parameters() -> None:
    assert normalize_stt_content_type("audio/webm;codecs=opus") == "audio/webm"
    assert normalize_stt_content_type(" audio/ogg; codecs=opus ") == "audio/ogg"
    assert normalize_stt_content_type("audio/wav") == "audio/wav"
    assert normalize_stt_content_type("") == "application/octet-stream"
    assert normalize_stt_content_type(None) == "application/octet-stream"


def test_auth_headers_styles() -> None:
    assert build_auth_headers("bearer", "k") == {"Authorization": "Bearer k"}
    assert build_auth_headers("api_key_header", "k") == {"api-key": "k"}
    assert build_auth_headers("token", "k") == {"Authorization": "Token k"}
    assert build_auth_headers("bearer", "") == {}


# ── TTS adapter ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tts_adapter_posts_openai_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, content=b"ID3audio-bytes", headers={"content-type": "audio/mpeg"})
    captured = _capture_post(monkeypatch, resp)
    config = TTSConfig(
        model="gpt-4o-mini-tts",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        voice="alloy",
        response_format="mp3",
    )
    audio, content_type = await OpenAICompatTTSAdapter().synthesize("hi there", config)
    assert audio == b"ID3audio-bytes"
    assert content_type == "audio/mpeg"
    assert captured["url"] == "https://api.openai.com/v1/audio/speech"
    assert captured["json"] == {
        "model": "gpt-4o-mini-tts",
        "input": "hi there",
        "response_format": "mp3",
        "voice": "alloy",
    }
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_tts_adapter_azure_uses_api_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, content=b"x", headers={"content-type": "audio/mpeg"})
    captured = _capture_post(monkeypatch, resp)
    config = TTSConfig(
        model="tts-1",
        base_url="https://r.azure.com/openai/deployments/tts/audio/speech?api-version=2025-04-01",
        api_key="azkey",
        auth_style="api_key_header",
        voice="alloy",
    )
    await OpenAICompatTTSAdapter().synthesize("hello", config)
    assert captured["headers"]["api-key"] == "azkey"
    assert "Authorization" not in captured["headers"]
    # Full /audio/ URL is preserved verbatim.
    assert captured["url"].endswith("api-version=2025-04-01")


@pytest.mark.asyncio
async def test_tts_adapter_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.voice.base import VoiceProviderError

    _capture_post(monkeypatch, httpx.Response(401, text="bad key"))
    config = TTSConfig(model="m", base_url="https://x/v1", api_key="k", voice="alloy")
    with pytest.raises(VoiceProviderError, match="401"):
        await OpenAICompatTTSAdapter().synthesize("hi", config)


@pytest.mark.asyncio
async def test_dashscope_tts_posts_native_shape_and_downloads_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = httpx.Response(
        200, json={"output": {"audio": {"url": "https://cdn.example.com/audio.wav"}}}
    )
    download = httpx.Response(200, content=b"WAVDATA", headers={"content-type": "audio/wav"})
    captured = _capture_http(monkeypatch, post=post, get=download)
    config = TTSConfig(
        model="qwen3-tts-instruct-flash",
        provider_name="dashscope",
        adapter="dashscope",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        api_key="dash-key",
        voice="Cherry",
        language="Chinese",
        instructions="Speak gently.",
    )

    audio, content_type = await DashScopeTTSAdapter().synthesize("hello", config)

    assert audio == b"WAVDATA"
    assert content_type == "audio/wav"
    assert captured["posts"][0]["url"] == (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    assert captured["posts"][0]["json"] == {
        "model": "qwen3-tts-instruct-flash",
        "input": {
            "text": "hello",
            "voice": "Cherry",
            "language_type": "Chinese",
            "instructions": "Speak gently.",
        },
    }
    assert captured["posts"][0]["headers"]["Authorization"] == "Bearer dash-key"
    assert captured["gets"][0]["url"] == "https://cdn.example.com/audio.wav"


@pytest.mark.asyncio
async def test_openrouter_tts_falls_back_to_chat_audio_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_calls: list[dict[str, Any]] = []

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        post_calls.append(
            {
                "url": url,
                "json": kwargs.get("json"),
                "headers": kwargs.get("headers"),
            }
        )
        if len(post_calls) == 1:
            response = httpx.Response(
                500,
                json={"error": {"message": "Internal Server Error"}},
            )
        else:
            chunk = {
                "choices": [
                    {
                        "delta": {
                            "audio": {
                                "data": base64.b64encode(b"pcm-audio").decode("ascii"),
                                "transcript": "hi",
                            }
                        }
                    }
                ]
            }
            response = httpx.Response(
                200,
                text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n",
                headers={"content-type": "text/event-stream"},
            )
        response.request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    config = TTSConfig(
        model="openai/gpt-4o-mini-tts",
        provider_name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="or-key",
        voice="alloy",
        response_format="pcm",
    )

    audio, content_type = await OpenRouterTTSAdapter().synthesize("hello", config)

    assert audio == b"pcm-audio"
    assert content_type == "audio/pcm"
    assert post_calls[0]["url"] == "https://openrouter.ai/api/v1/audio/speech"
    assert post_calls[1]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert post_calls[1]["json"]["modalities"] == ["text", "audio"]
    assert post_calls[1]["json"]["audio"] == {"voice": "alloy", "format": "pcm16"}
    assert post_calls[1]["headers"]["Authorization"] == "Bearer or-key"


@pytest.mark.asyncio
async def test_openrouter_gemini_tts_openai_voice_gets_clear_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.voice.base import VoiceProviderError

    _capture_post(
        monkeypatch,
        httpx.Response(500, json={"error": {"message": "Internal Server Error"}}),
    )
    config = TTSConfig(
        model="google/gemini-3.1-flash-tts-preview",
        provider_name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="or-key",
        voice="alloy",
        response_format="pcm",
    )
    with pytest.raises(VoiceProviderError, match="Kore"):
        await OpenRouterTTSAdapter().synthesize("hello", config)


# ── STT adapter ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stt_adapter_multipart(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, json={"text": "hello world"})
    captured = _capture_post(monkeypatch, resp)
    config = STTConfig(model="whisper-1", base_url="https://api.openai.com/v1", api_key="sk")
    text = await OpenAICompatSTTAdapter().transcribe(
        b"RIFFxxxx", config, filename="a.wav", content_type="audio/wav"
    )
    assert text == "hello world"
    assert captured["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert captured["files"]["file"][0] == "a.wav"
    assert captured["files"]["file"][2] == "audio/wav"
    assert captured["data"]["model"] == "whisper-1"


@pytest.mark.asyncio
async def test_stt_adapter_strips_codec_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, json={"text": "hello world"})
    captured = _capture_post(monkeypatch, resp)
    config = STTConfig(model="whisper-1", base_url="https://api.openai.com/v1", api_key="sk")
    text = await OpenAICompatSTTAdapter().transcribe(
        b"audiobytes",
        config,
        filename="recording.webm",
        content_type="audio/webm;codecs=opus",
    )
    assert text == "hello world"
    assert captured["files"]["file"][2] == "audio/webm"


@pytest.mark.asyncio
async def test_dashscope_stt_recognition_websocket_shape() -> None:
    task_id: str | None = None
    websocket = _FakeWebSocket(
        [
            {"header": {"event": "task-started"}},
            {
                "header": {"event": "result-generated"},
                "payload": {"output": {"sentence": [{"text": "hello "}, {"text": "world"}]}},
            },
            {"header": {"event": "task-finished"}},
        ]
    )

    # The fake pops start before the adapter knows its generated id. Patch the
    # id check with a dynamic side-effect-like object by deriving it from send.
    original_send = websocket.send_str

    async def record_start(value: str) -> None:
        nonlocal task_id
        await original_send(value)
        if task_id is None:
            task_id = json.loads(value)["header"]["task_id"]
            websocket.messages[0] = {"header": {"task_id": task_id, "event": "task-started"}}

    websocket.send_str = record_start  # type: ignore[method-assign]
    config = STTConfig(
        model="paraformer-v2",
        provider_name="dashscope",
        adapter="dashscope",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        api_key="dash-key",
    )

    text = await DashScopeSTTAdapter()._run_recognition(websocket, b"RIFFxxxx", config)

    assert text == "hello world"
    start = json.loads(websocket.strings[0])
    assert start["payload"]["model"] == "paraformer-v2"
    assert start["payload"]["parameters"] == {"format": "wav", "sample_rate": 16000}
    assert websocket.chunks == [b"RIFFxxxx"]
    assert json.loads(websocket.strings[-1])["header"]["action"] == "finish-task"


def test_dashscope_stt_url_and_errors() -> None:
    adapter = DashScopeSTTAdapter()
    assert adapter._websocket_url("https://dashscope.aliyuncs.com/api/v1") == (
        "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    )
    assert adapter._sentence_texts({"sentence": {"text": "single"}}) == ["single"]


@pytest.mark.asyncio
async def test_stt_adapter_openrouter_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, json={"text": "from base64"})
    captured = _capture_post(monkeypatch, resp)
    config = STTConfig(
        model="openai/whisper-large-v3",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk",
        request_style="base64_json",
    )
    text = await OpenAICompatSTTAdapter().transcribe(
        b"audiobytes", config, filename="clip.webm", content_type="audio/webm"
    )
    assert text == "from base64"
    assert captured["files"] is None  # not multipart
    assert captured["json"]["model"] == "openai/whisper-large-v3"
    assert captured["json"]["input_audio"]["format"] == "webm"
    assert captured["json"]["input_audio"]["data"]  # base64 string present


# ── catalog resolution ────────────────────────────────────────────────────


def _voice_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "tts": {
                "active_profile_id": "p1",
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "p1",
                        "binding": "siliconflow",
                        "base_url": "",
                        "api_key": "sf-key",
                        "models": [
                            {
                                "id": "m1",
                                "model": "FunAudioLLM/CosyVoice2-0.5B",
                                "voice": "FunAudioLLM/CosyVoice2-0.5B:anna",
                                "response_format": "wav",
                            }
                        ],
                    }
                ],
            },
            "stt": {
                "active_profile_id": "p2",
                "active_model_id": "m2",
                "profiles": [
                    {
                        "id": "p2",
                        "binding": "openrouter",
                        "base_url": "",
                        "api_key": "or-key",
                        "models": [{"id": "m2", "model": "openai/whisper-large-v3"}],
                    }
                ],
            },
        },
    }


def test_resolve_tts_config_uses_provider_default_base() -> None:
    cfg = resolve_tts_runtime_config(catalog=_voice_catalog())
    assert cfg.model == "FunAudioLLM/CosyVoice2-0.5B"
    assert cfg.provider_name == "siliconflow"
    assert cfg.base_url == "https://api.siliconflow.cn/v1"  # filled from spec default
    assert cfg.voice == "FunAudioLLM/CosyVoice2-0.5B:anna"
    assert cfg.response_format == "wav"
    assert cfg.api_key == "sf-key"


def test_resolve_stt_config_picks_openrouter_base64_style() -> None:
    cfg = resolve_stt_runtime_config(catalog=_voice_catalog())
    assert cfg.provider_name == "openrouter"
    assert cfg.request_style == "base64_json"
    assert cfg.base_url == "https://openrouter.ai/api/v1"


def test_resolve_dashscope_voice_configs() -> None:
    catalog = _voice_catalog()
    catalog["services"]["tts"]["profiles"][0]["binding"] = "aliyun"
    catalog["services"]["tts"]["profiles"][0]["models"][0] = {
        "id": "m1",
        "model": "qwen3-tts-flash",
        "voice": "",
    }
    catalog["services"]["stt"]["profiles"][0]["binding"] = "bailian"
    catalog["services"]["stt"]["profiles"][0]["models"][0]["model"] = "paraformer-v2"

    tts = resolve_tts_runtime_config(catalog=catalog)
    stt = resolve_stt_runtime_config(catalog=catalog)

    assert tts.provider_name == "dashscope"
    assert tts.adapter == "dashscope"
    assert tts.model == "qwen3-tts-flash"
    assert tts.voice == "Cherry"
    assert tts.base_url == "https://dashscope.aliyuncs.com/api/v1"
    assert stt.provider_name == "dashscope"
    assert stt.adapter == "dashscope"
    assert stt.model == "paraformer-v2"
    assert stt.base_url == tts.base_url


def test_resolve_tts_config_picks_openrouter_adapter() -> None:
    catalog = _voice_catalog()
    catalog["services"]["tts"]["profiles"][0]["binding"] = "openrouter"
    catalog["services"]["tts"]["profiles"][0]["models"][0]["model"] = (
        "google/gemini-3.1-flash-tts-preview"
    )
    cfg = resolve_tts_runtime_config(catalog=catalog)
    assert cfg.provider_name == "openrouter"
    assert cfg.adapter == "openrouter_tts"


def test_resolve_tts_config_raises_without_model() -> None:
    catalog = {"version": 1, "services": {"tts": {"profiles": []}}}
    with pytest.raises(ValueError, match="No active TTS model"):
        resolve_tts_runtime_config(catalog=catalog)


# ── facade ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_speech_facade_strips_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, content=b"audio", headers={"content-type": "audio/wav"})
    captured = _capture_post(monkeypatch, resp)
    audio, ctype = await synthesize_speech(
        "# Hi\n\n**bold** $x^2$",
        catalog=_voice_catalog(),
        math_speak=True,
    )
    assert audio == b"audio"
    spoken = captured["json"]["input"]
    assert spoken.startswith("Hi")
    assert "bold" in spoken
    assert "x squared" in spoken
    assert "$" not in spoken
    assert "^" not in spoken


@pytest.mark.asyncio
async def test_synthesize_speech_math_speak_off_keeps_caret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = httpx.Response(200, content=b"audio", headers={"content-type": "audio/wav"})
    captured = _capture_post(monkeypatch, resp)
    await synthesize_speech(
        "$x^2$",
        catalog=_voice_catalog(),
        math_speak=False,
    )
    spoken = captured["json"]["input"]
    assert "$" not in spoken
    assert "x^2" in spoken
    assert "squared" not in spoken


@pytest.mark.asyncio
async def test_synthesize_speech_reads_math_speak_from_ui_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.settings import interface_settings

    monkeypatch.setattr(interface_settings, "get_ui_settings", lambda: {"voice_math_speak": False})
    resp = httpx.Response(200, content=b"audio", headers={"content-type": "audio/wav"})
    captured = _capture_post(monkeypatch, resp)
    await synthesize_speech("$x^2$", catalog=_voice_catalog())
    assert "x^2" in captured["json"]["input"]
    assert "squared" not in captured["json"]["input"]


@pytest.mark.asyncio
async def test_transcribe_audio_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200, json={"text": "transcribed"})
    captured = _capture_post(monkeypatch, resp)
    text = await transcribe_audio(
        b"bytes",
        catalog=_voice_catalog(),
        filename="x.webm",
        content_type="audio/webm;codecs=opus",
    )
    assert text == "transcribed"
    assert captured["json"]["input_audio"]["format"] == "webm"
