"""Stage-2 image fallback on the chat agentic path (``run_labeled_step``).

When a model rejects image content and is not in the known-vision allowlist,
the labeled step strips the images in place and retries text-only instead of
hard-failing the turn. Known-vision models keep their images so the real error
propagates.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.core.agentic.labeled_step import run_labeled_step
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.services.llm.multimodal import has_image_parts


def _chunk(content: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=None,
            )
        ],
        usage=None,
    )


async def _async_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ImageRejectingClient:
    """Raises an image-rejection error whenever the request carries images."""

    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._chunks = chunks

        class _Completions:
            def __init__(self, parent: _ImageRejectingClient) -> None:
                self.parent = parent

            async def create(self, **kwargs: Any):
                messages = kwargs.get("messages") or []
                had_image = has_image_parts(messages)
                self.parent.calls.append({"had_image": had_image})
                if had_image:
                    raise RuntimeError("Provider error: this model does not support image input")
                return _async_stream(self.parent._chunks)

        class _Chat:
            def __init__(self, parent: _ImageRejectingClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


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


async def _collect_events(bus: StreamBus, fn) -> tuple[list[Any], Any]:
    events: list[Any] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    try:
        result = await fn()
    finally:
        await bus.close()
        await consumer
    return events, result


@pytest.mark.asyncio
async def test_retries_without_images_for_non_vision_model() -> None:
    client = _ImageRejectingClient([_chunk("``FINISH``\nOK")])
    bus = StreamBus()
    messages = _image_messages()

    async def _run():
        return await run_labeled_step(
            client=client,
            model="moonshot-v1-8k",  # not in the known-vision allowlist
            binding="moonshot",
            messages=messages,
            completion_kwargs={},
            tool_schemas=None,
            allowed_labels=("FINISH", "TOOL", "THINK", "PAUSE"),
            final_labels=frozenset({"FINISH"}),
            tool_label="TOOL",
            stream=bus,
            source="chat",
            stage="responding",
            iter_meta={"label": "Reasoning", "trace_id": "iter-1"},
        )

    events, result = await _collect_events(bus, _run)

    assert result.label == "FINISH"
    assert result.text == "OK"
    # First attempt carried the image; the retry did not.
    assert [c["had_image"] for c in client.calls] == [True, False]
    # The strip persists on the shared message list (no re-send next iteration).
    assert has_image_parts(messages) is False
    warnings = [
        event
        for event in events
        if event.type == StreamEventType.PROGRESS
        and (event.metadata or {}).get("image_fallback") is True
    ]
    assert warnings


@pytest.mark.asyncio
async def test_known_vision_model_propagates_error_without_stripping() -> None:
    client = _ImageRejectingClient([_chunk("``FINISH``\nOK")])
    bus = StreamBus()
    messages = _image_messages()

    async def _run():
        return await run_labeled_step(
            client=client,
            model="gpt-4o",  # known vision-capable → do not degrade
            binding="openai",
            messages=messages,
            completion_kwargs={},
            tool_schemas=None,
            allowed_labels=("FINISH", "TOOL", "THINK", "PAUSE"),
            final_labels=frozenset({"FINISH"}),
            tool_label="TOOL",
            stream=bus,
            source="chat",
            stage="responding",
            iter_meta={"label": "Reasoning", "trace_id": "iter-1"},
        )

    with pytest.raises(RuntimeError, match="image input"):
        await _collect_events(bus, _run)

    # Only one attempt; images were never stripped.
    assert [c["had_image"] for c in client.calls] == [True]
    assert has_image_parts(messages) is True
