"""Tests for the image/video generation service layer.

Covers the shared HTTP helpers, the OpenAI-compatible imagegen adapter (both
``b64_json`` and ``url`` response shapes), the async-task videogen adapter
(submit → poll → download, plus failure + payload shaping), catalog-driven
config resolution, and the public facades.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from deeptutor.services.config.provider_runtime import (
    resolve_imagegen_runtime_config,
    resolve_videogen_runtime_config,
)
from deeptutor.services.generation_http import (
    GenerationProviderError,
    build_auth_headers,
    join_api_path,
)
from deeptutor.services.imagegen import generate_image
from deeptutor.services.imagegen.adapters.chat_completions import ChatCompletionsImagegenAdapter
from deeptutor.services.imagegen.adapters.openai_compat import OpenAICompatImagegenAdapter
from deeptutor.services.imagegen.config import ImagegenConfig
from deeptutor.services.videogen import generate_video, probe_video
from deeptutor.services.videogen.adapters.async_task import AsyncTaskVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


def _patch_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: Any = None,
    get: Any = None,
) -> dict[str, Any]:
    """Patch ``httpx.AsyncClient`` post/get with url-routed fakes."""
    captured: dict[str, Any] = {"posts": [], "gets": []}

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["posts"].append(
            {"url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")}
        )
        resp = post(url, kwargs) if callable(post) else post
        resp.request = httpx.Request("POST", url)
        return resp

    async def fake_get(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        captured["gets"].append({"url": url})
        resp = get(url, kwargs) if callable(get) else get
        resp.request = httpx.Request("GET", url)
        return resp

    if post is not None:
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    if get is not None:
        monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return captured


# ── shared HTTP helpers ─────────────────────────────────────────────────────


def test_build_auth_headers_styles() -> None:
    assert build_auth_headers("bearer", "k") == {"Authorization": "Bearer k"}
    assert build_auth_headers("api_key_header", "k") == {"api-key": "k"}
    assert build_auth_headers("bearer", "") == {}


def test_join_api_path_appends_and_preserves_full_url() -> None:
    assert (
        join_api_path("https://api.openai.com/v1", "images/generations")
        == "https://api.openai.com/v1/images/generations"
    )
    full = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    assert join_api_path(full, "images/generations") == full


# ── imagegen adapter ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_imagegen_adapter_b64_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = base64.b64encode(b"PNGDATA").decode("ascii")
    resp = httpx.Response(200, json={"data": [{"b64_json": payload}]})
    captured = _patch_http(monkeypatch, post=resp)
    config = ImagegenConfig(
        model="gpt-image-1",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        size="1024x1024",
    )
    images = await OpenAICompatImagegenAdapter().generate("a cat", config, n=2)
    assert images == [(b"PNGDATA", "image/png")]
    post = captured["posts"][0]
    assert post["url"] == "https://api.openai.com/v1/images/generations"
    assert post["json"] == {"model": "gpt-image-1", "prompt": "a cat", "n": 2, "size": "1024x1024"}
    assert post["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_imagegen_adapter_url_is_downloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    post_resp = httpx.Response(200, json={"data": [{"url": "https://cdn/x.png"}]})
    get_resp = httpx.Response(200, content=b"DOWNLOADED", headers={"content-type": "image/png"})
    captured = _patch_http(monkeypatch, post=post_resp, get=get_resp)
    config = ImagegenConfig(model="seedream", base_url="https://ark/api/v3", api_key="k")
    images = await OpenAICompatImagegenAdapter().generate("dog", config)
    assert images == [(b"DOWNLOADED", "image/png")]
    assert captured["gets"][0]["url"] == "https://cdn/x.png"


@pytest.mark.asyncio
async def test_imagegen_chat_completions_adapter_data_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    data_uri = "data:image/png;base64," + base64.b64encode(b"PNGBYTES").decode("ascii")
    resp = httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": "here", "images": [{"image_url": {"url": data_uri}}]}}
            ]
        },
    )
    captured = _patch_http(monkeypatch, post=resp)
    config = ImagegenConfig(
        model="google/gemini-2.5-flash-image-preview",
        adapter="chat_completions",
        base_url="https://openrouter.ai/api/v1",
        api_key="or-key",
    )
    images = await ChatCompletionsImagegenAdapter().generate("a fox", config)
    assert images == [(b"PNGBYTES", "image/png")]
    post = captured["posts"][0]
    assert post["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert post["json"]["modalities"] == ["image", "text"]
    assert post["json"]["messages"][0]["content"] == "a fox"


@pytest.mark.asyncio
async def test_imagegen_adapter_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, post=httpx.Response(404, text="not activated"))
    config = ImagegenConfig(model="m", base_url="https://x/v1", api_key="k")
    with pytest.raises(GenerationProviderError, match="404"):
        await OpenAICompatImagegenAdapter().generate("x", config)


# ── videogen adapter ────────────────────────────────────────────────────────


def test_videogen_submit_payload_seedance_shape() -> None:
    config = VideogenConfig(
        model="seedance",
        base_url="https://ark/api/v3",
        aspect_ratio="16:9",
        resolution="720p",
        duration="5",
    )
    payload = AsyncTaskVideogenAdapter._build_submit_payload("a wave", config)
    assert payload["model"] == "seedance"
    text = payload["content"][0]["text"]
    assert text.startswith("a wave")
    assert "--ratio 16:9" in text and "--resolution 720p" in text and "--duration 5" in text


@pytest.mark.asyncio
async def test_videogen_adapter_submit_poll_download(monkeypatch: pytest.MonkeyPatch) -> None:
    submit = httpx.Response(200, json={"id": "task-1"})

    def get_router(url: str, _kwargs: Any) -> httpx.Response:
        if url.endswith("/contents/generations/tasks/task-1"):
            return httpx.Response(
                200, json={"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}}
            )
        return httpx.Response(200, content=b"MP4DATA", headers={"content-type": "video/mp4"})

    _patch_http(monkeypatch, post=submit, get=get_router)
    config = VideogenConfig(
        model="seedance",
        base_url="https://ark/api/v3",
        api_key="k",
        poll_interval=0.0,
    )
    video, content_type = await AsyncTaskVideogenAdapter().generate("a wave", config)
    assert video == b"MP4DATA"
    assert content_type == "video/mp4"


@pytest.mark.asyncio
async def test_videogen_adapter_raises_on_failed_task(monkeypatch: pytest.MonkeyPatch) -> None:
    submit = httpx.Response(200, json={"id": "t2"})
    fail = httpx.Response(200, json={"status": "failed", "error": {"message": "content blocked"}})
    _patch_http(monkeypatch, post=submit, get=fail)
    config = VideogenConfig(model="m", base_url="https://x/v3", api_key="k", poll_interval=0.0)
    with pytest.raises(GenerationProviderError, match="content blocked"):
        await AsyncTaskVideogenAdapter().generate("x", config)


# ── catalog resolution ──────────────────────────────────────────────────────


def _media_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "imagegen": {
                "active_profile_id": "p1",
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "p1",
                        "binding": "volcengine",
                        "base_url": "",
                        "api_key": "ark-key",
                        "models": [{"id": "m1", "model": "doubao-seedream-3", "size": "1024x1024"}],
                    }
                ],
            },
            "videogen": {
                "active_profile_id": "p2",
                "active_model_id": "m2",
                "profiles": [
                    {
                        "id": "p2",
                        "binding": "volcengine",
                        "base_url": "",
                        "api_key": "ark-key",
                        "models": [
                            {"id": "m2", "model": "doubao-seedance-1", "aspect_ratio": "9:16"}
                        ],
                    }
                ],
            },
        },
    }


def test_resolve_imagegen_config_fills_provider_default_base() -> None:
    cfg = resolve_imagegen_runtime_config(catalog=_media_catalog())
    assert cfg.model == "doubao-seedream-3"
    assert cfg.provider_name == "volcengine"
    assert cfg.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert cfg.size == "1024x1024"
    assert cfg.api_key == "ark-key"


def test_resolve_imagegen_openrouter_uses_chat_adapter() -> None:
    catalog = {
        "version": 1,
        "services": {
            "imagegen": {
                "active_profile_id": "p",
                "active_model_id": "m",
                "profiles": [
                    {
                        "id": "p",
                        "binding": "openrouter",
                        "base_url": "",
                        "api_key": "or-key",
                        "models": [{"id": "m", "model": "black-forest-labs/flux.2-pro"}],
                    }
                ],
            }
        },
    }
    cfg = resolve_imagegen_runtime_config(catalog=catalog)
    assert cfg.provider_name == "openrouter"
    assert cfg.adapter == "chat_completions"
    assert cfg.base_url == "https://openrouter.ai/api/v1"


def test_resolve_videogen_config_uses_async_task_adapter() -> None:
    cfg = resolve_videogen_runtime_config(catalog=_media_catalog())
    assert cfg.provider_name == "volcengine"
    assert cfg.adapter == "async_task"
    assert cfg.aspect_ratio == "9:16"


def test_resolve_imagegen_config_raises_without_model() -> None:
    catalog = {"version": 1, "services": {"imagegen": {"profiles": []}}}
    with pytest.raises(ValueError, match="No active image-generation model"):
        resolve_imagegen_runtime_config(catalog=catalog)


# ── facades ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_image_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = base64.b64encode(b"IMG").decode("ascii")
    captured = _patch_http(
        monkeypatch, post=httpx.Response(200, json={"data": [{"b64_json": payload}]})
    )
    images = await generate_image("a tree", catalog=_media_catalog(), size="512x512")
    assert images == [(b"IMG", "image/png")]
    assert captured["posts"][0]["json"]["size"] == "512x512"


@pytest.mark.asyncio
async def test_imagegen_tool_saves_public_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool must write generated bytes to a path /api/outputs can serve.

    Regression: media landed under ``<task>/media`` which was not on the
    public-output allowlist, so artifacts collected empty ("no saved files").
    """
    import shutil

    import deeptutor.services.imagegen as imagegen_mod
    from deeptutor.services.path_service import get_path_service
    from deeptutor.tools.media_gen_tool import ImagegenTool

    async def fake_generate_image(prompt: str, **_kwargs: Any) -> list[tuple[bytes, str]]:
        return [(b"\x89PNG\r\n\x1a\nfake", "image/png")]

    monkeypatch.setattr(imagegen_mod, "generate_image", fake_generate_image)

    workspace = get_path_service().get_task_workspace("chat", "test_imagegen_tool") / "media"
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        result = await ImagegenTool().execute(prompt="a cat", _workspace_dir=str(workspace))
        assert result.success, result.content
        artifacts = result.metadata.get("artifacts") or []
        assert artifacts, "tool produced no artifacts"
        assert artifacts[0]["url"].startswith("/api/outputs/")
        assert artifacts[0]["mime_type"] == "image/png"
    finally:
        shutil.rmtree(
            get_path_service().get_task_workspace("chat", "test_imagegen_tool"),
            ignore_errors=True,
        )


