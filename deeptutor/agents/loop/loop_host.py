"""Provider/tool/capability effects shared by both scheduler implementations.

This migration adapter owns conversation data, never loop scheduling decisions.
It runs inside the originating Python task to preserve account/workspace scopes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deeptutor.runtime.agentic.messages import (
    assistant_message_with_tool_calls,
    extend_transient_model_messages,
)
from deeptutor.runtime.agentic.tool_dispatch import DispatchOutcome
from deeptutor.services.llm import LLMReasoningBudgetExhausted, finish_was_truncated

from . import loop_state as values

if TYPE_CHECKING:
    from .agent_loop import AgentLoop


class AgentLoopHost:
    def __init__(
        self,
        loop: AgentLoop,
        messages: list[dict[str, Any]],
        state: values.AgentLoopState,
        checkpoint_boundary: int,
    ) -> None:
        self.loop = loop
        self.pipeline = loop.pipeline
        self.context = loop.context
        self.stream = loop.stream
        self.messages = messages
        self.state = state
        self.checkpoint_boundary = checkpoint_boundary
        self.continued: list[str] = []
        self.result: values.LLMCallResult | None = None
        self.dispatch: DispatchOutcome | None = None
        self.outcome: values.LoopOutcome | None = None
        self.redirect = ""
        self.override: str | None = None
        self.override_after_tools = False
        self.recovery_tools: frozenset[str] | None = None
        self.recovery_schemas: list[dict[str, Any]] | None = None

    async def invoke(self, operation: str, args: dict[str, Any], state: dict[str, Any]) -> Any:
        operations = {
            "prepare_recovery": self.prepare_recovery,
            "begin_settlement": self.begin_settlement,
            "call_round": self.call_round,
            "continue_truncated": self.continue_truncated,
            "raise_reasoning_budget": self.raise_reasoning_budget,
            "recover_empty": self.recover_empty,
            "check_finish": self.check_finish,
            "redirect_finish": self.redirect_finish,
            "reject_finish": self.reject_finish,
            "finish": self.finish,
            "dispatch_tools": self.dispatch_tools,
            "resolve_pause": self.resolve_pause,
            "after_tools": self.after_tools,
            "terminate": self.terminate,
            "forced_finish": self.forced_finish,
        }
        if operation not in operations or not isinstance(args, dict):
            raise ValueError("Unknown chat host operation")
        self.sync_state(state)
        return await operations[operation](**args)

    def sync_state(self, state: dict[str, Any]) -> None:
        for name in (
            "rounds",
            "exploration_rounds",
            "settlement_rounds",
            "tool_steps",
            "reasoning_budget_recoveries",
        ):
            value = state.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("Invalid chat loop state")
            setattr(self.state, name, value)

    async def warning(self, key: str, default: str) -> None:
        await self.stream.progress(
            self.pipeline._t(key, default=default),
            source=self.loop.source,
            stage=self.loop.stage,
            metadata={"trace_kind": "warning"},
        )

    async def prepare_recovery(self) -> dict[str, bool]:
        recovery = self.pipeline._capability_settlement_recovery(self.context)
        if recovery is None:
            return {"available": False, "rejected": False}
        instruction, names = recovery
        self.recovery_schemas = [
            schema
            for schema in self.loop.tool_schemas or []
            if (schema.get("function") or {}).get("name") in names
        ]
        self.recovery_tools = frozenset(
            schema["function"]["name"] for schema in self.recovery_schemas
        )
        if not self.recovery_tools:
            return {"available": False, "rejected": True}
        self.loop._append_loop_instruction(self.messages, instruction)
        return {"available": True, "rejected": False}

    async def begin_settlement(self) -> None:
        await self.loop._begin_settlement(self.messages)

    async def read_inbox(self) -> None:
        """Hand the model what the learner sent while the turn was running.

        Read at every step boundary — before each model call, so after the
        tool batch in flight — and appended as the learner's own words; the
        trace row puts the message in the transcript where it was read.
        """
        drain = self.context.runtime.drain_user_inputs
        inputs = drain() if drain is not None else []
        if not inputs:
            return
        lead = self.pipeline._t(
            "loop.user_sent_while_working",
            default=(
                "[The user sent this while you were working. Take it into account from "
                "here on: answer it, or adjust what you are doing.]"
            ),
        )
        said = "\n\n".join(str(item["content"]) for item in inputs)
        self.loop._append_loop_instruction(self.messages, f"{lead}\n{said}")
        await self.stream.progress(
            "",
            source=self.loop.source,
            stage=self.loop.stage,
            metadata={
                "trace_kind": "user_input",
                "user_inputs": [
                    {"command_id": item["command_id"], "content": item["content"]}
                    for item in inputs
                ],
            },
        )

    async def call_round(self, *, settling: bool, first: bool) -> dict[str, bool]:
        self.override_after_tools = False
        await self.read_inbox()
        self.result = await self.loop._call_llm(
            messages=self.messages,
            label=self.pipeline._t("labels.final_response", default="Final response")
            if settling
            else self.pipeline._t("labels.exploring", default="Exploring"),
            call_kind="agent_loop_round",
            trace_role="response" if settling else "explore",
            max_tokens=self.pipeline.loop_max_tokens,
            tool_schemas=self.recovery_schemas
            if self.recovery_tools is not None
            else self.loop.tool_schemas,
            defer_visible_output=self.pipeline._capability_buffers_visible_output(self.context),
            tool_choice=self.pipeline.initial_tool_choice if first else None,
        )
        rejected = self.recovery_tools is not None and any(
            str(call.get("name") or "").strip() not in self.recovery_tools
            for call in self.result.tool_calls
        )
        if rejected:
            if self.result.deferred_chunk_metadata is None and self.result.visible_text:
                self.continued.append(self.result.visible_text)
            await self.loop._discard_deferred_output(self.result)
        return {
            "recoveryRejected": rejected,
            "hasTools": bool(self.result.tool_calls),
            "hasText": bool(self.loop._clean(self.result.text)),
            "truncated": finish_was_truncated(self.result.finish_reason),
            "reasoningBudgetExhausted": values._reasoning_budget_exhausted(
                self.result, self.pipeline.loop_max_tokens
            ),
        }

    async def raise_reasoning_budget(self) -> None:
        assert self.result is not None
        await self.loop._release_deferred_output(self.result)
        raise LLMReasoningBudgetExhausted(
            self.pipeline._t(
                "notices.reasoning_budget_exhausted",
                default=(
                    "The model exhausted its output budget on internal reasoning twice without "
                    "producing an answer or tool action. Please retry, lower reasoning effort, "
                    "or split the task into smaller steps."
                ),
            ),
            diagnostics={
                "rounds": self.state.rounds,
                "reasoning_chars": self.result.reasoning_chars,
                "completion_tokens": self.result.usage.get("completion_tokens"),
                "reasoning_tokens": self.result.usage.get("reasoning_tokens"),
            },
        )

    async def continue_truncated(self) -> None:
        result = self.result
        assert result is not None
        await self.loop._release_deferred_output(result)
        await self.warning(
            "notices.output_truncated",
            "The model output reached its token limit; asked it to continue.",
        )
        if result.visible_text:
            self.continued.append(result.visible_text)
        if values._has_replayable_assistant_state(result):
            self.messages.append(values._assistant_round_message(result))
        if result.visible_text:
            instruction = self.pipeline._t(
                "loop.continue_truncated",
                default=(
                    "Your previous response stopped at the token limit. Continue from where it ended "
                    "without repeating it, and complete the user-facing answer."
                ),
            )
        else:
            instruction = self.pipeline._t(
                "loop.continue_truncated_reasoning",
                default=(
                    "Your previous round spent its entire output budget on internal reasoning and hit "
                    "the token limit before writing anything — so there is nothing to continue from, "
                    "and reasoning it through again will end the same way. Act now instead: make the "
                    "tool call, or write the answer with the judgement you already have. Good enough "
                    "is required; optimal is not. Do not redesign or second-guess what you had already settled on."
                ),
            )
        self.loop._append_loop_instruction(self.messages, instruction)

    async def recover_empty(self, *, force: bool) -> None:
        assert self.result is not None
        await self.warning(
            "notices.empty_finish_nudged",
            "The round produced only internal reasoning; asked the model to continue.",
        )
        if values._has_replayable_assistant_state(self.result):
            self.messages.append(values._assistant_round_message(self.result))
        if force:
            instruction = self.pipeline._t(
                "loop.repeat_reasoning_only_nudge",
                default=(
                    "Your previous rounds produced only internal reasoning — no tool call and no "
                    "user-facing answer. Do not reason further. Select the most likely next action and produce it now."
                ),
            )
        else:
            instruction = self.pipeline._t(
                "loop.finish_empty_nudge",
                default=(
                    "Your previous round produced only internal reasoning — no tool call and no "
                    "user-facing answer. Continue now: either call the tools to execute your plan, "
                    "or write the final user-facing answer directly."
                ),
            )
        self.loop._append_loop_instruction(self.messages, instruction)

    async def check_finish(self) -> dict[str, bool]:
        assert self.result is not None
        text = self.loop._clean(self.result.text)
        self.redirect = self.pipeline._capability_finish_instruction(self.context, text)
        if self.redirect:
            if self.result.deferred_chunk_metadata is None and self.result.visible_text:
                self.continued.append(self.result.visible_text)
            await self.loop._discard_deferred_output(self.result)
            return {"redirect": True, "override": False}
        self.override = self.pipeline._capability_final_text_override(self.context, text)
        return {"redirect": False, "override": self.override is not None}

    async def redirect_finish(self) -> None:
        assert self.result is not None
        if self.result.text:
            self.messages.append(values._assistant_round_message(self.result))
        self.loop._append_loop_instruction(self.messages, self.redirect)

    async def reject_finish(self) -> None:
        self.outcome = await self.loop._reject_capability_finish()
        self.outcome.final_text = values._join_answer_parts(self.continued, "")

    async def finish(self, *, override: bool) -> None:
        result = self.result
        assert result is not None
        if override:
            assert self.override is not None
            if not self.override_after_tools:
                if result.deferred_chunk_metadata is None and result.visible_text:
                    self.continued.append(result.visible_text)
                    self.messages.append(values._assistant_round_message(result))
                    # An additive notice may include the original answer. That
                    # answer is already on screen, so publish only the addition.
                    if result.visible_text in self.override:
                        before, _, after = self.override.partition(result.visible_text)
                        self.override = (before + after).strip()
                        if self.override:
                            self.override = "\n\n" + self.override
                await self.loop._discard_deferred_output(result)
            if not self.context.capability_output.answer_published:
                await self.pipeline._emit_protocol_fallback_final_response(
                    self.stream, self.override
                )
                self.context.capability_output.answer_published = True
            self.outcome = await self.loop._finalize_finish(
                self.override,
                visible_text=self.override,
                continued_answer_parts=self.continued,
                allow_empty=True,
            )
            return
        await self.loop._release_deferred_output(result)
        self.messages.append(values._assistant_round_message(result))
        self.outcome = await self.loop._finalize_finish(
            self.loop._clean(result.text),
            visible_text=result.visible_text,
            continued_answer_parts=self.continued,
            provider_response_state=values._provider_response_state(
                result.response_output_items, result.reasoning_content, result.thinking_blocks
            ),
        )

    async def dispatch_tools(self) -> dict[str, bool]:
        result = self.result
        assert result is not None
        if finish_was_truncated(result.finish_reason):
            await self.warning(
                "notices.tool_call_truncated",
                (
                    "The model reached its output token limit while writing a tool call, so the call "
                    "may be incomplete. If this repeats, raise this capability's max tokens or pick "
                    "a model that reasons less."
                ),
            )
        tool_names = tuple(str(call.get("name") or "") for call in result.tool_calls)
        policy = self.pipeline._capability_tool_round_output_policy(
            self.context, self.loop._clean(result.text), tool_names
        )
        if policy == "discard":
            await self.loop._discard_deferred_output(result)
        else:
            await self.loop._release_deferred_output(result)
        assistant = assistant_message_with_tool_calls(
            result.text,
            result.tool_calls,
            reasoning_content=result.reasoning_content or None,
            thinking_blocks=result.thinking_blocks or None,
        )
        provider_state = values._provider_response_state(
            result.response_output_items, result.reasoning_content, result.thinking_blocks
        )
        if provider_state is not None:
            assistant["_provider_response_state"] = provider_state
        self.messages.append(assistant)
        self.dispatch = await self.pipeline._dispatch_tool_calls(
            tool_calls=result.tool_calls,
            context=self.context,
            stream=self.stream,
            iteration_index=self.state.tool_steps,
            stage=self.loop.stage,
        )
        self.state.sources.extend(self.dispatch.sources)
        self.messages.extend(self.dispatch.tool_messages)
        extend_transient_model_messages(
            self.loop._transient_model_messages, self.dispatch.model_messages
        )
        return {"pause": self.dispatch.pause}

    async def resolve_pause(self) -> bool:
        assert self.dispatch is not None
        resumed = await self.pipeline._await_user_reply_and_resolve(
            context=self.context, stream=self.stream, dispatch=self.dispatch
        )
        if not resumed:
            self.outcome = values.LoopOutcome(final_text="", completed=False)
        return resumed

    async def after_tools(self) -> dict[str, bool]:
        assert self.dispatch is not None
        self.checkpoint_boundary = self.loop._fold_context_checkpoint(
            messages=self.messages,
            dispatch=self.dispatch,
            checkpoint_boundary=self.checkpoint_boundary,
        )
        self.override = self.pipeline._capability_final_text_override(self.context, "")
        self.override_after_tools = True
        return {"override": self.override is not None, "terminate": self.dispatch.terminate}

    async def terminate(self) -> None:
        assert self.dispatch is not None
        payload = self.dispatch.terminate_payload or {}
        await self.pipeline._emit_terminator_final_response(self.stream, payload)
        self.outcome = values.LoopOutcome(
            final_text=values._join_answer_parts(self.continued, str(payload.get("content") or "")),
            completed=True,
        )

    async def forced_finish(self, *, reason: str, error: str) -> dict[str, int]:
        before = self.state.rounds
        self.outcome = await self.loop._forced_finish(
            self.messages,
            self.state,
            reason=reason,
            error=error,
            continued_answer_parts=self.continued,
        )
        return {"extraRounds": self.state.rounds - before}


async def run_loop_with_host(
    loop: AgentLoop,
    *,
    messages: list[dict[str, Any]],
    state: values.AgentLoopState,
    checkpoint_boundary: int,
    scheduler: str,
    config: dict[str, int],
) -> values.LoopOutcome:
    host = AgentLoopHost(loop, messages, state, checkpoint_boundary)
    if scheduler == "typescript":
        from deeptutor.runtime.ts_engine import get_engine_client

        final_state = await get_engine_client().run(host, config)
    else:
        from deeptutor.agents.loop.python_scheduler import run_loop

        final_state = await run_loop(host, config)
    host.sync_state(final_state)
    if host.outcome is None:
        raise RuntimeError("Chat scheduler completed without an outcome")
    return host.outcome
