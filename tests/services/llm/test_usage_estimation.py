"""Regression: transport encodings must not inflate fallback usage."""

from copy import deepcopy
import json
from types import SimpleNamespace as NS

import pytest

from deeptutor.services.llm import metrics
from deeptutor.services.llm.usage_estimation import (
    ESTIMATED_IMAGE_TOKENS,
    estimate_prompt_tokens,
)


def image_part(payload, dialect):
    if dialect == "chat":
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{payload}", "detail": "high"},
        }
    if dialect == "responses":
        return {"type": "input_image", "image_url": f"data:image/png;base64,{payload}"}
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": payload},
    }


@pytest.mark.parametrize("dialect", ["chat", "responses", "anthropic"])
def test_encoded_size_does_not_change_estimate_or_request(dialect):
    small = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image"},
                image_part("AAAA", dialect),
            ],
        }
    ]
    large = deepcopy(small)
    large[0]["content"][1] = image_part("A" * 8_212_712, dialect)
    before = deepcopy(large)
    assert estimate_prompt_tokens(large) == estimate_prompt_tokens(small)
    assert ESTIMATED_IMAGE_TOKENS <= estimate_prompt_tokens(large) < ESTIMATED_IMAGE_TOKENS + 100
    assert large == before


@pytest.mark.parametrize(
    "messages",
    [
        None,
        "",
        "plain text",
        [
            {"role": "system", "content": "You are a tutor"},
            {"role": "user", "content": [{"type": "text", "text": "Explain 光学"}]},
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "reasoning",
                "tool_calls": [{"function": {"name": "lookup", "arguments": '{"q":"optics"}'}}],
            },
            {"role": "tool", "tool_call_id": "1", "content": "Long source evidence " * 300},
        ],
    ],
)
def test_text_only_estimates_keep_existing_behavior(messages):
    assert estimate_prompt_tokens(messages) == int(len(str(messages or "")) / 3.5)


def test_remote_urls_file_ids_and_repeated_images_are_bounded():
    images = [
        {"type": "image_url", "image_url": {"url": "https://example.invalid/" + "a" * 5000}},
        {"type": "input_image", "file_id": "file-123"},
        {"type": "image", "source": {"type": "url", "url": "https://example.invalid/a.png"}},
    ]
    messages = [{"role": "user", "content": images + images}]
    estimate = estimate_prompt_tokens(messages)
    assert 6 * ESTIMATED_IMAGE_TOKENS <= estimate < 6 * ESTIMATED_IMAGE_TOKENS + 100


def test_image_looking_text_and_tool_arguments_are_not_removed():
    text = json.dumps(image_part("A" * 4000, "chat"))
    messages = [
        {"role": "user", "content": text},
        {"role": "assistant", "tool_calls": [{"function": {"arguments": text}}]},
    ]
    assert estimate_prompt_tokens(messages) == int(len(str(messages)) / 3.5)


@pytest.mark.parametrize("reported", [False, True])
def test_meter_uses_bounded_fallback_but_provider_usage_wins(tmp_path, monkeypatch, reported):
    from deeptutor.services.llm import usage_ledger

    monkeypatch.setattr(usage_ledger, "ledger_path", lambda: tmp_path / "usage.sqlite3")
    collector = metrics.TurnUsage(session_id="synthetic", turn_id="turn")
    token = metrics.current_usage.set(collector)
    messages = [{"role": "user", "content": [image_part("A" * 8_212_712, "chat")]}]
    try:
        meter = metrics.CallMeasurement(messages=messages)
        meter.delta("an image")
        meter.finish(
            NS(usage={"prompt_tokens": 1700, "completion_tokens": 9} if reported else None)
        )
        meter.finish()  # caller cleanup must not duplicate the call
    finally:
        metrics.current_usage.reset(token)
    summary = collector.summary()
    assert summary["total_calls"] == 1
    assert summary["prompt_tokens"] == (1700 if reported else estimate_prompt_tokens(messages))
    assert summary["estimated_calls"] == (0 if reported else 1)
    assert summary["total_tokens"] == summary["prompt_tokens"] + summary["completion_tokens"]
    # The durable ledger must carry the same corrected measurement, never image data.
    import sqlite3

    with sqlite3.connect(tmp_path / "usage.sqlite3") as conn:
        raw = conn.execute("SELECT usage_json FROM llm_calls").fetchone()[0]
    assert json.loads(raw)["prompt_tokens"] == summary["prompt_tokens"]
    assert "data:image" not in raw
    assert len(raw) < 2000


@pytest.mark.asyncio
async def test_stream_without_usage_aggregates_calls_once(tmp_path, monkeypatch):
    from deeptutor.services.llm import usage_ledger

    monkeypatch.setattr(usage_ledger, "ledger_path", lambda: tmp_path / "usage.sqlite3")
    messages = [{"role": "user", "content": [image_part("A" * 5000, "chat")]}]

    async def chunks():
        yield NS(choices=[NS(delta=NS(content="answer"))], usage=None)

    async def create(**kwargs):
        return chunks()

    collector = metrics.TurnUsage()
    token = metrics.current_usage.set(collector)
    client = NS(chat=NS(completions=NS(create=create)))
    metrics.instrument_client(client)
    try:
        for _ in range(2):
            stream = await client.chat.completions.create(messages=messages, stream=True)
            async for _ in stream:
                pass
            await stream.close()
    finally:
        metrics.current_usage.reset(token)
    summary = collector.summary()
    assert summary["total_calls"] == summary["estimated_calls"] == 2
    assert summary["prompt_tokens"] == 2 * estimate_prompt_tokens(messages)
