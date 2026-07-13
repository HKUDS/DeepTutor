"""Stage-2 image fallback gating in ``provider_core.base.LLMProvider``.

The factory passes ``allow_image_fallback = not supports_vision(...)``. When
True (model not in the known-vision allowlist) a non-transient failure that
carried images is retried text-only; when False (known vision-capable) the
images are kept and the real error surfaces.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.multimodal import has_image_parts
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse


def _image_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            ],
        }
    ]


class _ScriptedProvider(LLMProvider):
    """Returns queued responses and records whether each call carried images."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        super().__init__()
        self._responses = list(responses)
        self.calls_had_image: list[bool] = []

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls_had_image.append(has_image_parts(messages))
        return self._responses.pop(0)

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_strips_images_and_retries_when_fallback_allowed() -> None:
    provider = _ScriptedProvider(
        [
            LLMResponse(content="this model does not support images", finish_reason="error"),
            LLMResponse(content="ok", finish_reason="stop"),
        ]
    )
    messages = _image_messages()

    resp = await provider.chat_with_retry(
        messages=messages, model="m", retry_delays=(), allow_image_fallback=True
    )

    assert resp.content == "ok"
    # First attempt carried images; the retry was text-only.
    assert provider.calls_had_image == [True, False]
    # Success persists: the shared message list no longer carries images.
    assert has_image_parts(messages) is False


@pytest.mark.asyncio
async def test_keeps_images_and_surfaces_error_when_fallback_disabled() -> None:
    provider = _ScriptedProvider([LLMResponse(content="bad request (400)", finish_reason="error")])
    messages = _image_messages()

    resp = await provider.chat_with_retry(
        messages=messages, model="gpt-4o", retry_delays=(), allow_image_fallback=False
    )

    assert resp.finish_reason == "error"
    # Exactly one call — no strip-and-retry — and images are preserved.
    assert provider.calls_had_image == [True]
    assert has_image_parts(messages) is True
