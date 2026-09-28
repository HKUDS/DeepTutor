"""Account usage rollups combining durable LLM calls and recovered conversation history."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel


class UsageTotals(BaseModel):
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_calls: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_input_tokens: int = 0
    cache_reported_calls: int = 0
    cache_hit_rate: float | None = None
    ttft_seconds: float | None = None
    tokens_per_second: float | None = None
    duration_seconds: float = 0
    estimated_calls: int = 0


class ModelUsage(UsageTotals):
    provider: str = ""
    model: str = ""


class DailyUsage(BaseModel):
    date: str
    total_tokens: int = 0
    total_calls: int = 0
    turns: int = 0
    tracked_turns: int = 0


class UsageStatistics(BaseModel):
    year: int
    timezone: str
    totals: UsageTotals
    days: list[DailyUsage]
    models: list[ModelUsage]
    active_days: int
    sessions: int
    turns: int
    tracked_turns: int
    updated_at: float


def summaries_from_events(
    events: Any, metadata: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """RESULT is a snapshot; DONE replaces it, never adds to the same turn."""
    from .usage_recovery import recover_summary

    summaries: list[dict[str, Any]] = []
    pending = None
    evidence: list[dict[str, Any]] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        evidence.append(event)
        meta = event.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        if event.get("type") == "result":
            payload = meta.get("metadata") or {}
            if isinstance(payload, dict):
                value = payload.get("usage_summary") or payload.get("cost_summary")
                if isinstance(value, dict):
                    pending = value
        elif event.get("type") == "done":
            value = meta.get("usage_summary")
            if isinstance(value, dict):
                pending = value
            if pending:
                summaries.append(recover_summary(pending, evidence, metadata))
            pending = None
            evidence = []
    if pending:
        summaries.append(recover_summary(pending, evidence, metadata))
    return summaries


def _number(value: Any) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) and number > 0 else 0
    except (ValueError, TypeError, OverflowError):
        return 0


class _Totals:
    def __init__(self) -> None:
        self.values: dict[str, float] = defaultdict(float)

    def add(self, summary: dict[str, Any]) -> None:
        for key in (
            "total_tokens",
            "prompt_tokens",
            "completion_tokens",
            "total_calls",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cache_input_tokens",
            "cache_reported_calls",
            "duration_seconds",
            "estimated_calls",
            "ttft_calls",
            "generation_seconds",
            "timed_completion_tokens",
        ):
            self.values[key] += _number(summary.get(key))
        self.values["ttft_total"] += _number(summary.get("ttft_seconds")) * _number(
            summary.get("ttft_calls")
        )

    def result(self) -> dict[str, Any]:
        v = self.values
        result: dict[str, Any] = {
            key: int(v[key])
            for key in UsageTotals.model_fields
            if key
            not in ("cache_hit_rate", "ttft_seconds", "tokens_per_second", "duration_seconds")
        }
        result.update(
            duration_seconds=v["duration_seconds"],
            cache_hit_rate=v["cache_read_input_tokens"] / v["cache_input_tokens"]
            if v["cache_input_tokens"]
            else None,
            ttft_seconds=v["ttft_total"] / v["ttft_calls"] if v["ttft_calls"] else None,
            tokens_per_second=v["timed_completion_tokens"] / v["generation_seconds"]
            if v["generation_seconds"]
            else None,
        )
        return result


def _call_summary(call: dict[str, Any]) -> dict[str, Any]:
    cached = call.get("cache_read_input_tokens") is not None
    generation = _number(call.get("generation_seconds")) if not call.get("estimated") else 0
    return {
        **call,
        "total_calls": 1,
        "cache_reported_calls": int(cached),
        "cache_input_tokens": call.get("prompt_tokens", 0) if cached else 0,
        "ttft_calls": int(call.get("ttft_seconds") is not None),
        "generation_seconds": generation,
        "timed_completion_tokens": call.get("completion_tokens", 0) if generation else 0,
        "estimated_calls": int(bool(call.get("estimated"))),
    }


def aggregate_usage(records: list[dict[str, Any]], *, year: int, timezone: str) -> UsageStatistics:
    zone = ZoneInfo(timezone)
    start = datetime(year, 1, 1, tzinfo=zone)
    end = datetime(year + 1, 1, 1, tzinfo=zone)
    totals = _Totals()
    models: dict[tuple[str, str], _Totals] = defaultdict(_Totals)
    days: dict[str, DailyUsage] = {}
    day = start.date()
    while day < end.date():
        key = day.isoformat()
        days[key] = DailyUsage(date=key)
        day += timedelta(days=1)
    sessions: set[str] = set()
    activities: set[str] = set()
    tracked_activities: set[str] = set()
    daily_activities: set[tuple[str, str]] = set()
    daily_tracked: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        stamp = _number(record.get("created_at"))
        if not start.timestamp() <= stamp < end.timestamp():
            continue
        key = datetime.fromtimestamp(stamp, zone).date().isoformat()
        daily = days[key]
        activity = str(record.get("activity_id") or record.get("turn_id") or f"history:{index}")
        activities.add(activity)
        if (key, activity) not in daily_activities:
            daily.turns += 1
            daily_activities.add((key, activity))
        if session := record.get("session_id"):
            sessions.add(str(session))
        summaries = record.get("summaries") or []
        if summaries:
            tracked_activities.add(activity)
            if (key, activity) not in daily_tracked:
                daily.tracked_turns += 1
                daily_tracked.add((key, activity))
        for summary in summaries:
            totals.add(summary)
            daily.total_tokens += int(_number(summary.get("total_tokens")))
            daily.total_calls += int(_number(summary.get("total_calls")))
            calls = summary.get("call_details")
            if isinstance(calls, list) and calls:
                for call in calls:
                    if isinstance(call, dict):
                        models[(str(call.get("provider") or ""), str(call.get("model") or ""))].add(
                            _call_summary(call)
                        )
            elif isinstance(summary.get("by_model"), dict) and summary["by_model"]:
                for model, values in summary["by_model"].items():
                    if isinstance(values, dict):
                        models[("", str(model))].add(
                            {
                                **values,
                                "total_calls": values.get("total_calls", values.get("calls", 0)),
                            }
                        )
            else:
                models[(str(summary.get("provider") or ""), str(summary.get("model") or ""))].add(
                    summary
                )
    return UsageStatistics(
        year=year,
        timezone=timezone,
        totals=UsageTotals(**totals.result()),
        days=list(days.values()),
        models=sorted(
            [
                ModelUsage(provider=provider, model=model, **value.result())
                for (provider, model), value in models.items()
            ],
            key=lambda value: value.total_tokens,
            reverse=True,
        ),
        active_days=sum(day.turns > 0 for day in days.values()),
        sessions=len(sessions),
        turns=len(activities),
        tracked_turns=len(tracked_activities),
        updated_at=datetime.now().timestamp(),
    )