@pytest.mark.asyncio
async def test_imagegen_tool_without_injected_workspace_uses_public_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct tool calls still need a real public workspace, not a phantom agent dir."""
    import shutil

    import deeptutor.services.imagegen as imagegen_mod
    from deeptutor.services.path_service import get_path_service
    from deeptutor.tools.media_gen_tool import ImagegenTool

    async def fake_generate_image(prompt: str, **_kwargs: Any) -> list[tuple[bytes, str]]:
        return [(b"\x89PNG\r\n\x1a\nfake", "image/png")]

    monkeypatch.setattr(imagegen_mod, "generate_image", fake_generate_image)

    task_root = get_path_service().get_task_workspace("chat", "media_gen")
    try:
        result = await ImagegenTool().execute(prompt="fallback image")
        assert result.success, result.content
        artifacts = result.metadata.get("artifacts") or []
        assert artifacts, "tool produced no artifacts"
        assert artifacts[0]["url"].startswith("/api/outputs/")
        assert "/workspace/chat/chat/media_gen/media/" in artifacts[0]["url"]
    finally:
        shutil.rmtree(task_root, ignore_errors=True)


@pytest.mark.asyncio
async def test_videogen_tool_forwards_progress_and_saves(monkeypatch: pytest.MonkeyPatch) -> None:
    """videogen must forward progress to its event_sink (resets the chat idle
    watchdog during long renders) and save the video to a public path."""
    import shutil

    from deeptutor.services.path_service import get_path_service
    import deeptutor.services.videogen as videogen_mod
    from deeptutor.tools.media_gen_tool import VideogenTool

    async def fake_generate_video(
        prompt: str, *, progress: Any = None, **_kwargs: Any
    ) -> tuple[bytes, str]:
        if progress is not None:
            await progress("Still rendering video…")
        return (b"MP4DATA", "video/mp4")

    monkeypatch.setattr(videogen_mod, "generate_video", fake_generate_video)

    events: list[tuple[str, str]] = []

    async def event_sink(event_type: str, message: str = "", metadata: Any = None) -> None:
        events.append((event_type, message))

    workspace = get_path_service().get_task_workspace("chat", "test_videogen_tool") / "media"
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        result = await VideogenTool().execute(
            prompt="an ocean wave",
            _workspace_dir=str(workspace),
            event_sink=event_sink,
        )
        assert result.success, result.content
        assert any("rendering" in message for _, message in events), events
        artifacts = result.metadata.get("artifacts") or []
        assert artifacts, "tool produced no artifacts"
        assert artifacts[0]["url"].startswith("/api/outputs/")
        assert artifacts[0]["mime_type"] == "video/mp4"
    finally:
        shutil.rmtree(
            get_path_service().get_task_workspace("chat", "test_videogen_tool"),
            ignore_errors=True,
        )


@pytest.mark.asyncio
async def test_generate_image_facade_rejects_empty_prompt() -> None:
    with pytest.raises(GenerationProviderError, match="empty prompt"):
        await generate_image("   ", catalog=_media_catalog())


@pytest.mark.asyncio
async def test_probe_video_returns_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_http(monkeypatch, post=httpx.Response(200, json={"id": "probe-1"}))
    task_id = await probe_video("test clip", catalog=_media_catalog())
    assert task_id == "probe-1"
    # Probe submits only — no polling GET.
    assert captured["gets"] == []


@pytest.mark.asyncio
async def test_generate_video_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    submit = httpx.Response(200, json={"id": "task-9"})

    def get_router(url: str, _kwargs: Any) -> httpx.Response:
        if "tasks/task-9" in url:
            return httpx.Response(
                200, json={"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"}}
            )
        return httpx.Response(200, content=b"VID", headers={"content-type": "video/mp4"})

    _patch_http(monkeypatch, post=submit, get=get_router)
    # Default poll_interval would sleep, but the first poll succeeds so no sleep.
    video, content_type = await generate_video("ocean", catalog=_media_catalog())
    assert video == b"VID"
    assert content_type == "video/mp4"
