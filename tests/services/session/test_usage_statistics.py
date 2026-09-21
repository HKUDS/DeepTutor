from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.usage_statistics import aggregate_usage, summaries_from_events


def summary(prompt=100, cached=80, output=20, model="glm-test", ttft=2):
    return {
        "total_tokens": prompt + output,
        "prompt_tokens": prompt,
        "completion_tokens": output,
        "total_calls": 1,
        "cache_read_input_tokens": cached,
        "cache_input_tokens": prompt,
        "cache_reported_calls": 1,
        "ttft_seconds": ttft,
        "ttft_calls": 1,
        "generation_seconds": 2,
        "timed_completion_tokens": output,
        "call_details": [
            {
                "provider": "zhipu",
                "model": model,
                "total_tokens": prompt + output,
                "prompt_tokens": prompt,
                "completion_tokens": output,
                "cache_read_input_tokens": cached,
                "ttft_seconds": ttft,
                "generation_seconds": 2,
            }
        ],
    }


def events(value):
    return [
        {"type": "result", "metadata": {"metadata": {"usage_summary": value}}},
        {"type": "done", "metadata": {"usage_summary": value}},
    ]


def test_rollups_deduplicate_snapshots_and_weight_measurements():
    records = [
        {
            "session_id": "s",
            "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp(),
            "summaries": summaries_from_events(events(value)),
        }
        for value in (summary(), summary(900, 90, 60, ttft=4))
    ]
    result = aggregate_usage(records, year=2026, timezone="UTC")
    assert result.totals.total_tokens == 1080
    assert result.totals.cache_hit_rate == 0.17
    assert result.totals.ttft_seconds == 3
    assert result.totals.tokens_per_second == 20
    assert result.models[0].total_tokens == 1080
    assert result.models[0].cache_hit_rate == 0.17
    assert result.active_days == 1
    assert result.days[1].turns == 2
    assert result.sessions == 1
    assert result.tracked_turns == 2


def test_calendar_uses_requested_timezone_and_includes_leap_day():
    records = [
        {
            "session_id": "s",
            "created_at": datetime(2024, 1, 1, 1, tzinfo=timezone.utc).timestamp(),
            "summaries": [],
        }
    ]
    local = aggregate_usage(records, year=2023, timezone="America/New_York")
    assert local.days[-1].turns == 1
    assert local.tracked_turns == 0
    assert aggregate_usage(records, year=2024, timezone="America/New_York").turns == 0
    assert len(aggregate_usage([], year=2024, timezone="UTC").days) == 366


def test_old_usage_is_unattributed_and_unknown_cache_stays_unknown():
    legacy = {"total_tokens": 120, "prompt_tokens": 100, "completion_tokens": 20, "total_calls": 1}
    extracted = summaries_from_events(
        [{"type": "result", "metadata": {"metadata": {"cost_summary": legacy}}}]
    )
    result = aggregate_usage(
        [{"session_id": "s", "created_at": 1767312000, "summaries": extracted}],
        year=2026,
        timezone="UTC",
    )
    assert result.models[0].model == ""
    assert result.totals.cache_hit_rate is None
    assert result.totals.ttft_seconds is None


@pytest.mark.asyncio
async def test_sqlite_reads_saved_usage_and_activity_without_transcripts(tmp_path):
    store = SQLiteSessionStore(tmp_path / "usage.db")
    session = await store.create_session()
    await store.add_message(session["id"], "user", "private prompt")
    await store.add_message(session["id"], "assistant", "private reply", events=events(summary()))
    await store.add_message(session["id"], "assistant", "older reply")
    records = await store.usage_records(0, 9999999999)
    assert len(records) == 2
    assert len(records[0]["summaries"]) == 1
    assert records[1]["summaries"] == []
    assert "private" not in str(records)
    # Current runtime leaves message events empty and persists the trace separately.
    native = await store.add_message(session["id"], "assistant", "native reply")
    turn = await store.create_turn(session["id"])
    await store.link_turn_message(turn["id"], native)
    await store.append_turn_events(turn["id"], events(summary(prompt=700)))
    records = await store.usage_records(0, 9999999999)
    assert len(records) == 3
    assert records[-1]["summaries"][0]["total_tokens"] == 720
    # A migrated row may contain both sources; the canonical DONE wins once.
    with store._connect() as conn:
        import json

        conn.execute(
            "UPDATE messages SET events_json = ? WHERE id = ?",
            (json.dumps(events(summary())), native),
        )
    records = await store.usage_records(0, 9999999999)
    assert records[-1]["summaries"][0]["total_tokens"] == 720
    assert len(records[-1]["summaries"]) == 1
    other = SQLiteSessionStore(tmp_path / "other.db")
    assert await other.usage_records(0, 9999999999) == []


