"""Tests for OpenRouter imagegen modality fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from deeptutor.services.imagegen.adapters.chat_completions import (
    ChatCompletionsImagegenAdapter,
)
from deeptutor.services.imagegen.config import ImagegenConfig


def _config() -> ImagegenConfig:
    return ImagegenConfig(
        provider_name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        model="bytedance-seed/seedream-5-0-lite",
        adapter="chat_completions",
    )


def _resp(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status_code=status, json=body, request=httpx.Request("POST", "https://x"))


class TestModalitiesFallback:
    @pytest.mark.asyncio
    async def test_retries_with_image_only_on_modality_404(self):
        data_uri = "data:image/png;base64,aGVsbG8="
        success_body = {
            "choices": [
                {"message": {"images": [{"type": "image_url", "image_url": {"url": data_uri}}]}}
            ]
        }
        responses = [
            _resp(
                404,
                {
                    "error": {
                        "message": "No endpoints found that support the requested output modalities: image, text"
                    }
                },
            ),
            _resp(200, success_body),
        ]
        adapter = ChatCompletionsImagegenAdapter()

        calls: list[dict] = []

        async def fake_post(url, *, headers, json):
            calls.append(json)
            return responses[len(calls) - 1]

        with patch.object(httpx.AsyncClient, "post", side_effect=fake_post):
            images = await adapter.generate("draw a cat", _config())

        assert len(images) == 1
        assert calls[0]["modalities"] == ["image", "text"]
        assert calls[1]["modalities"] == ["image"]

    @pytest.mark.asyncio
    async def test_success_with_both_modalities_no_retry(self):
        data_uri = "data:image/png;base64,aGVsbG8="
        success_body = {
            "choices": [
                {"message": {"images": [{"type": "image_url", "image_url": {"url": data_uri}}]}}
            ]
        }
        adapter = ChatCompletionsImagegenAdapter()

        calls: list[dict] = []

        async def fake_post(url, *, headers, json):
            calls.append(json)
            return _resp(200, success_body)

        with patch.object(httpx.AsyncClient, "post", side_effect=fake_post):
            images = await adapter.generate("draw a cat", _config())

        assert len(images) == 1
        assert len(calls) == 1
        assert calls[0]["modalities"] == ["image", "text"]
