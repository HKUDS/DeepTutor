"""xAI Grok Imagine video-generation provider tests."""

from __future__ import annotations

import json

import httpx
import pytest

from deeptutor.services.config.provider_runtime import VIDEOGEN_PROVIDERS
from deeptutor.services.videogen.adapters.xai import XaiVideogenAdapter
from deeptutor.services.videogen.config import VideogenConfig


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )


def test_xai_videogen_spec() -> None:
    spec = VIDEOGEN_PROVIDERS["xai"]

    assert spec.default_model == "grok-imagine-video-1.5"
    assert spec.default_api_base == "https://api.x.ai/v1"
    assert spec.adapter == "xai"


@pytest.mark.asyncio
async def test_xai_videogen_submit_poll_download(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/videos/generations":
            assert json.loads(request.content) == {
                "model": "grok-imagine-video-1.5",
                "prompt": "Un chat",
                "duration": 8,
                "aspect_ratio": "16:9",
                "resolution": "720p",
            }
            return httpx.Response(200, json={"request_id": "req_1"})
        if request.url.path == "/v1/videos/req_1":
            return httpx.Response(
                200,
                json={"status": "done", "video": {"url": "https://video.example/v.mp4"}},
            )
        if request.url.host == "video.example":
            return httpx.Response(200, content=b"MP4", headers={"content-type": "video/mp4"})
        raise AssertionError(f"unexpected request: {request.url}")

    transport(monkeypatch, handle)
    config = VideogenConfig(
        model="grok-imagine-video-1.5",
        api_key="test-key",
        base_url="https://api.x.ai/v1",
        duration="8",
        aspect_ratio="16:9",
        resolution="720p",
        poll_interval=0,
        poll_timeout=5,
    )

    video, content_type = await XaiVideogenAdapter().generate("Un chat", config)

    assert video == b"MP4"
    assert content_type == "video/mp4"
    assert calls == [
        ("POST", "/v1/videos/generations"),
        ("GET", "/v1/videos/req_1"),
        ("GET", "/v.mp4"),
    ]
