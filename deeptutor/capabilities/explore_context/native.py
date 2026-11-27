"""Scoped admission for the shared TS loop's read-only source investigation.

The application supplies authorized sources and localized prompts. Model I/O,
conversation projection, tool execution and loop control use the same engine as
chat. Investigation output belongs exclusively to the thinking trace.
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.agentic.client import build_completion_kwargs
from deeptutor.runtime.ts_engine import get_engine_client
from deeptutor.runtime.ts_engine.config import provider_config
from deeptutor.services.llm.context_window import resolve_effective_context_window


async def investigate_native(
    explorer: Any,
    context: Any,
    stream: Any,
    sources: dict[str, str],
    usage: Any,
    *,
    single_pass: bool = False,
) -> str:
    from deeptutor.runtime.agentic.tool_dispatch import MAX_PARALLEL_TOOL_CALLS

    from .explorer import EXPLORE_SOURCE, EXPLORE_STAGE, MAX_LOOP_ROUNDS, _budgets

    system = explorer._t("system" if single_pass else "loop.system")
    template = explorer._t("user_template" if single_pass else "loop.user_template")
    if not system or not template:
        return ""
    system = system if single_pass else system.format(tool_call_limit=MAX_PARALLEL_TOOL_CALLS)
    user = template.format(
        question=(context.user_message or "").strip() or "(empty)",
        mode=str(context.active_capability or "chat"),
        manifest=(context.source_manifest or "").strip() or "(none)",
        sources=explorer._render_source_blocks(sources) if single_pass else "",
    )
    cfg = explorer._llm_config
    tokens = _budgets()["briefing" if single_pass else "loop"]["max_tokens"]
    provider = provider_config(
        cfg,
        build_completion_kwargs(
            temperature=0.2,
            model=cfg.model,
            max_tokens=tokens,
            binding=cfg.binding,
            reasoning_effort=cfg.reasoning_effort,
        ),
    )

    class InvestigationPort:
        async def invoke(self, operation: str, args: dict, state: dict) -> None:
            if operation == "checkpoint":
                # An investigation must never replace the answer's model transcript.
                return
            if operation != "event":
                raise ValueError("Unexpected source investigation effect")
            event = args["event"]
            kind = StreamEventType(event["type"])
            if kind == StreamEventType.CONTENT:
                kind = StreamEventType.THINKING
            if kind not in {
                StreamEventType.THINKING,
                StreamEventType.PROGRESS,
                StreamEventType.TOOL_CALL,
                StreamEventType.TOOL_RESULT,
            }:
                raise ValueError("Unexpected investigation event")
            metadata = dict(event["metadata"])
            if metadata.get("call_kind") == "agent_loop_round":
                metadata.update(call_kind="context_exploration", trace_role="explore")
            await stream.emit(
                StreamEvent(
                    type=kind,
                    source=EXPLORE_SOURCE,
                    stage=EXPLORE_STAGE,
                    content=event["content"],
                    metadata=metadata,
                )
            )

    payload = {
        "config": {
            "explorationBudget": 1 if single_pass else MAX_LOOP_ROUNDS - 1,
            "settlementBudget": 0,
            "emptyRecoveryBudget": 1,
        },
        "provider": provider,
        "seed": {
            "system": system,
            "history": [],
            "snapshots": {},
            "user": {"role": "user", "content": user},
            "contextWindow": resolve_effective_context_window(
                context_window=cfg.context_window, model=cfg.model, max_tokens=tokens
            ),
            "outputTokens": tokens,
            "model": cfg.model,
            "route": {},
        },
        "tools": []
        if single_pass
        else [
            {"schema": schema, "native": True, "sensitive": ["source_index"]}
            for schema in explorer._read_source_schemas(sources)
        ],
        "toolRuntime": {"read_source": {"sources": sources}},
        "source": EXPLORE_SOURCE,
        "stage": EXPLORE_STAGE,
        "sessionId": context.session_id or "",
        "workspace": None,
        "skillRoots": {},
        "rebindingTools": [],
        "deferOutput": False,
        "policyHooks": False,
        "initialToolChoice": None,
        "copy": {
            "exploring": explorer._status_exploring(),
            "final_response": explorer._status_exploring(),
            "finish": explorer._forced_finish_instruction(),
            "empty_nudge": explorer._forced_finish_instruction(),
        },
    }
    async with stream.stage(
        EXPLORE_STAGE,
        source=EXPLORE_SOURCE,
        metadata={"call_kind": "context_exploration", "native_runtime": "typescript"},
    ):
        result = await get_engine_client().run_native(InvestigationPort(), payload)
    if usage is not None:
        for entry in result["usage"]:
            usage.add_from_response(entry)
    return result["response"]
