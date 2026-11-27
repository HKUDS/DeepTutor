import asyncio
import base64
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from deeptutor.services.settings import service_preview as preview
from deeptutor.services.voice import discovery
from deeptutor.services.voice.options import voice_options


def catalog(service="tts", provider="minimax", model="speech-2.8-hd"):
    return {
        "version": 1,
        "services": {
            service: {
                "active_profile_id": "p",
                "active_model_id": "old",
                "profiles": [
                    {
                        "id": "p",
                        "binding": provider,
                        "provider": provider,
                        "api_key": "test-secret",
                        "base_url": "https://vendor.test/v1",
                        "models": [
                            {"id": "old", "model": "old-model"},
                            {"id": "edited", "model": model},
                        ],
                    }
                ],
            }
        },
    }


def mock_client(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        discovery.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_minimax_queries_live_each_time_and_preserves_catalog(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url == "https://vendor.test/v1/get_voice"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={
                "base_resp": {"status_code": 0},
                "system_voice": [{"voice_id": f"live-{len(calls)}", "voice_name": "Live"}],
            },
        )

    mock_client(monkeypatch, handler)
    draft = catalog()
    before = deepcopy(draft)
    first = await discovery.discover_voices(draft, "p", "edited")
    second = await discovery.discover_voices(draft, "p", "edited")
    assert first["voices"][0]["id"] == "live-1"
    assert second["voices"][0]["id"] == "live-2"
    assert first["scope"] == "account" and draft == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-4o-mini-tts"),
        ("volcengine_speech", "seed-tts-2.0"),
        ("dashscope", "qwen3-tts-flash"),
    ],
)
async def test_unsupported_never_guesses_a_voice_endpoint(monkeypatch, provider, model):
    def handler(request):
        pytest.fail("Unsupported lookup must not send credentials")

    mock_client(monkeypatch, handler)
    result = await discovery.discover_voices(catalog(provider=provider, model=model), "p", "edited")
    assert result == {"status": "unsupported", "voices": [], "scope": "none"}


@pytest.mark.asyncio
async def test_dashscope_verifies_each_custom_voice_target_model(monkeypatch):
    import json

    def handler(request):
        body = json.loads(request.content)
        action = body["input"]["action"]
        if action == "list_voice":
            return httpx.Response(
                200,
                json={
                    "output": {
                        "voice_list": [
                            {"voice_id": "match", "status": "OK"},
                            {"voice_id": "other", "status": "OK"},
                            {"voice_id": "pending", "status": "DEPLOYING"},
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "output": {
                    "target_model": "qwen-audio-3.0-tts-plus"
                    if body["input"]["voice_id"] == "match"
                    else "wrong-model"
                }
            },
        )

    mock_client(monkeypatch, handler)
    result = await discovery.discover_voices(
        catalog(provider="dashscope", model="qwen-audio-3.0-tts-plus"), "p", "edited"
    )
    assert result["voices"] == [{"id": "match", "label": "match"}]
    assert result["scope"] == "custom"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"detail": "test-secret"}),
        (200, {"base_resp": {"status_code": 1004, "status_msg": "test-secret"}}),
        (200, []),
    ],
)
async def test_voice_errors_are_not_empty_success_or_secret_echo(monkeypatch, status, body):
    mock_client(monkeypatch, lambda req: httpx.Response(status, json=body))
    with pytest.raises(discovery.VoiceDiscoveryError) as exc:
        await discovery.discover_voices(catalog(), "p", "edited")
    assert "test-secret" not in str(exc.value)


def test_voice_hints_never_ship_voice_ids():
    for provider in (
        "openai",
        "azure_openai",
        "openrouter",
        "minimax",
        "dashscope",
        "volcengine_speech",
        "groq",
        "siliconflow",
        "xiaomi_mimo",
    ):
        options = voice_options(provider, "tts")
        assert all(model["voices"] == [] for model in [*options["models"], options["fallback"]])


async def collect(service, **kwargs):
    return [
        event
        async for event in preview.preview_events(
            catalog(service), service, "p", "edited", "example", **kwargs
        )
    ]


