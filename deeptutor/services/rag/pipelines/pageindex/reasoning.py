"""A small DeepTutor agent loop for workflow-owned PageIndex reading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deeptutor.core.agentic import (
    DispatchOutcome,
    LabelProtocol,
    LLMClientConfig,
    UsageTracker,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
    dispatch_tool_calls,
    run_agentic_loop,
)
from deeptutor.core.agentic.labeled_step import run_labeled_step
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.llm import get_llm_config

from .tools import PageIndexToolContext, build_pageindex_tool_context

_PROTOCOL = LabelProtocol(
    allowed=("THINK", "TOOL", "FINISH"),
    terminal=frozenset({"FINISH"}),
    intermediate=frozenset({"THINK"}),
    final=frozenset({"FINISH"}),
    tool_label="TOOL",
)


@dataclass(frozen=True)
class PageIndexReadingResult:
    text: str
    sources: list[dict[str, Any]]
    tool_context: PageIndexToolContext


class _ReadingHost:
    def __init__(
        self,
        *,
        tool_context: PageIndexToolContext,
        context: UnifiedContext,
        stream: StreamBus,
        client: Any,
        model: str | None,
        binding: str,
        reasoning_effort: str | None,
        source: str,
        stage: str,
    ) -> None:
        self.tool_context = tool_context
        self.context = context
        self.stream = stream
        self.client = client
        self.model = model
        self.binding = binding
        self.reasoning_effort = reasoning_effort
        self.source = source
        self.stage = stage

    async def guard_context_window(self, messages: list[dict[str, Any]]) -> None:
        return

    def build_iteration_trace_meta(self, iteration: int) -> tuple[dict[str, Any], dict[str, Any]]:
        call_id = new_call_id(f"{self.source}-pageindex-{iteration}")
        meta = build_trace_metadata(
            call_id=call_id,
            phase=self.stage,
            label="PageIndex reading",
            call_kind="llm_reasoning",
            trace_id=call_id,
            trace_role="thought",
            trace_group="stage",
        )
        return meta, meta

    async def dispatch_tools(
        self,
        *,
        iteration: int,
        tool_calls: list[dict[str, Any]],
    ) -> DispatchOutcome:
        return await dispatch_tool_calls(
            tool_calls=tool_calls,
            context=self.context,
            stream=self.stream,
            source=self.source,
            stage=self.stage,
            iteration_index=iteration,
            registry=self.tool_context.registry,
            tool_call_label="PageIndex tool",
            retrieve_label="Read document",
            empty_tool_result_message="PageIndex returned no content.",
            start_retrieval_message="Reading PageIndex documents",
            too_many_tool_calls_message="Too many tool calls in one round.",
            unknown_error_message_factory=lambda name: f"Error executing {name}.",
            trace_id_prefix=f"{self.source}-pageindex",
        )

    async def resolve_pause(self, dispatch: DispatchOutcome) -> bool:
        return False

    async def emit_terminator(self, payload: dict[str, Any] | None) -> None:
        return

    async def emit_final(self, text: str, final_meta: dict[str, Any]) -> None:
        return

    def protocol_retry_notice(self) -> str:
        return "The PageIndex reading loop used an invalid action label; retrying."

    def protocol_repair_message(self, violation: str) -> str:
        return (
            f"Protocol violation: {violation}. Start with exactly THINK, TOOL, or FINISH. "
            "Use TOOL only with tool calls; FINISH must contain the requested result."
        )

    async def force_finalize(
        self,
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
    ) -> tuple[str, bool, int]:
        messages.append(
            {
                "role": "user",
                "content": "Tool budget exhausted. Return FINISH followed by the best grounded result now.",
            }
        )
        step = await run_labeled_step(
            client=self.client,
            model=self.model,
            messages=messages,
            completion_kwargs=build_completion_kwargs(
                temperature=0.2,
                model=self.model,
                max_tokens=5000,
                binding=self.binding,
                reasoning_effort=self.reasoning_effort,
            ),
            tool_schemas=None,
            allowed_labels=("FINISH",),
            final_labels=frozenset({"FINISH"}),
            tool_label=None,
            stream=self.stream,
            source=self.source,
            stage=self.stage,
            iter_meta=self.build_iteration_trace_meta(start_iteration)[0],
            binding=self.binding,
        )
        return step.text, step.label == "FINISH", 1


async def read_pageindex_with_agent(
    *,
    kb_name: str,
    system_prompt: str,
    user_prompt: str,
    context: UnifiedContext | None = None,
    stream: StreamBus | None = None,
    source: str,
    stage: str,
    max_iterations: int = 8,
) -> PageIndexReadingResult:
    """Run the caller's reasoning stage with the selected PageIndex tools."""
    llm = get_llm_config()
    binding = str(getattr(llm, "binding", None) or "openai")
    model = getattr(llm, "model", None)
    if not can_use_native_tool_calling(binding=binding, model=model):
        raise RuntimeError("The active LLM must support tool calling to read a PageIndex KB.")

    tool_context = await build_pageindex_tool_context(
        kb_name,
        base_registry=get_tool_registry(),
    )
    if tool_context is None:
        raise ValueError(f"Knowledge base '{kb_name}' is not a PageIndex knowledge base")

    bus = stream or StreamBus(max_history=0)
    turn_context = context or UnifiedContext(user_message=user_prompt, knowledge_bases=[kb_name])
    client = build_openai_client(
        LLMClientConfig(
            binding=binding,
            model=model,
            api_key=getattr(llm, "api_key", None),
            base_url=getattr(llm, "base_url", None),
            api_version=getattr(llm, "api_version", None),
            extra_headers=getattr(llm, "extra_headers", None) or None,
            reasoning_effort=getattr(llm, "reasoning_effort", None),
        )
    )
    docs = (
        "; ".join(
            f"{name} (doc_id: {doc_id})" for name, doc_id in sorted(tool_context.documents.items())
        )
        or "(no indexed documents)"
    )
    tool_names = ", ".join(tool.name for tool in tool_context.tools)
    managed = (
        "You are reading a PageIndex knowledge base inside the caller's existing workflow.\n"
        "Use Reasoning as Retrieval: inspect document structure and then read only relevant pages.\n"
        "Never call a generic RAG search and never answer document claims from general knowledge.\n"
        "Each response must start with exactly one label on its own first line: THINK, TOOL, or "
        "FINISH. TOOL must include native tool calls. FINISH must contain the caller's requested "
        "grounded result.\n"
        f"Available tools: {tool_names}\nDocuments: {docs}\n"
        f"{tool_context.instructions}\n\n{system_prompt}"
    )
    host = _ReadingHost(
        tool_context=tool_context,
        context=turn_context,
        stream=bus,
        client=client,
        model=model,
        binding=binding,
        reasoning_effort=getattr(llm, "reasoning_effort", None),
        source=source,
        stage=stage,
    )
    outcome = await run_agentic_loop(
        initial_messages=[
            {"role": "system", "content": managed},
            {"role": "user", "content": user_prompt},
        ],
        protocol=_PROTOCOL,
        client=client,
        model=model,
        completion_kwargs=build_completion_kwargs(
            temperature=0.2,
            model=model,
            max_tokens=5000,
            binding=binding,
            reasoning_effort=getattr(llm, "reasoning_effort", None),
        ),
        binding=binding,
        tool_schemas=[tool.get_definition().to_openai_schema() for tool in tool_context.tools],
        stream=bus,
        source=source,
        stage=stage,
        max_iterations=max_iterations,
        host=host,
        usage=UsageTracker(model=model),
        eager_sub_trace=True,
    )
    if outcome.sources:
        await bus.sources(outcome.sources, source=source, stage=stage)
    return PageIndexReadingResult(
        text=(outcome.final_text or "").strip(),
        sources=list(outcome.sources),
        tool_context=tool_context,
    )


__all__ = ["PageIndexReadingResult", "read_pageindex_with_agent"]
