import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS

import pytest

from deeptutor.services.llm import factory, metrics, usage_ledger
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core.base import LLMProvider, LLMResponse
from deeptutor.services.session.usage_statistics import aggregate_usage


class Provider(LLMProvider):
    provider_name = "test-provider"

    async def chat(self, **kwargs):
        return LLMResponse(content="answer", usage={"prompt_tokens": 100, "completion_tokens": 20})

    def get_default_model(self):
        return "test-model"


@pytest.mark.asyncio
async def test_factory_records_background_completion_and_stream_without_turn(monkeypatch):
    config = LLMConfig(model="test-model", api_key="test", binding="openai", provider_name="openai")
    monkeypatch.setattr(factory, "get_llm_config", lambda: config)
    monkeypatch.setattr(factory, "get_runtime_provider", lambda _: Provider())
    assert metrics.current_usage.get() is None
    assert await factory.complete("private prompt") == "answer"
    assert "".join([part async for part in factory.stream("private prompt")]) == "answer"
    records = usage_ledger.usage_records(0, 9999999999)
    assert len(records) == 2
    result = aggregate_usage(records, year=datetime.now(timezone.utc).year, timezone="UTC")
    assert result.totals.total_tokens == 240
    assert result.totals.total_calls == 2
    assert result.sessions == 0
    assert result.turns == 2
    assert result.models[0].model == "test-model"
    raw = usage_ledger.ledger_path().read_bytes()
    assert b"private prompt" not in raw
    assert b"answer" not in raw


@pytest.mark.asyncio
async def test_ledger_and_saved_turn_merge_once_with_partial_write_recovery():
    collector = metrics.TurnUsage(session_id="session", turn_id="turn", source="mastery_path")
    token = metrics.current_usage.set(collector)
    try:
        meter = metrics.CallMeasurement(model="tutor")
        meter.finish(NS(usage={"prompt_tokens": 100, "completion_tokens": 20}))
        meter.finish()  # stream close/finalization cannot count a call again
    finally:
        metrics.current_usage.reset(token)
    ledger = usage_ledger.usage_records(0, 9999999999)
    history = [{**ledger[0], "summaries": [collector.summary()]}]
    merged = usage_ledger.merge_records(history, ledger)
    result = aggregate_usage(merged, year=datetime.now(timezone.utc).year, timezone="UTC")
    assert result.totals.total_tokens == 120
    assert result.turns == result.tracked_turns == result.sessions == 1
    # Simulate a persisted snapshot for a second call whose ledger write failed.
    collector.calls.append({**collector.calls[0], "call_id": "unwritten"})
    history[0]["summaries"] = [collector.summary()]
    result = aggregate_usage(
        usage_ledger.merge_records(history, ledger),
        year=datetime.now(timezone.utc).year,
        timezone="UTC",
    )
    assert result.totals.total_tokens == 240
    assert result.totals.total_calls == 2
    assert result.turns == 1
    # Removing the conversation does not remove the durable consumption.
    assert (
        aggregate_usage(
            ledger, year=datetime.now(timezone.utc).year, timezone="UTC"
        ).totals.total_tokens
        == 120
    )


@pytest.mark.asyncio
async def test_owner_is_captured_before_async_work_and_nested_calls_count_once(
    monkeypatch, tmp_path
):
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.multi_user.paths import get_owner_path_service

    monkeypatch.setattr(
        usage_ledger,
        "ledger_path",
        lambda: get_owner_path_service().get_user_root() / "usage.sqlite3",
    )

    async def user_call(name):
        user = CurrentUser(name, name, "user", UserScope("user", name, tmp_path / name))
        token = set_current_user(user)
        try:

            async def create(**kwargs):
                await asyncio.sleep(0)
                return await metrics.measure_provider_call(Provider().chat, model=name)

            client = metrics.instrument_client(
                NS(chat=NS(completions=NS(create=create))), model=name
            )
            await client.chat.completions.create()
            return usage_ledger.usage_records(0, 9999999999)
        finally:
            reset_current_user(token)

    alice, bob = await asyncio.gather(user_call("alice"), user_call("bob"))
    assert len(alice) == len(bob) == 1
    assert alice[0]["summaries"][0]["call_details"][0]["model"] == "alice"
    assert bob[0]["summaries"][0]["call_details"][0]["model"] == "bob"


@pytest.mark.asyncio
async def test_interrupted_provider_call_is_recorded_and_propagates():
    async def call(**kwargs):
        await kwargs["on_content_delta"]("partial")
        raise asyncio.CancelledError()

    async def on_delta(_):
        pass

    with pytest.raises(asyncio.CancelledError):
        await metrics.measure_provider_call(call, model="interrupted", on_content_delta=on_delta)
    records = usage_ledger.usage_records(0, 9999999999)
    assert len(records) == 1
    assert records[0]["summaries"][0]["call_details"][0]["status"] == "interrupted"


def test_perplexity_search_records_its_separate_llm_transport(monkeypatch):
    from deeptutor.services.search.providers.perplexity import PerplexityProvider

    provider = PerplexityProvider(api_key="test")
    provider._client = NS(
        chat=NS(
            completions=NS(
                create=lambda **kwargs: NS(
                    model="sonar",
                    choices=[NS(message=NS(content="answer"), finish_reason="stop")],
                    usage=NS(prompt_tokens=80, completion_tokens=10, total_tokens=90),
                )
            )
        )
    )
    provider.search("test question")
    records = usage_ledger.usage_records(0, 9999999999)
    assert records[0]["summaries"][0]["total_tokens"] == 90
    assert records[0]["summaries"][0]["call_details"][0]["provider"] == "perplexity"


def test_cross_year_calls_keep_their_original_date_without_snapshot_duplicates():
    call = {
        "call_id": "new-year",
        "model": "m",
        "total_tokens": 100,
        "prompt_tokens": 90,
        "completion_tokens": 10,
        "estimated": False,
    }
    stamp = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    usage_ledger.record_call(usage_ledger.ledger_path(), call, started_at=stamp, turn_id="turn")
    collector = metrics.TurnUsage()
    collector.calls = [call]
    history = [{"created_at": start + 60, "turn_id": "turn", "summaries": [collector.summary()]}]
    result = aggregate_usage(
        usage_ledger.combined_usage_records(history, start, start + 86400),
        year=2026,
        timezone="UTC",
    )
    assert result.totals.total_tokens == 0
    previous = usage_ledger.combined_usage_records([], stamp - 60, start)
    assert aggregate_usage(previous, year=2025, timezone="UTC").totals.total_tokens == 100


def test_doubao_search_records_response_api_tokens(monkeypatch):
    from deeptutor.services.search.providers.doubao import DoubaoProvider

    monkeypatch.setattr(
        "deeptutor.services.search.providers.doubao.requests.post",
        lambda *a, **kw: NS(
            status_code=200,
            json=lambda: {"usage": {"input_tokens": 75, "output_tokens": 25}, "output": []},
        ),
    )
    DoubaoProvider(api_key="test").search("query", model="doubao-test")
    record = usage_ledger.usage_records(0, 9999999999)[0]
    assert record["summaries"][0]["total_tokens"] == 100
    assert record["summaries"][0]["call_details"][0]["model"] == "doubao-test"
