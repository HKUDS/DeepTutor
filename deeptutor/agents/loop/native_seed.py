"""Admit a scoped native turn without constructing a Python model client.

The existing application still resolves identity, tool grants, and domain prompt
fragments. TypeScript assembles and owns the conversation from this immutable
seed, including runtime snapshots, request projection, and per-round budgets.
"""

from __future__ import annotations

from typing import Any

from deeptutor.runtime.ts_engine.config import provider_config
from deeptutor.services.llm.context_window import resolve_effective_context_window

NATIVE_TOOLS = frozenset(
    {
        "workspace_list",
        "workspace_read",
        "workspace_search",
        "read_skill",
        "ask_user",
        "reason",
        "brainstorm",
        "read_source",
        "read_memory",
        "partner_read",
    }
)


def tool_specs(pipeline: Any, schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for schema in schemas:
        name = schema["function"]["name"]
        tool = pipeline.tool_lookup.get(name)
        if tool is None:
            continue
        definition = tool.get_definition()
        # A plugin replacing a builtin must keep its own implementation.
        native = name in NATIVE_TOOLS and type(tool).__module__ in {
            "deeptutor.tools.workspace",
            "deeptutor.tools.builtin",
            "deeptutor.tools.partner_memory",
        }
        result.append(
            {
                "schema": schema,
                "sensitive": [p.name for p in definition.parameters if p.sensitive],
                "native": native,
            }
        )
    return result


async def native_seed(
    pipeline: Any, context: Any, stream: Any, enabled: list[str], schemas: list[dict[str, Any]]
) -> dict[str, Any]:
    # Validate the provider before any pre-loop capability can produce effects.
    provider = provider_config(
        pipeline.llm_config, pipeline._completion_kwargs(max_tokens=pipeline.loop_max_tokens)
    )
    briefing = await pipeline._capability_pre_loop_briefings(context, stream)
    kb = await pipeline._retrieve_kb_seed_block(context, stream)
    seed = "\n\n".join(
        x.strip() for x in [kb, pipeline._capability_pre_loop_seed(context), briefing] if x.strip()
    )
    system = pipeline._build_system_prompt(enabled, context, include_tool_manifest=bool(schemas))
    user = pipeline._prompt_assembler.user_message(context=context, kb_seed=seed)
    user_message = pipeline._prepare_messages_with_attachments(
        [{"role": "user", "content": user}], context
    )[-1]
    history = context.runtime.model_history
    if history is None:
        history = []
        for entry in context.conversation_history:
            if entry.get("role") in {"user", "assistant"}:
                history.append(dict(entry))
            elif entry.get("role") == "system" and entry.get("content"):
                history.append(
                    {"role": "system", "content": f"[Conversation summary]\n{entry['content']}"}
                )
    from deeptutor.services.skill.runtime import runtime_skills

    skill_roots = {}
    if any(s["function"]["name"] == "read_skill" for s in schemas):
        for name, service in runtime_skills().items():
            resolved = service._resolve_skill_dir(name)
            if resolved:
                skill_roots[name] = str(resolved[0].resolve())
    workspace = context.runtime.workspace
    copy = {
        key: pipeline._t(f"labels.{key}", default=fallback)
        for key, fallback in [
            ("exploring", "Exploring"),
            ("final_response", "Final response"),
            ("tool_call", "Tool call"),
        ]
    }
    copy.update(
        finish=pipeline._finish_exhausted_instruction(),
        settle=pipeline._settle_exhausted_instruction(),
    )
    for key, path in {
        "continue_truncated": "loop.continue_truncated",
        "continue_reasoning": "loop.continue_truncated_reasoning",
        "empty_nudge": "loop.finish_empty_nudge",
        "user_sent_while_working": "loop.user_sent_while_working",
        "context_window_guard": "notices.context_window_guard",
        "output_truncated": "notices.output_truncated",
    }.items():
        copy[key] = pipeline._t(path, default="")
    from .native_tools import tool_runtime

    specs = tool_specs(pipeline, schemas)
    runtime = tool_runtime(pipeline, context, specs)
    return {
        "config": {
            "explorationBudget": pipeline.effective_max_rounds(context),
            "settlementBudget": 3,
            "emptyRecoveryBudget": 2,
        },
        "provider": provider,
        "seed": {
            "system": system,
            "history": history,
            "snapshots": pipeline._runtime_snapshots,
            "user": user_message,
            "contextWindow": resolve_effective_context_window(
                context_window=pipeline.llm_config.context_window,
                model=pipeline.model,
                max_tokens=pipeline.loop_max_tokens,
            ),
            "outputTokens": pipeline.loop_max_tokens,
            "model": pipeline.model,
            "route": {"provider": pipeline.binding, "model": pipeline.model},
        },
        "tools": specs,
        "toolRuntime": runtime,
        "source": pipeline.event_source,
        "stage": pipeline.event_stage,
        "sessionId": context.session_id or "",
        "workspace": {"root": workspace.root, "id": workspace.workspace_id} if workspace else None,
        "skillRoots": skill_roots,
        "rebindingTools": list(pipeline._capability_rebinding_tools(context)),
        "deferOutput": pipeline._capability_buffers_visible_output(context),
        "policyHooks": bool(pipeline._active_loop_capabilities(context)),
        "userInputEnabled": context.runtime.drain_user_inputs is not None,
        "initialToolChoice": pipeline.initial_tool_choice,
        "copy": copy,
    }