@pytest.mark.asyncio
async def test_search_uses_query_and_no_fallback_and_returns_results(monkeypatch):
    from deeptutor.services.config import provider_runtime
    from deeptutor.services.settings import provider_probe

    monkeypatch.setattr(
        provider_runtime,
        "resolve_search_runtime_config",
        lambda **kw: SimpleNamespace(
            requested_provider="brave", base_url="test", api_key="key", proxy="", max_results=5
        ),
    )

    def search(*args, **kwargs):
        assert (
            args[0] == "brave"
            and kwargs["query"] == "example"
            and kwargs["require_results"] is False
        )
        return SimpleNamespace(
            answer="",
            citations=[],
            search_results=[
                SimpleNamespace(title="Title", url="https://example.org", snippet="Result")
            ],
        )

    monkeypatch.setattr(provider_probe, "test_search_access", search)
    events = await collect("search")
    assert events[-1]["results"][0]["title"] == "Title"


@pytest.mark.asyncio
async def test_stt_transcribes_actual_audio_against_draft_selection(monkeypatch):
    from deeptutor.services import voice

    async def transcribe(raw, **kwargs):
        assert raw == b"real sample" and kwargs["filename"] == "sample.wav"
        assert kwargs["catalog"]["services"]["stt"]["active_model_id"] == "edited"
        return "Recognized words"

    monkeypatch.setattr(voice, "transcribe_audio", transcribe)
    assert (await collect("stt", audio=b"real sample", content_type="audio/wav"))[-1][
        "text"
    ] == "Recognized words"


@pytest.mark.asyncio
async def test_image_returns_only_completed_media(monkeypatch):
    from deeptutor.services import imagegen

    async def generate(*args, **kwargs):
        assert kwargs["n"] == 1
        return [(b"image", "image/png")]

    monkeypatch.setattr(imagegen, "generate_image", generate)
    result = (await collect("imagegen"))[-1]
    assert result["kind"] == "image" and base64.b64decode(result["data"]) == b"image"


@pytest.mark.asyncio
async def test_video_does_not_succeed_when_task_is_only_submitted(monkeypatch):
    from deeptutor.services import videogen

    accepted = asyncio.Event()
    finish = asyncio.Event()

    async def generate(*args, progress, **kwargs):
        await progress("submitted with secret-url")
        accepted.set()
        await finish.wait()
        return b"video", "video/mp4"

    monkeypatch.setattr(videogen, "generate_video", generate)
    stream = preview.preview_events(catalog("videogen"), "videogen", "p", "edited", "prompt")
    assert (await anext(stream))["phase"] == "requesting"
    event = await anext(stream)
    assert event == {"type": "progress", "phase": "rendering"}
    finish.set()
    assert (await anext(stream))["kind"] == "video"
    await stream.aclose()


@pytest.mark.asyncio
async def test_disconnect_cancels_video_polling(monkeypatch):
    from deeptutor.services import videogen

    stopped = asyncio.Event()

    async def generate(*args, progress, **kwargs):
        try:
            await progress("submitted")
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(videogen, "generate_video", generate)
    stream = preview.preview_events(catalog("videogen"), "videogen", "p", "edited", "prompt")
    await anext(stream)
    await anext(stream)
    await stream.aclose()
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_preview_failure_redacts_provider_errors(monkeypatch):
    from deeptutor.services import imagegen

    async def generate(*args, **kwargs):
        raise ValueError("secret-key, upstream request body")

    monkeypatch.setattr(imagegen, "generate_image", generate)
    assert (await collect("imagegen"))[-1] == {"type": "error", "code": "failed"}


def test_input_limits_and_non_media_results():
    with pytest.raises(ValueError):
        preview.validate_input("stt", "", "bad!", "audio/wav")
    with pytest.raises(ValueError):
        preview.validate_input("search", " ", "", "")
    with pytest.raises(ValueError):
        preview.media_result(b"<script>", "text/html", "image")
    assert (
        preview.validate_input("stt", "", base64.b64encode(b"sample").decode(), "audio/wav")
        == b"sample"
    )
