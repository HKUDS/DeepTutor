r"""Foundational agentic engine primitives.

These modules implement the chat-style ``\`\`LABEL\`\`+content`` LLM protocol as
reusable building blocks. Any capability that wants a streaming, label-driven
LLM loop (chat, solve step, etc.) composes them.

Layering:

* :mod:`labels`         — protocol-label parsing (parametric label set).
* :mod:`client`         — OpenAI/Azure client factory + completion kwargs.
* :mod:`usage`          — token-usage accumulator shared across steps.
* :mod:`labeled_step`   — one streaming LLM call with label routing.
* :mod:`tool_dispatch`  — parallel tool execution with per-tool sub-traces.
* :mod:`loop`           — iteration scheduler that ties the above together.

Capability-specific concerns (system prompt assembly, tool whitelist, KB enums,
answer-now fast paths, force-finalize strategies, context-window guards) live
in each capability's own module — the primitives expose hooks but do not bake
those decisions in.
"""

from importlib import import_module

__all__ = [
    "LABEL_PROBE_MAX_CHARS",
    "LABEL_UNKNOWN",
    "LLMClientConfig",
    "LabelProtocol",
    "LabeledStepResult",
    "LoopHost",
    "LoopOutcome",
    "MAX_PARALLEL_TOOL_CALLS",
    "DispatchOutcome",
    "UsageTracker",
    "build_completion_kwargs",
    "build_openai_client",
    "can_use_native_tool_calling",
    "classify_label",
    "dispatch_tool_calls",
    "execute_tool_call",
    "find_inline_labels",
    "run_agentic_loop",
    "run_labeled_step",
    "strip_label_probe_prefix",
]


_EXPORT_MODULES = {
    "LLMClientConfig": "client",
    "build_completion_kwargs": "client",
    "build_openai_client": "client",
    "can_use_native_tool_calling": "client",
    "LabeledStepResult": "labeled_step",
    "run_labeled_step": "labeled_step",
    "LABEL_PROBE_MAX_CHARS": "labels",
    "LABEL_UNKNOWN": "labels",
    "classify_label": "labels",
    "find_inline_labels": "labels",
    "strip_label_probe_prefix": "labels",
    "LabelProtocol": "loop",
    "LoopHost": "loop",
    "LoopOutcome": "loop",
    "run_agentic_loop": "loop",
    "MAX_PARALLEL_TOOL_CALLS": "tool_dispatch",
    "DispatchOutcome": "tool_dispatch",
    "dispatch_tool_calls": "tool_dispatch",
    "execute_tool_call": "tool_dispatch",
    "UsageTracker": "usage",
}


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
