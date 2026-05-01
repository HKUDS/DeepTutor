"""
Deep Solve Capability
=====================

Multi-agent problem solving pipeline: Plan -> ReAct -> Write.
Wraps the existing ``MainSolver``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from deeptutor.capabilities.request_contracts import get_capability_request_schema
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import derive_trace_metadata, merge_trace_metadata


def _image_attachments(attachments: list[Any]) -> list[Any]:
    """Return the image attachments to forward into multimodal LLM calls."""
    return [att for att in attachments or [] if getattr(att, "type", "") == "image"]


class DeepSolveCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="deep_solve",
        description="Multi-agent problem solving (Plan -> ReAct -> Write).",
        stages=["planning", "reasoning", "writing"],
        tools_used=["rag", "web_search", "code_execution", "reason"],
        cli_aliases=["solve"],
        request_schema=get_capability_request_schema("deep_solve"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        from deeptutor.agents.solve.main_solver import MainSolver
        from deeptutor.capabilities._answer_now import extract_answer_now_context
        from deeptutor.services.llm.config import get_llm_config

        answer_now_payload = extract_answer_now_context(context)
        if answer_now_payload is not None:
            await self._run_answer_now(context, stream, answer_now_payload)
            return

        llm_config = get_llm_config()
        detailed = context.config_overrides.get("detailed_answer", True)
        enabled_tools = list(
            self.manifest.tools_used if context.enabled_tools is None else context.enabled_tools
        )
        rag_enabled = "rag" in enabled_tools
        kb_name = context.knowledge_bases[0] if rag_enabled and context.knowledge_bases else None

        # Consistency normalization: if rag is requested but no KB is
        # actually available, strip "rag" from the enabled tool set so the
        # ReAct loop never exposes an action that would fail at runtime.
        if rag_enabled and not kb_name:
            enabled_tools = [tool for tool in enabled_tools if tool != "rag"]
            rag_enabled = False
            await stream.progress(
                message=(
                    "RAG was enabled but no knowledge base is selected; "
                    "the rag tool is disabled for this turn."
                ),
                source=self.name,
                stage="planning",
                metadata={"trace_kind": "warning", "reason": "rag_without_kb"},
            )

        solver = MainSolver(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=llm_config.api_version,
            kb_name=kb_name,
            language=context.language,
            enabled_tools=enabled_tools,
            disable_planner_retrieve=not (rag_enabled and kb_name),
        )
        await solver.ainit()

        # Also bridge the explicit progress callback
        def _normalize_stage(stage: str) -> str:
            mapping = {
                "plan": "planning",
                "planning": "planning",
                "solve": "reasoning",
                "solving": "reasoning",
                "reasoning": "reasoning",
                "write": "writing",
                "writing": "writing",
            }
            return mapping.get(stage, stage or "reasoning")

        async def _trace_bridge(update: dict) -> None:
            event = str(update.get("event", "") or "")
            stage = str(update.get("phase") or update.get("stage") or "reasoning")
            stage = _normalize_stage(stage)
            base_metadata = {
                key: value
                for key, value in update.items()
                if key
                not in {"event", "state", "response", "chunk", "result", "tool_args", "tool_name"}
            }

            if event == "llm_call":
                state = str(update.get("state", "running"))
                label = str(update.get("label", "") or "")
                if state == "running":
                    await stream.progress(
                        message=label,
                        source=self.name,
                        stage=stage,
                        metadata=merge_trace_metadata(
                            base_metadata,
                            {"trace_kind": "call_status", "call_state": "running"},
                        ),
                    )
                    return
                if state == "streaming":
                    chunk = str(update.get("chunk", "") or "")
                    if chunk:
                        await stream.thinking(
                            chunk,
                            source=self.name,
                            stage=stage,
                            metadata=merge_trace_metadata(
                                base_metadata,
                                {"trace_kind": "llm_chunk"},
                            ),
                        )
                    return
                if state == "complete":
                    was_streaming = update.get("streaming", False)
                    if not was_streaming:
                        response = str(update.get("response", "") or "")
                        if response:
                            await stream.thinking(
                                response,
                                source=self.name,
                                stage=stage,
                                metadata=merge_trace_metadata(
                                    base_metadata,
                                    {"trace_kind": "llm_output"},
                                ),
                            )
                    await stream.progress(
                        message="",
                        source=self.name,
                        stage=stage,
                        metadata=merge_trace_metadata(
                            base_metadata,
                            {"trace_kind": "call_status", "call_state": "complete"},
                        ),
                    )
                    return
                if state == "error":
                    await stream.error(
                        str(update.get("response", "") or "LLM call failed."),
                        source=self.name,
                        stage=stage,
                        metadata=merge_trace_metadata(
                            base_metadata,
                            {"trace_kind": "call_status", "call_state": "error"},
                        ),
                    )
                    return

            if event == "llm_observation":
                response = str(update.get("response", "") or "")
                if response:
                    await stream.observation(
                        response,
                        source=self.name,
                        stage=stage,
                        metadata=derive_trace_metadata(
                            base_metadata,
                            trace_role="observe",
                            trace_kind="observation",
                        ),
                    )
                return

            if event == "tool_call":
                await stream.tool_call(
                    tool_name=str(update.get("tool_name", "") or "tool"),
                    args=update.get("tool_args", {}) or {},
                    source=self.name,
                    stage=stage,
                    metadata=derive_trace_metadata(
                        base_metadata,
                        trace_role="tool",
                        trace_kind="tool_call",
                    ),
                )
                return

            if event == "tool_result":
                await stream.tool_result(
                    tool_name=str(update.get("tool_name", "") or "tool"),
                    result=str(update.get("result", "") or ""),
                    source=self.name,
                    stage=stage,
                    metadata=derive_trace_metadata(
                        base_metadata,
                        trace_role="tool",
                        trace_kind="tool_result",
                        sources=update.get("sources", []) or [],
                    ),
                )
                return

            if event == "tool_log":
                message = str(update.get("message", "") or "")
                if not message:
                    return
                await stream.progress(
                    message=message,
                    source=self.name,
                    stage=stage,
                    metadata=derive_trace_metadata(
                        base_metadata,
                        trace_role="retrieve",
                        trace_group="retrieve",
                        trace_kind=str(update.get("trace_kind", "tool_log") or "tool_log"),
                    ),
                )
                return

        def _progress_bridge(stage: str, progress: dict):
            async def _emit() -> None:
                status = str(progress.get("status", stage))
                detail_parts = []
                if "step_id" in progress:
                    detail_parts.append(f"[{progress['step_id']}]")
                if "step_target" in progress:
                    detail_parts.append(str(progress["step_target"])[:80])
                detail = " ".join(detail_parts)
                msg = f"{status}: {detail}" if detail else status
                await stream.progress(
                    message=msg,
                    source=self.name,
                    stage=_normalize_stage(stage),
                )

            try:
                asyncio.get_running_loop().create_task(_emit())
            except RuntimeError:
                pass

        setattr(solver, "_send_progress_update", _progress_bridge)
        if hasattr(solver, "set_trace_callback"):
            solver.set_trace_callback(_trace_bridge)

        # Content callback — streams writer tokens to the main chat area
        content_streamed = False

        async def _content_sink(chunk: str) -> None:
            nonlocal content_streamed
            content_streamed = True
            await stream.content(
                chunk,
                source=self.name,
                stage="writing",
            )

        setattr(solver, "_content_callback", _content_sink)

        try:
            result = await solver.solve(
                question=context.user_message,
                attachments=_image_attachments(context.attachments),
                verbose=False,
                detailed=detailed,
                conversation_context=str(
                    context.metadata.get("conversation_context_text", "") or ""
                ).strip(),
            )

            final_answer = result.get("final_answer", "")

            if final_answer and not content_streamed:
                async with stream.stage("writing", source=self.name):
                    await stream.content(final_answer, source=self.name, stage="writing")

            await stream.result(
                {
                    "response": final_answer,
                    "output_dir": result.get("output_dir", ""),
                    "metadata": result.get("metadata", {}),
                },
                source=self.name,
            )
        except Exception as exc:
            # Check if it's a clarification-needed exception from our pipeline
            exc_name = type(exc).__name__
            if exc_name == "QuestionNeedsClarification":
                clarification_msg = str(exc)
                await stream.error(
                    clarification_msg,
                    source=self.name,
                    stage="planning",
                    metadata={
                        "needs_clarification": True,
                        "question_issues": getattr(exc, "question_issues", []),
                        "trace_kind": "clarification_required",
                    },
                )
                # Return a special result so the orchestrator doesn't treat it as a failure
                await stream.result(
                    {
                        "response": "",
                        "clarification_required": True,
                        "clarification_message": clarification_msg,
                        "question_issues": getattr(exc, "question_issues", []),
                    },
                    source=self.name,
                )
                return
            raise

    async def _run_answer_now(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        payload: dict[str, Any],
    ) -> None:
        """
        Fast-path for ``deep_solve``: skip Plan + ReAct, jump straight into
        the writer with whatever reasoning trace has streamed so far.

        The result payload preserves the same envelope shape as a normal
        ``deep_solve`` turn (``response`` + ``metadata``) so the frontend
        renders it identically.
        """
        from deeptutor.capabilities._answer_now import (
            build_answer_now_trace_metadata,
            format_trace_summary,
            join_chunks,
            labeled_block,
            load_answer_now_prompts,
            make_skip_notice,
            stream_synthesis,
        )

        original = str(payload.get("original_user_message") or context.user_message).strip()
        partial = str(payload.get("partial_response") or "").strip()
        trace_summary = format_trace_summary(payload.get("events"), language=context.language)

        prompts = load_answer_now_prompts("solve", context.language)
        system_prompt = str(prompts.get("system", "")).strip()
        user_prompt = str(prompts.get("user_template", "")).format(
            original=original,
            current_draft=labeled_block("Current Draft", partial),
            execution_trace=labeled_block("Execution Trace", trace_summary),
        )
        notice_label = "Writing"

        trace_meta = build_answer_now_trace_metadata(
            capability=self.name, phase="writing", label="Answer now"
        )

        notice = make_skip_notice(
            capability=self.name,
            language=context.language,
            stages_skipped=["planning", "reasoning"],
        )

        async with stream.stage("writing", source=self.name, metadata=trace_meta):
            if notice:
                await stream.content(
                    notice + "\n\n",
                    source=self.name,
                    stage="writing",
                )
            chunks: list[str] = []
            async for chunk in stream_synthesis(
                stream=stream,
                source=self.name,
                stage="writing",
                trace_meta=trace_meta,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2000,
            ):
                chunks.append(chunk)

        final_answer = join_chunks(chunks)
        await stream.result(
            {
                "response": (notice + "\n\n" + final_answer).strip() if notice else final_answer,
                "output_dir": "",
                "metadata": {
                    "answer_now": True,
                    "synthesizer": notice_label,
                },
            },
            source=self.name,
        )