@pytest.mark.asyncio
async def test_pocketbase_scopes_owner_and_paginates(monkeypatch):
    from deeptutor.services.session import pocketbase_store as module

    captured = []

    class Collection:
        def __init__(self, name):
            self.name = name

        def get_full_list(self, query_params):
            assert query_params["filter"] == module._workspace_filter('user_id="alice"')
            return [NS(user_id="alice", session_id="own"), NS(user_id="bob", session_id="foreign")]

        def get_list(self, page, limit, query_params):
            captured.append((self.name, query_params["filter"]))
            if self.name == "messages":
                rows = [
                    NS(
                        id=f"msg_{i}",
                        session_id="own",
                        msg_created_at=1767312000,
                        events_json=events(summary()),
                    )
                    for i in (range(200) if page == 1 else [200])
                ]
                if page == 1:
                    rows.append(NS(session_id="foreign"))
                return NS(items=rows, total_items=201)
            if self.name == "turns":
                rows = []
                if 'assistant_message_id="msg_0"' in query_params["filter"]:
                    rows = [
                        NS(turn_id="native_turn", session_id="own", assistant_message_id="msg_0"),
                        NS(
                            turn_id="foreign_turn",
                            session_id="foreign",
                            assistant_message_id="msg_0",
                        ),
                    ]
                return NS(items=rows, total_items=len(rows))
            assert self.name == "turn_events"
            assert 'turn_id="native_turn"' in query_params["filter"]
            assert "foreign_turn" not in query_params["filter"]
            return NS(
                items=[
                    NS(turn_id="native_turn", type=e["type"], metadata_json=e["metadata"])
                    for e in events(summary(prompt=700))
                ],
                total_items=2,
            )

    monkeypatch.setattr(module, "_current_user_id", lambda: "alice")
    monkeypatch.setattr(module, "_pb", lambda: NS(collection=Collection))
    records = await module.PocketBaseSessionStore().usage_records(0, 9999999999)
    assert len(records) == 201
    assert records[0]["summaries"][0]["total_tokens"] == 720
    assert len(records[0]["summaries"]) == 1
    assert records[1]["summaries"][0]["total_tokens"] == 120
    assert all("foreign" not in query for _, query in captured)
    assert all('session_id="own"' in query for name, query in captured if name != "turn_events")


@pytest.mark.asyncio
async def test_usage_endpoint_validates_timezone_and_uses_active_store(monkeypatch):
    from fastapi import HTTPException

    from deeptutor.api.routers.settings import get_usage_statistics

    store = NS(usage_records=AsyncMock(return_value=[]))
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: store)
    with pytest.raises(HTTPException):
        await get_usage_statistics(year=2026, timezone="not/a/timezone")
    assert not store.usage_records.called
    result = await get_usage_statistics(year=2026, timezone="Asia/Shanghai")
    assert result.year == 2026
    assert (
        store.usage_records.call_args.args[0]
        == datetime(2025, 12, 31, 16, tzinfo=timezone.utc).timestamp()
    )


def test_recovers_legacy_models_from_llm_traces_but_not_search_tool_models():
    legacy = {"total_tokens": 120, "prompt_tokens": 100, "completion_tokens": 20, "total_calls": 1}
    trace = [
        {
            "type": "thinking",
            "metadata": {
                "trace_kind": "call_status",
                "call_kind": "llm_generation",
                "model": "historical-model",
            },
        },
        {"type": "tool_result", "metadata": {"tool_metadata": {"model": "sonar"}}},
        {"type": "result", "metadata": {"metadata": {"cost_summary": legacy}}},
    ]
    recovered = summaries_from_events(trace)
    assert recovered[0]["model"] == "historical-model"
    result = aggregate_usage(
        [{"created_at": 1767312000, "summaries": recovered}], year=2026, timezone="UTC"
    )
    assert result.models[0].model == "historical-model"
    assert result.models[0].total_tokens == 120
    # Ambiguous multi-model turns must not be assigned entirely to either model.
    trace.insert(
        0, {"type": "thinking", "metadata": {"trace_kind": "call_status", "model": "other-model"}}
    )
    assert not summaries_from_events(trace)[0].get("model")


def test_recovers_context_budget_and_original_per_model_report(tmp_path, monkeypatch):
    import json

    from deeptutor.multi_user import paths

    root = tmp_path / "account"
    root.mkdir()
    monkeypatch.setattr(paths, "get_current_path_service", lambda: NS(get_user_root=lambda: root))
    summary = {"total_tokens": 120, "total_calls": 2}
    metadata = {"cost_summary": summary, "context_budget": {"model": "original-model"}}
    event = {"type": "result", "metadata": {"metadata": metadata}}
    assert summaries_from_events([event])[0]["model"] == "original-model"
    nested = {
        "type": "result",
        "metadata": {
            "metadata": {
                "cost_summary": summary,
                "loop": {"metadata": {"context_budget": {"model": "nested-model"}}},
            }
        },
    }
    assert summaries_from_events([nested])[0]["model"] == "nested-model"
    metadata["output_dir"] = str(root)
    report = {
        "summary": {
            "total_tokens": 120,
            "by_model": {
                "first": {
                    "total_tokens": 70,
                    "prompt_tokens": 60,
                    "completion_tokens": 10,
                    "calls": 1,
                },
                "second": {
                    "total_tokens": 50,
                    "prompt_tokens": 40,
                    "completion_tokens": 10,
                    "calls": 1,
                },
            },
        }
    }
    (root / "cost_report.json").write_text(json.dumps(report))
    recovered = summaries_from_events([event])
    assert recovered[0]["prompt_tokens"] == 100
    result = aggregate_usage(
        [{"created_at": 1767312000, "summaries": recovered}], year=2026, timezone="UTC"
    )
    assert {model.model for model in result.models} == {"first", "second"}
    assert sum(model.total_tokens for model in result.models) == result.totals.total_tokens
    # Historical artifacts may not escape this account's storage root.
    metadata["output_dir"] = str(tmp_path)
    (tmp_path / "cost_report.json").write_text(json.dumps(report))
    assert not summaries_from_events([event])[0].get("by_model")
