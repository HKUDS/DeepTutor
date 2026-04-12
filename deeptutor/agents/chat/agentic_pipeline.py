"""Agentic chat pipeline with thinking, acting, observing, and responding."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import logging
import os
from typing import Any

import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import (
    build_trace_metadata,
    derive_trace_metadata,
    merge_trace_metadata,
    new_call_id,
)
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.llm import (
    clean_thinking_tags,
    complete as llm_complete,
    get_llm_config,
    get_token_limit_kwargs,
    prepare_multimodal_messages,
    stream as llm_stream,
    supports_response_format,
    supports_tools,
)
from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES
from deeptutor.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

CHAT_EXCLUDED_TOOLS = {"geogebra_analysis"}
CHAT_OPTIONAL_TOOLS = [
    name for name in BUILTIN_TOOL_NAMES if name not in CHAT_EXCLUDED_TOOLS
]
MAX_PARALLEL_TOOL_CALLS = 8
MAX_TOOL_RESULT_CHARS = 4000


@dataclass
class ToolTrace:
    name: str
    arguments: dict[str, Any]
    result: str
    success: bool
    sources: list[dict[str, Any]]
    metadata: dict[str, Any]


class AgenticChatPipeline:
    """Run chat as a 4-stage agentic pipeline."""

    def __init__(self, language: str = "en") -> None:
        self.language = "zh" if language.lower().startswith("zh") else "en"
        self.llm_config = get_llm_config()
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.registry = get_tool_registry()
        self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}

    def _accumulate_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage:
            self._usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            self._usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
            self._usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
            self._usage["calls"] += 1

    def _get_cost_summary(self) -> dict[str, Any] | None:
        if self._usage["calls"] == 0:
            return None
        return {
            "total_cost_usd": 0,
            "total_tokens": self._usage["total_tokens"],
            "total_calls": self._usage["calls"],
        }

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        answer_now_context = self._extract_answer_now_context(context)
        if answer_now_context is not None:
            final_response, trace_meta = await self._stage_answer_now(
                context=context,
                answer_now_context=answer_now_context,
                stream=stream,
            )
            result_payload: dict[str, Any] = {
                "response": final_response,
                "answer_now": True,
                "source_trace": trace_meta.get("label", "Answer now"),
            }
            cs = self._get_cost_summary()
            if cs:
                result_payload["metadata"] = {"cost_summary": cs}
            await stream.result(result_payload, source="chat")
            return

        enabled_tools = self._normalize_enabled_tools(context.enabled_tools)
        thinking_text = await self._stage_thinking(context, enabled_tools, stream)
        tool_traces = await self._stage_acting(
            context=context,
            enabled_tools=enabled_tools,
            thinking_text=thinking_text,
            stream=stream,
        )
        observation = await self._stage_observing(
            context=context,
            enabled_tools=enabled_tools,
            thinking_text=thinking_text,
            tool_traces=tool_traces,
            stream=stream,
        )
        final_response, responding_trace = await self._stage_responding(
            context=context,
            enabled_tools=enabled_tools,
            thinking_text=thinking_text,
            observation=observation,
            tool_traces=tool_traces,
            stream=stream,
        )

        all_sources: list[dict[str, Any]] = []
        for trace in tool_traces:
            all_sources.extend(trace.sources)
        if all_sources:
            await stream.sources(
                all_sources,
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    responding_trace,
                    {"trace_kind": "sources"},
                ),
            )

        result_payload: dict[str, Any] = {
            "response": final_response,
            "observation": observation,
            "tool_traces": [asdict(trace) for trace in tool_traces],
        }
        cs = self._get_cost_summary()
        if cs:
            result_payload["metadata"] = {"cost_summary": cs}
        await stream.result(result_payload, source="chat")

    async def _stage_thinking(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        stream: StreamBus,
    ) -> str:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-thinking"),
            phase="thinking",
            label=self._text(zh="Reasoning", en="Reasoning"),
            call_kind="llm_reasoning",
            trace_id="chat-thinking",
            trace_role="thought",
            trace_group="stage",
        )
        async with stream.stage("thinking", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="thinking",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._thinking_system_prompt(enabled_tools, context),
                user_content=context.user_message,
            )
            messages, images_stripped = self._prepare_messages_with_attachments(
                messages,
                context,
            )
            if images_stripped:
                await stream.thinking(
                    self._images_stripped_notice(),
                    source="chat",
                    stage="thinking",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )

            chunks: list[str] = []
            async for chunk in self._stream_messages(messages, max_tokens=1200):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.thinking(
                    chunk,
                    source="chat",
                    stage="thinking",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="thinking",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model)

    async def _stage_acting(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        stream: StreamBus,
    ) -> list[ToolTrace]:
        async with stream.stage("acting", source="chat"):
            if not enabled_tools:
                await stream.progress(
                    self._text(
                        zh="当前没有启用任何工具，本轮跳过工具调用。",
                        en="No tools are enabled for this turn, so tool execution was skipped.",
                    ),
                    source="chat",
                    stage="acting",
                )
                return []

            if self._can_use_native_tool_calling():
                return await self._run_native_tool_loop(
                    context=context,
                    enabled_tools=enabled_tools,
                    thinking_text=thinking_text,
                    stream=stream,
                )

            await stream.progress(
                self._text(
                    zh="当前模型不支持原生工具调用，已切换到 ReAct 文本编排。",
                    en="The current model does not support native tool calling, so ReAct text orchestration is used.",
                ),
                source="chat",
                stage="acting",
            )
            return await self._run_react_fallback(
                context=context,
                enabled_tools=enabled_tools,
                thinking_text=thinking_text,
                stream=stream,
            )

    async def _stage_observing(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        tool_traces: list[ToolTrace],
        stream: StreamBus,
    ) -> str:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-observing"),
            phase="observing",
            label=self._text(zh="Observation", en="Observation"),
            call_kind="llm_observation",
            trace_id="chat-observing",
            trace_role="observe",
            trace_group="stage",
        )
        async with stream.stage("observing", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="observing",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )
            observation_prompt = self._text(
                zh=(
                    "请整理本轮推理与工具执行得到的关键信息，输出给 tutor 自己看的观察总结。"
                    "聚焦：已确认事实、仍不确定的点、最终回答应强调什么。不要直接写给学生。"
                ),
                en=(
                    "Summarize what was learned from the reasoning and tool execution for the tutor's internal observation note. "
                    "Focus on confirmed facts, remaining uncertainty, and what the final answer should emphasize. "
                    "Do not address the student directly."
                ),
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._observing_system_prompt(enabled_tools),
                user_content=(
                    f"{observation_prompt}\n\n"
                    f"{self._labeled_block('Thinking', thinking_text)}\n\n"
                    f"{self._labeled_block('Tool Trace', self._format_tool_traces(tool_traces))}"
                ),
            )

            chunks: list[str] = []
            async for chunk in self._stream_messages(messages, max_tokens=1200):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.observation(
                    chunk,
                    source="chat",
                    stage="observing",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "observation"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="observing",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model)

    async def _stage_responding(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        observation: str,
        tool_traces: list[ToolTrace],
        stream: StreamBus,
    ) -> tuple[str, dict[str, Any]]:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-responding"),
            phase="responding",
            label=self._text(zh="Final response", en="Final response"),
            call_kind="llm_final_response",
            trace_id="chat-responding",
            trace_role="response",
            trace_group="stage",
        )
        async with stream.stage("responding", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )
            user_prompt = self._text(
                zh=(
                    f"用户问题：\n{context.user_message}\n\n"
                    f"{self._labeled_block('Observation', observation)}\n\n"
                    f"{self._labeled_block('Tool Trace', self._format_tool_traces(tool_traces))}\n\n"
                    "请基于以上内容，直接给出正式回答。不要暴露内部 pipeline、thinking、observing 等字样。"
                ),
                en=(
                    f"User request:\n{context.user_message}\n\n"
                    f"{self._labeled_block('Observation', observation)}\n\n"
                    f"{self._labeled_block('Tool Trace', self._format_tool_traces(tool_traces))}\n\n"
                    "Use this material to produce the final answer for the user. "
                    "Do not mention the internal pipeline, thinking, or observing stages."
                ),
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._responding_system_prompt(enabled_tools),
                user_content=user_prompt,
            )

            chunks: list[str] = []
            async for chunk in self._stream_messages(messages, max_tokens=1800):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.content(
                    chunk,
                    source="chat",
                    stage="responding",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model), trace_meta

    async def _stage_answer_now(
        self,
        context: UnifiedContext,
        answer_now_context: dict[str, Any],
        stream: StreamBus,
    ) -> tuple[str, dict[str, Any]]:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-answer-now"),
            phase="responding",
            label="Answer now",
            call_kind="llm_final_response",
            trace_id="chat-answer-now",
            trace_role="response",
            trace_group="stage",
        )
        async with stream.stage("responding", source="chat", metadata=trace_meta):
            await stream.progress(
                trace_meta["label"],
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "running"},
                ),
            )

            original_user_message = str(
                answer_now_context.get("original_user_message") or context.user_message
            ).strip()
            partial_response = str(answer_now_context.get("partial_response") or "").strip()
            trace_summary = self._format_answer_now_events(answer_now_context.get("events"))
            user_prompt = self._text(
                zh=(
                    f"用户原始问题：\n{original_user_message}\n\n"
                    f"{self._labeled_block('Current Draft', partial_response)}\n\n"
                    f"{self._labeled_block('Execution Trace', trace_summary)}\n\n"
                    "请基于当前已经完成的内容，立刻直接生成给用户的最终答复。"
                    "不要继续规划或调用工具，不要提到内部阶段。"
                    "如果信息仍有缺口，请诚实说明不确定之处，但仍尽可能先给出当前最有用的回答。"
                ),
                en=(
                    f"Original user request:\n{original_user_message}\n\n"
                    f"{self._labeled_block('Current Draft', partial_response)}\n\n"
                    f"{self._labeled_block('Execution Trace', trace_summary)}\n\n"
                    "Using only the material already gathered so far, produce the final user-facing answer now. "
                    "Do not continue planning or call tools, and do not mention internal stages. "
                    "If something is still uncertain, be explicit about the uncertainty while still giving the most useful answer you can."
                ),
            )
            messages = self._build_messages(
                context=context,
                system_prompt=self._responding_system_prompt([]),
                user_content=user_prompt,
            )

            chunks: list[str] = []
            async for chunk in self._stream_messages(messages, max_tokens=1800):
                if not chunk:
                    continue
                chunks.append(chunk)
                await stream.content(
                    chunk,
                    source="chat",
                    stage="responding",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_chunk"}),
                )
            await stream.progress(
                "",
                source="chat",
                stage="responding",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return clean_thinking_tags("".join(chunks), self.binding, self.model), trace_meta

    async def _run_native_tool_loop(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        stream: StreamBus,
    ) -> list[ToolTrace]:
        tool_schemas = self.registry.build_openai_schemas(enabled_tools)
        messages = self._build_messages(
            context=context,
            system_prompt=self._acting_system_prompt(enabled_tools, context),
            user_content=self._acting_user_prompt(context, thinking_text),
        )
        tool_traces: list[ToolTrace] = []
        client = self._build_openai_client()
        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-acting"),
            phase="acting",
            label=self._text(zh="Tool call", en="Tool call"),
            call_kind="tool_planning",
            trace_id="chat-acting",
            trace_role="tool",
            trace_group="tool_call",
        )
        await stream.progress(
            trace_meta["label"],
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "running"},
            ),
        )
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
            **self._completion_kwargs(max_tokens=1500),
        )
        self._accumulate_usage(response)
        if not response.choices:
            return tool_traces

        choice = response.choices[0]
        message = choice.message
        assistant_content = self._message_text(message.content)
        raw_tool_calls = list(message.tool_calls or [])

        if assistant_content:
            await stream.thinking(
                assistant_content,
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_output"}),
            )

        if not raw_tool_calls:
            await stream.progress(
                self._text(
                    zh="本轮不需要调用工具。",
                    en="No tool call was needed for this turn.",
                ),
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "progress"}),
            )
            await stream.progress(
                "",
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return tool_traces

        pending_calls: list[tuple[str, str, dict[str, Any]]] = []
        if len(raw_tool_calls) > MAX_PARALLEL_TOOL_CALLS:
            await stream.progress(
                self._text(
                    zh=f"模型请求了 {len(raw_tool_calls)} 个工具，本轮最多并行执行 {MAX_PARALLEL_TOOL_CALLS} 个，已截断。",
                    en=(
                        f"The model requested {len(raw_tool_calls)} tools. "
                        f"At most {MAX_PARALLEL_TOOL_CALLS} can run in parallel in one turn, so the list was truncated."
                    ),
                ),
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "progress"}),
            )
        for tool_call in raw_tool_calls[:MAX_PARALLEL_TOOL_CALLS]:
            tool_name = tool_call.function.name
            tool_args = parse_json_response(
                tool_call.function.arguments or "{}",
                logger_instance=logger,
                fallback={},
            )
            if not isinstance(tool_args, dict):
                tool_args = {}
            tool_args = self._augment_tool_kwargs(tool_name, tool_args, context, thinking_text)
            pending_calls.append((tool_call.id, tool_name, tool_args))

        for tool_index, (tool_call_id, tool_name, tool_args) in enumerate(pending_calls):
            await stream.tool_call(
                tool_name=tool_name,
                args=tool_args,
                source="chat",
                stage="acting",
                metadata=self._tool_trace_metadata(
                    trace_meta,
                    context=context,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_index=tool_index,
                ),
            )

        tool_results = await asyncio.gather(
            *[
                self._execute_tool_call(
                    tool_name,
                    tool_args,
                    stream=stream,
                    retrieve_meta=self._retrieve_trace_metadata(
                        trace_meta,
                        context=context,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        tool_index=tool_index,
                        tool_args=tool_args,
                    ),
                )
                for tool_index, (tool_call_id, tool_name, tool_args) in enumerate(pending_calls)
            ]
        )

        for tool_index, ((tool_call_id, tool_name, tool_args), tool_result) in enumerate(
            zip(pending_calls, tool_results, strict=False)
        ):
            result_text = tool_result["result_text"]
            success = bool(tool_result["success"])
            sources = tool_result["sources"]
            metadata = tool_result["metadata"]
            await stream.tool_result(
                tool_name=tool_name,
                result=result_text,
                source="chat",
                stage="acting",
                metadata=self._tool_trace_metadata(
                    trace_meta,
                    context=context,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    tool_index=tool_index,
                    trace_kind="tool_result",
                ),
            )

            tool_traces.append(
                ToolTrace(
                    name=tool_name,
                    arguments=tool_args,
                    result=result_text,
                    success=success,
                    sources=sources,
                    metadata=metadata,
                )
            )

        await stream.progress(
            "",
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "complete"},
            ),
        )

        return tool_traces

    async def _run_react_fallback(
        self,
        context: UnifiedContext,
        enabled_tools: list[str],
        thinking_text: str,
        stream: StreamBus,
    ) -> list[ToolTrace]:
        tool_traces: list[ToolTrace] = []
        tool_table = self.registry.build_prompt_text(
            enabled_tools,
            format="table",
            language=self.language,
            control_actions=[
                {
                    "name": "done",
                    "when_to_use": self._text(
                        zh="当已有信息足够，且不需要继续调用工具时使用。",
                        en="Use when the available information is sufficient and no more tools are needed.",
                    ),
                    "input_format": self._text(
                        zh="空字符串。",
                        en="Empty string.",
                    ),
                }
            ],
        )

        trace_meta = build_trace_metadata(
            call_id=new_call_id("chat-react"),
            phase="acting",
            label=self._text(zh="Tool call", en="Tool call"),
            call_kind="tool_planning",
            trace_id="chat-react",
            trace_role="tool",
            trace_group="tool_call",
        )
        await stream.progress(
            trace_meta["label"],
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "running"},
            ),
        )
        _fb_prompt = self._acting_user_prompt(context, thinking_text)
        _fb_system = self._react_fallback_system_prompt(tool_table)
        _chunks: list[str] = []
        async for _c in llm_stream(
            prompt=_fb_prompt,
            system_prompt=_fb_system,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            response_format={"type": "json_object"}
            if supports_response_format(self.binding, self.model)
            else None,
            **self._completion_kwargs(max_tokens=800),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
        _fb_in = int((len(_fb_prompt) + len(_fb_system)) / 3.5)
        _fb_out = int(len(response) / 3.5)
        self._usage["prompt_tokens"] += _fb_in
        self._usage["completion_tokens"] += _fb_out
        self._usage["total_tokens"] += _fb_in + _fb_out
        self._usage["calls"] += 1

        payload = parse_json_response(response, logger_instance=logger, fallback={})
        if not isinstance(payload, dict):
            payload = {}

        action = str(payload.get("action") or "done").strip()
        action_input = payload.get("action_input") or {}
        if not isinstance(action_input, dict):
            action_input = {}

        if action == "done":
            if response:
                await stream.thinking(
                    response,
                    source="chat",
                    stage="acting",
                    metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_output"}),
                )
            await stream.progress(
                self._text(
                    zh="本轮不需要调用工具。",
                    en="No tool call was needed for this turn.",
                ),
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "progress"}),
            )
            await stream.progress(
                "",
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(
                    trace_meta,
                    {"trace_kind": "call_status", "call_state": "complete"},
                ),
            )
            return tool_traces

        tool_args = self._augment_tool_kwargs(action, action_input, context, thinking_text)
        if response:
            await stream.thinking(
                response,
                source="chat",
                stage="acting",
                metadata=merge_trace_metadata(trace_meta, {"trace_kind": "llm_output"}),
            )
        await stream.tool_call(
            tool_name=action,
            args=tool_args,
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "tool_call", "trace_role": "tool", "tool_name": action},
            ),
        )

        try:
            result = await self._execute_tool_call(
                action,
                tool_args,
                stream=stream,
                retrieve_meta=self._retrieve_trace_metadata(
                    trace_meta,
                    context=context,
                    tool_call_id="chat-react-tool",
                    tool_name=action,
                    tool_index=0,
                    tool_args=tool_args,
                ),
            )
            result_text = result["result_text"]
            success = result["success"]
            sources = result["sources"]
            metadata = result["metadata"]
        except Exception:
            logger.error("Fallback tool %s failed", action, exc_info=True)
            result_text = self._text(
                zh=f"执行工具 {action} 时发生未知错误。",
                en=f"An unknown error occurred while executing {action}.",
            )
            success = False
            sources = []
            metadata = {"error": result_text}

        await stream.tool_result(
            tool_name=action,
            result=result_text,
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "tool_result", "trace_role": "tool", "tool_name": action},
            ),
        )
        tool_traces.append(
            ToolTrace(
                name=action,
                arguments=tool_args,
                result=result_text,
                success=success,
                sources=sources,
                metadata=metadata,
            )
        )
        await stream.progress(
            "",
            source="chat",
            stage="acting",
            metadata=merge_trace_metadata(
                trace_meta,
                {"trace_kind": "call_status", "call_state": "complete"},
            ),
        )

        return tool_traces

    def _build_messages(
        self,
        context: UnifiedContext,
        system_prompt: str,
        user_content: str,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if context.memory_context:
            messages.append({"role": "system", "content": context.memory_context})
        for item in context.conversation_history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant", "system"} and isinstance(content, (str, list)):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_content})
        return messages

    def _prepare_messages_with_attachments(
        self,
        messages: list[dict[str, Any]],
        context: UnifiedContext,
    ) -> tuple[list[dict[str, Any]], bool]:
        mm_result = prepare_multimodal_messages(
            messages,
            context.attachments,
            binding=self.binding,
            model=self.model,
        )
        return mm_result.messages, mm_result.images_stripped

    async def _stream_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ):
        output_chars = 0
        async for chunk in llm_stream(
            prompt="",
            system_prompt="",
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            messages=messages,
            **self._completion_kwargs(max_tokens=max_tokens),
        ):
            output_chars += len(chunk)
            yield chunk
        input_chars = sum(len(str(m.get("content", ""))) for m in messages)
        est_input = int(input_chars / 3.5)
        est_output = int(output_chars / 3.5)
        self._usage["prompt_tokens"] += est_input
        self._usage["completion_tokens"] += est_output
        self._usage["total_tokens"] += est_input + est_output
        self._usage["calls"] += 1

    def _build_openai_client(self):
        http_client = None
        if os.getenv("DISABLE_SSL_VERIFY", "").lower() in ("true", "1", "yes"):
            http_client = httpx.AsyncClient(verify=False)  # nosec B501

        if self.binding == "azure_openai" or (self.binding == "openai" and self.api_version):
            return AsyncAzureOpenAI(
                api_key=self.api_key or "sk-no-key-required",
                azure_endpoint=self.base_url,
                api_version=self.api_version,
                http_client=http_client,
            )
        return AsyncOpenAI(
            api_key=self.api_key or "sk-no-key-required",
            base_url=self.base_url or None,
            http_client=http_client,
        )

    def _completion_kwargs(self, max_tokens: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"temperature": 0.2}
        if self.model:
            kwargs.update(get_token_limit_kwargs(self.model, max_tokens))
        return kwargs

    def _can_use_native_tool_calling(self) -> bool:
        if not supports_tools(self.binding, self.model):
            return False
        return self.binding not in {"anthropic", "claude", "ollama", "lm_studio", "vllm", "llama_cpp"}

    def _normalize_enabled_tools(self, enabled_tools: list[str] | None) -> list[str]:
        selected = enabled_tools or []
        return [
            tool.name
            for tool in self.registry.get_enabled(selected)
            if tool.name not in CHAT_EXCLUDED_TOOLS
        ]

    @staticmethod
    def _extract_answer_now_context(context: UnifiedContext) -> dict[str, Any] | None:
        raw = context.config_overrides.get("answer_now_context")
        if not isinstance(raw, dict):
            return None
        original_user_message = str(raw.get("original_user_message") or "").strip()
        if not original_user_message:
            return None
        return raw

    async def _execute_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        stream: StreamBus | None = None,
        retrieve_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async def _event_sink(
            event_type: str,
            message: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> None:
            if stream is None or retrieve_meta is None or not message:
                return
            await stream.progress(
                message,
                source="chat",
                stage="acting",
                metadata=derive_trace_metadata(
                    retrieve_meta,
                    trace_kind=str(event_type or "tool_log"),
                    **(metadata or {}),
                ),
            )

        if stream is not None and retrieve_meta is not None:
            query = str(retrieve_meta.get("query") or tool_args.get("query") or "").strip()
            await stream.progress(
                f"Query: {query}" if query else self._text(zh="开始检索", en="Starting retrieval"),
                source="chat",
                stage="acting",
                metadata=derive_trace_metadata(
                    retrieve_meta,
                    trace_kind="call_status",
                    call_state="running",
                ),
            )
        try:
            result = await self.registry.execute(
                tool_name,
                event_sink=_event_sink if retrieve_meta is not None else None,
                **tool_args,
            )
            if stream is not None and retrieve_meta is not None:
                await stream.progress(
                    f"Retrieve complete ({len(result.content)} chars)",
                    source="chat",
                    stage="acting",
                    metadata=derive_trace_metadata(
                        retrieve_meta,
                        trace_kind="call_status",
                        call_state="complete",
                    ),
                )
            return {
                "result_text": result.content
                or self._text(
                    zh="工具执行完成，但没有返回文本内容。",
                    en="The tool completed without returning text output.",
                ),
                "success": result.success,
                "sources": result.sources,
                "metadata": result.metadata,
            }
        except Exception as exc:
            logger.error("Tool %s failed", tool_name, exc_info=True)
            if stream is not None and retrieve_meta is not None:
                await stream.error(
                    f"Retrieve failed: {exc}",
                    source="chat",
                    stage="acting",
                    metadata=derive_trace_metadata(
                        retrieve_meta,
                        trace_kind="call_status",
                        call_state="error",
                        error=str(exc),
                    ),
                )
            return {
                "result_text": f"Error executing {tool_name}: {exc}",
                "success": False,
                "sources": [],
                "metadata": {"error": str(exc)},
            }

    def _tool_trace_metadata(
        self,
        trace_meta: dict[str, Any],
        *,
        context: UnifiedContext,
        tool_call_id: str,
        tool_name: str,
        tool_index: int,
        trace_kind: str = "tool_call",
    ) -> dict[str, Any]:
        return merge_trace_metadata(
            trace_meta,
            {
                "trace_kind": trace_kind,
                "trace_role": "tool",
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "tool_index": tool_index,
                "session_id": context.session_id,
                "turn_id": str(context.metadata.get("turn_id", "")),
            },
        )

    def _retrieve_trace_metadata(
        self,
        trace_meta: dict[str, Any],
        *,
        context: UnifiedContext,
        tool_call_id: str,
        tool_name: str,
        tool_index: int,
        tool_args: dict[str, Any],
    ) -> dict[str, Any] | None:
        if tool_name != "rag":
            return None
        return derive_trace_metadata(
            trace_meta,
            call_id=new_call_id(f"chat-retrieve-{tool_index + 1}"),
            label=self._text(zh="Retrieve", en="Retrieve"),
            call_kind="rag_retrieval",
            trace_role="retrieve",
            trace_group="retrieve",
            trace_id=f"{trace_meta.get('trace_id', 'chat')}-retrieve-{tool_index + 1}",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_index=tool_index,
            session_id=context.session_id,
            turn_id=str(context.metadata.get("turn_id", "")),
            query=str(tool_args.get("query", "") or ""),
        )

    def _augment_tool_kwargs(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: UnifiedContext,
        thinking_text: str,
    ) -> dict[str, Any]:
        from deeptutor.services.path_service import get_path_service

        kwargs = dict(args)
        turn_id = str(context.metadata.get("turn_id", "") or "").strip()
        task_dir = None
        if turn_id:
            task_dir = get_path_service().get_task_workspace("chat", turn_id)
        if tool_name == "rag" and context.knowledge_bases:
            kwargs.setdefault("kb_name", context.knowledge_bases[0])
            kwargs.setdefault("mode", "hybrid")
        elif tool_name == "code_execution":
            kwargs.setdefault("intent", context.user_message)
            kwargs.setdefault("timeout", 30)
            kwargs.setdefault("feature", "chat")
            kwargs.setdefault("session_id", context.session_id)
            kwargs.setdefault("turn_id", turn_id)
            if task_dir is not None:
                kwargs.setdefault("workspace_dir", str(task_dir / "code_runs"))
        elif tool_name in {"reason", "brainstorm"}:
            kwargs.setdefault("context", thinking_text)
        elif tool_name == "paper_search":
            kwargs.setdefault("max_results", 3)
            kwargs.setdefault("years_limit", 3)
            kwargs.setdefault("sort_by", "relevance")
        elif tool_name == "web_search":
            kwargs.setdefault("query", context.user_message)
            if task_dir is not None:
                kwargs.setdefault("output_dir", str(task_dir / "web_search"))
        return kwargs

    def _acting_system_prompt(self, enabled_tools: list[str], context: UnifiedContext) -> str:
        kb_name = context.knowledge_bases[0] if context.knowledge_bases else ""
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
            kb_name=kb_name,
        )
        tool_aliases = self.registry.build_prompt_text(
            enabled_tools,
            format="aliases",
            language=self.language,
        )
        return self._text(
            zh=(
                "你是 DeepTutor 的工具调用代理。你的任务是根据用户问题和前序 thinking，"
                "从当前已启用的工具中自主选择必要工具并调用。"
                "\n\n规则：\n"
                "1. 先完整审视所有已启用工具，再决定最有帮助的工具组合；不要只盯住单个工具。\n"
                "2. 对于需要定义、事实核验、外部资料、论文、计算、推理等不同信息面的复杂问题，优先并行调用多个互补工具来覆盖这些信息面。\n"
                "3. 只调用真正有帮助的工具，但只要工具能显著提升答案质量，就应充分调用。\n"
                "4. 参数要具体、可执行，优先使用用户原问题中的关键信息，必要时针对不同工具改写成最适合它的查询。\n"
                "5. 如果信息已经足够，可以不调用工具。\n"
                "6. 不要输出最终回答给学生；这里只负责工具选择与调用。\n"
                f"7. 单轮最多并行调用 {MAX_PARALLEL_TOOL_CALLS} 个工具；如果有多个互补工具都相关，优先在同一轮一起调用。\n\n"
                f"当前可用工具：\n{tool_list or '- 无'}\n\n"
                f"工具使用提示：\n{tool_aliases or '- 无'}"
            ),
            en=(
                "You are DeepTutor's tool-using agent. Based on the user request and prior thinking, "
                "autonomously choose and call only the enabled tools that are truly helpful."
                "\n\nRules:\n"
                "1. Review the full enabled tool list before deciding; do not fixate on a single tool too early.\n"
                "2. For complex questions that need definitions, grounding, outside evidence, papers, calculation, or deeper reasoning, prefer calling multiple complementary tools in parallel so each one covers a distinct information need.\n"
                "3. Call tools only when they add value, but when they materially improve answer quality you should use them fully.\n"
                "4. Use concrete, executable arguments grounded in the user's request, and adapt the wording when different tools need different query styles.\n"
                "5. If enough evidence already exists, you may skip tool use.\n"
                "6. Do not produce the final student-facing answer here; this stage is only for tool use.\n"
                f"7. At most {MAX_PARALLEL_TOOL_CALLS} tools may run in parallel in one turn; if several complementary tools are relevant, prefer issuing them together in the same turn.\n\n"
                f"Enabled tools:\n{tool_list or '- none'}\n\n"
                f"Tool usage notes:\n{tool_aliases or '- none'}"
            ),
        )

    def _react_fallback_system_prompt(self, tool_table: str) -> str:
        return self._text(
            zh=(
                "你是 DeepTutor 的 ReAct 工具代理。你必须只输出一个 JSON 对象，不要输出其他文本。\n\n"
                "JSON 格式：\n"
                '{\n  "action": "<tool_name_or_done>",\n  "action_input": { ... }\n}\n\n'
                "可选动作如下：\n"
                f"{tool_table}\n\n"
                "先基于用户问题和可用工具列表判断是否真的需要工具；若需要，请选择最能补足关键信息缺口的那个工具。"
                "如果不需要工具，请输出 action=done。"
            ),
            en=(
                "You are DeepTutor's ReAct tool agent. Output exactly one JSON object and nothing else.\n\n"
                "JSON format:\n"
                '{\n  "action": "<tool_name_or_done>",\n  "action_input": { ... }\n}\n\n'
                "Available actions:\n"
                f"{tool_table}\n\n"
                "Decide from the user request and the full enabled tool list whether tool use is truly needed; if it is, choose the single tool that best closes the most important information gap. "
                "If no tool is needed, set action=done."
            ),
        )

    def _thinking_system_prompt(self, enabled_tools: list[str], context: UnifiedContext) -> str:
        kb_name = context.knowledge_bases[0] if context.knowledge_bases else ""
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
            kb_name=kb_name,
        )
        return self._text(
            zh=(
                "你是 DeepTutor 的 thinking 阶段。请先分析用户问题，判断目标、已知条件、缺失信息，"
                "并思考是否需要后续工具调用。这里输出的是 tutor 的内部思路，不是最终回复。"
                "\n\n要求：\n"
                "1. 流式、简洁、自然地输出思考过程。\n"
                "2. 可以明确指出你预计会使用哪些工具，但此阶段不要真正调用工具。\n"
                "3. 如果用户开启了工具，请结合可用工具来规划。\n\n"
                f"当前启用工具：\n{tool_list or '- 无'}"
            ),
            en=(
                "You are DeepTutor's thinking stage. Analyze the user's request, identify goals, constraints, "
                "missing information, and whether later tool use is needed. This is the tutor's internal reasoning, "
                "not the final answer.\n\n"
                "Requirements:\n"
                "1. Stream concise, natural reasoning.\n"
                "2. You may mention which tools seem useful, but do not call tools in this stage.\n"
                "3. If tools are enabled, factor them into your plan.\n\n"
                f"Enabled tools:\n{tool_list or '- none'}"
            ),
        )

    def _observing_system_prompt(self, enabled_tools: list[str]) -> str:
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
        )
        return self._text(
            zh=(
                "你是 DeepTutor 的 observing 阶段。请基于 thinking 和 acting 阶段的输出，"
                "整理一份内部观察总结，供最终回答阶段使用。不要直接回答学生。"
                "\n\n优先总结：\n"
                "1. 已确认的事实与结论\n"
                "2. 工具结果带来的关键证据\n"
                "3. 仍需在最终回答中解释清楚的点\n\n"
                f"本轮可用工具背景：\n{tool_list or '- 无'}"
            ),
            en=(
                "You are DeepTutor's observing stage. Based on the outputs from the thinking and acting stages, "
                "prepare an internal synthesis for the final answer stage. Do not answer the student directly.\n\n"
                "Prioritize:\n"
                "1. confirmed facts and conclusions\n"
                "2. key evidence from tool outputs\n"
                "3. what the final answer must explain clearly\n\n"
                f"Tool context for this turn:\n{tool_list or '- none'}"
            ),
        )

    def _responding_system_prompt(self, enabled_tools: list[str]) -> str:
        tool_list = self.registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
        )
        return self._text(
            zh=(
                "你是 DeepTutor 的最终回答阶段。请根据 observation 和工具结果，"
                "给用户一个清晰、直接、结构良好的正式答复。"
                "\n\n要求：\n"
                "1. 只输出面向用户的正式回答。\n"
                "2. 不要暴露内部链路、思考过程或工具编排。\n"
                "3. 若工具结果提供了证据或限制，请自然融入答案。\n\n"
                f"本轮工具背景：\n{tool_list or '- 无'}"
            ),
            en=(
                "You are DeepTutor's final response stage. Use the observation and tool evidence to provide a clear, "
                "direct, well-structured answer to the user.\n\n"
                "Requirements:\n"
                "1. Output only the final user-facing answer.\n"
                "2. Do not reveal the internal chain, reasoning, or tool orchestration.\n"
                "3. Naturally integrate evidence or limits surfaced by the tools.\n\n"
                f"Tool context for this turn:\n{tool_list or '- none'}"
            ),
        )

    def _acting_user_prompt(self, context: UnifiedContext, thinking_text: str) -> str:
        return self._text(
            zh=(
                f"用户问题：\n{context.user_message}\n\n"
                f"{self._labeled_block('Thinking', thinking_text)}\n\n"
                "请先基于问题与全部可用工具，判断有哪些信息缺口需要工具补足。"
                f"如果需要，请尽量在同一轮并行调用多个互补工具，但总数不要超过 {MAX_PARALLEL_TOOL_CALLS} 个。"
            ),
            en=(
                f"User request:\n{context.user_message}\n\n"
                f"{self._labeled_block('Thinking', thinking_text)}\n\n"
                "First reason about which information gaps require tools, using the full enabled tool list. "
                f"If tool use is needed, prefer calling multiple complementary tools in the same turn, up to {MAX_PARALLEL_TOOL_CALLS} total."
            ),
        )

    def _format_tool_traces(self, tool_traces: list[ToolTrace]) -> str:
        if not tool_traces:
            return self._text(
                zh="本轮没有实际工具调用。",
                en="No tools were actually called in this turn.",
            )

        blocks: list[str] = []
        for idx, trace in enumerate(tool_traces, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"{idx}. {trace.name}",
                        f"arguments: {json.dumps(trace.arguments, ensure_ascii=False)}",
                        f"success: {trace.success}",
                        f"result: {self._truncate_tool_result(trace.result)}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _format_answer_now_events(self, events: Any) -> str:
        if not isinstance(events, list) or not events:
            return self._text(
                zh="没有可用的中间执行记录。",
                en="No intermediate execution trace was provided.",
            )

        lines: list[str] = []
        for index, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "event").strip()
            stage = str(event.get("stage") or "").strip()
            content = str(event.get("content") or "").strip()
            metadata = event.get("metadata")
            label_parts = [event_type]
            if stage:
                label_parts.append(stage)
            line = f"{index}. {' / '.join(label_parts)}"
            if content:
                line += f": {self._truncate_tool_result(content, limit=1200)}"
            if isinstance(metadata, dict):
                tool_name = str(metadata.get("tool_name") or metadata.get("tool") or "").strip()
                if tool_name:
                    line += f" [tool={tool_name}]"
            lines.append(line)

        if not lines:
            return self._text(
                zh="没有可用的中间执行记录。",
                en="No intermediate execution trace was provided.",
            )
        return "\n".join(lines)

    @staticmethod
    def _message_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(texts).strip()
        return str(content or "")

    @staticmethod
    def _truncate_tool_result(content: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
        cleaned = content.strip()
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."

    def _images_stripped_notice(self) -> str:
        return self._text(
            zh=(
                f"当前模型 `{self.model}` 不支持图像输入，thinking 阶段已忽略本轮图片附件。"
            ),
            en=(
                f"The current model `{self.model}` does not support image input, so image attachments were ignored in the thinking stage."
            ),
        )

    @staticmethod
    def _labeled_block(label: str, content: str) -> str:
        return f"[{label}]\n{content.strip() if content.strip() else '(empty)'}"

    def _text(self, *, zh: str, en: str) -> str:
        return zh if self.language == "zh" else en
