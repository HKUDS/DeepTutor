import asyncio
from types import SimpleNamespace as NS

import pytest

from deeptutor.services.llm import metrics
from deeptutor.services.llm.usage_frame import usage_breakdown


def test_provider_cache_dialects():
    assert usage_breakdown(
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 70,
            "cache_creation_input_tokens": 20,
        }
    ) == {
        "prompt_tokens": 100,
        "completion_tokens": 5,
        "total_tokens": 105,
        "cache_read_input_tokens": 70,
        "cache_creation_input_tokens": 20,
    }
    for payload in (
        {
            "prompt_tokens": 100,
            "completion_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 70},
        },
        {"input_tokens": 100, "output_tokens": 5, "input_tokens_details": NS(cached_tokens=70)},
        {"prompt_tokens": 100, "completion_tokens": 5, "prompt_cache_hit_tokens": 70},
    ):
        result = usage_breakdown(payload)
        assert result["cache_read_input_tokens"] == 70
        assert result["prompt_tokens"] == 100
    assert "cache_read_input_tokens" not in usage_breakdown({"prompt_tokens": 100})
    assert (
        usage_breakdown({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 0}})[
            "cache_read_input_tokens"
        ]
        == 0
    )


@pytest.mark.asyncio
async def test_stream_records_once_and_ignores_usage_trailer_for_generation(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(metrics.time, "perf_counter", lambda: now[0])
    collector = metrics.TurnUsage()
    token = metrics.current_usage.set(collector)
    frame = {
        "prompt_tokens": 100,
        "completion_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 75},
    }

    async def chunks():
        now[0] = 2
        yield NS(choices=[NS(delta=NS(content="hello"))], usage=None)
        now[0] = 4
        yield NS(choices=[NS(delta=NS(content="world"))], usage=frame)
        now[0] = 8
        yield NS(choices=[], usage=frame)

    async def create(**kwargs):
        return chunks()

    client = NS(chat=NS(completions=NS(create=create)))
    metrics.instrument_client(client, model="m", provider="p")
    try:
        stream = await client.chat.completions.create(stream=True)
        async for _ in stream:
            pass
        await stream.close()
    finally:
        metrics.current_usage.reset(token)
    summary = collector.summary()
    assert summary["total_calls"] == 1
    assert summary["ttft_seconds"] == 2
    assert summary["tokens_per_second"] == 20
    assert summary["cache_hit_rate"] == 0.75
    assert summary["duration_seconds"] == 8


@pytest.mark.asyncio
async def test_collectors_are_isolated_and_nested_instrumentation_does_not_duplicate():
    async def turn(model):
        collector = metrics.TurnUsage()
        token = metrics.current_usage.set(collector)

        async def provider(**kwargs):
            await asyncio.sleep(0)
            return NS(usage={"prompt_tokens": 100, "completion_tokens": 10}, finish_reason="stop")

        async def create(**kwargs):
            return await metrics.measure_provider_call(provider, model=model)

        client = NS(chat=NS(completions=NS(create=create)))
        metrics.instrument_client(client, model=model)
        try:
            await client.chat.completions.create()
        finally:
            metrics.current_usage.reset(token)
        return collector.summary()

    a, b = await asyncio.gather(turn("a"), turn("b"))
    assert a["total_calls"] == b["total_calls"] == 1
    assert a["call_details"][0]["model"] == "a"
    assert b["call_details"][0]["model"] == "b"
    assert a["cache_hit_rate"] is None


def test_cache_rate_is_token_weighted_and_missing_reports_are_not_zero():
    collector = metrics.TurnUsage()
    token = metrics.current_usage.set(collector)
    try:
        for count, read in ((100, 80), (900, 90), (500, None)):
            frame = {"prompt_tokens": count, "completion_tokens": 10}
            if read is not None:
                frame["cache_read_input_tokens"] = read
            metrics.CallMeasurement().finish(NS(usage=frame))
    finally:
        metrics.current_usage.reset(token)
    summary = collector.summary()
    assert summary["cache_hit_rate"] == 0.17
    assert summary["cache_reported_calls"] == 2
    assert summary["ttft_seconds"] is None
    assert summary["tokens_per_second"] is None


def test_cache_only_anthropic_usage_and_malformed_counts():
    assert (
        usage_breakdown({"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 100})[
            "total_tokens"
        ]
        == 100
    )
    assert usage_breakdown({"prompt_tokens": float("inf")}) == {}
