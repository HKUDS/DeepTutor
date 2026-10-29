"""Server-owned admission data for tools whose execution lives in TypeScript."""

from __future__ import annotations

from typing import Any

from deeptutor.runtime.agentic.client import build_completion_kwargs
from deeptutor.runtime.ts_engine.config import provider_config


def tool_runtime(pipeline: Any, context: Any, specs: list[dict]) -> dict[str, dict]:
    runtime: dict[str, dict] = {}
    for spec in specs:
        name = spec["schema"]["function"]["name"]
        if not spec["native"] or name not in {
            "reason",
            "brainstorm",
            "read_source",
            "read_memory",
            "partner_read",
        }:
            continue
        defaults = pipeline._augment_tool_kwargs(name, {}, context)
        # Preserve custom capability augmentation through its existing adapter.
        allowed = (
            {"context"}
            if name in {"reason", "brainstorm"}
            else ({"source_index"} if name == "read_source" else set())
        )
        if set(defaults) - allowed or name in pipeline._capability_rebinding_tools(context):
            spec["native"] = False
            continue
        if name in {"read_memory", "partner_read"}:
            from .native_memory import memory_roots

            runtime[name] = {"memoryRoots": memory_roots(name)}
            continue
        if name == "read_source":
            index = defaults.get("source_index") or {}
            if not isinstance(index, dict):
                spec["native"] = False
                continue
            runtime[name] = {"sources": {str(k): str(v) for k, v in index.items()}}
            continue
        from deeptutor.services.config import get_agent_params
        from deeptutor.tools.brainstorm import _SYSTEM_PROMPT as brainstorm_prompt
        from deeptutor.tools.reason import _SYSTEM_PROMPT as reason_prompt

        params = get_agent_params("solve" if name == "reason" else "brainstorm")
        runtime[name] = {
            "context": str(defaults.get("context") or ""),
            "system": reason_prompt if name == "reason" else brainstorm_prompt,
            "provider": provider_config(
                pipeline.llm_config,
                build_completion_kwargs(
                    model=pipeline.model,
                    binding=pipeline.binding,
                    max_tokens=params.get("max_tokens", 4096 if name == "reason" else 2048),
                    temperature=params.get("temperature", 0.0 if name == "reason" else 0.8),
                    reasoning_effort=pipeline.llm_config.reasoning_effort,
                ),
            ),
        }
    return runtime
