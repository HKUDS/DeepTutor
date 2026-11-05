"""Durable store adapter for TypeScript history planning and summarization.

Python resolves the selected branch and persists a successful summary watermark.
No tokenization, context-budget selection or summary model request happens here.
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.agentic.client import build_completion_kwargs
from deeptutor.runtime.ts_engine import get_engine_client
from deeptutor.runtime.ts_engine.config import provider_config

from .context_builder import ContextBuildResult, build_history_text, format_messages_as_transcript
from .model_history import history_groups, model_turn, replay_history


async def build_native_history(
    builder: Any,
    *,
    session_id: str,
    llm_config: Any,
    language: str,
    messages: list[dict],
    unsummarized: list[dict],
    summary: str,
    route: dict | None,
    on_event: Any,
) -> ContextBuildResult:
    groups = history_groups(unsummarized)
    budget = builder._history_budget(llm_config)
    summary_budget = builder._summary_budget(budget, llm_config)
    events: list[StreamEvent] = []

    class HistoryPort:
        async def invoke(self, operation: str, args: dict, state: dict) -> None:
            if operation != "event":
                raise ValueError("Unknown history engine operation")
            raw = args["event"]
            if raw["type"] != "progress":
                raise ValueError("Unexpected history event")
            event = StreamEvent(
                type=StreamEventType.PROGRESS,
                source="context_builder",
                stage="summarize_context",
                content=raw["content"],
                metadata=raw["metadata"],
            )
            events.append(event)
            if on_event is not None:
                await on_event(event)

    result = await get_engine_client().run_native(
        HistoryPort(),
        {
            "groups": [{"messages": replay_history(group, route=route)} for group in groups],
            "summary": summary,
            "archivedTranscript": format_messages_as_transcript(
                messages[: len(messages) - len(unsummarized)]
            ),
            "budget": budget,
            "recentBudget": builder._recent_budget(budget),
            "summaryBudget": summary_budget,
            "rebuildBudget": builder._rebuild_source_budget(llm_config),
            "language": language,
            "provider": provider_config(
                llm_config,
                build_completion_kwargs(
                    temperature=0.2,
                    model=llm_config.model,
                    max_tokens=summary_budget,
                    binding=llm_config.binding,
                    reasoning_effort=llm_config.reasoning_effort,
                ),
            ),
        },
        kind="history",
    )
    summarized = result["summarizedGroups"]
    retained_start = result["retainedStart"]
    if not (
        isinstance(summarized, int)
        and isinstance(retained_start, int)
        and 0 <= summarized <= retained_start <= len(groups)
    ):
        raise ValueError("Invalid native history watermark")
    if summarized:
        watermark = int(groups[summarized - 1][-1].get("id", 0) or 0)
        await builder.store.update_summary(session_id, result["summary"], watermark)
    retained = [row for group in groups[retained_start:] for row in group]
    history = builder._build_history(result["summary"], retained)
    return ContextBuildResult(
        conversation_history=history,
        conversation_summary=result["summary"],
        context_text=build_history_text(history),
        events=events,
        token_count=result["tokenCount"],
        budget=budget,
        model_history=replay_history(retained, result["summary"], route),
        previous_model_turn=next(
            (record for row in reversed(messages) if (record := model_turn(row)) is not None), None
        ),
    )
