"""
Visualize Capability
====================

Three-stage visualization pipeline: Analyze -> Generate -> Review.
Produces SVG or Chart.js code from user requests and conversation context.
"""

from __future__ import annotations

from typing import Any

from deeptutor.capabilities.request_contracts import get_capability_request_schema
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import merge_trace_metadata


class VisualizeCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="visualize",
        description="Generate SVG, Chart.js, or Mermaid visualizations.",
        stages=["analyzing", "generating", "reviewing"],
        tools_used=[],
        cli_aliases=["visualize", "viz"],
        request_schema=get_capability_request_schema("visualize"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        from deeptutor.agents.visualize.pipeline import VisualizePipeline
        from deeptutor.services.llm.config import get_llm_config

        llm_config = get_llm_config()
        history_context = str(
            context.metadata.get("conversation_context_text", "") or ""
        ).strip()
        render_mode = str(
            context.config_overrides.get("render_mode", "auto") or "auto"
        ).strip().lower()

        pipeline = VisualizePipeline(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=llm_config.api_version,
            language=context.language,
            trace_callback=self._build_trace_bridge(stream),
        )

        # Stage 1: Analyze
        async with stream.stage("analyzing", source=self.name):
            await stream.thinking(
                "Analyzing visualization requirements...",
                source=self.name,
                stage="analyzing",
            )
            analysis = await pipeline.run_analysis(
                user_input=context.user_message,
                history_context=history_context,
                render_mode=render_mode,
            )
            await stream.progress(
                message=f"Render type: {analysis.render_type} — {analysis.description}",
                source=self.name,
                stage="analyzing",
            )

        # Stage 2: Generate code
        async with stream.stage("generating", source=self.name):
            await stream.thinking(
                "Generating visualization code...",
                source=self.name,
                stage="generating",
            )
            code = await pipeline.run_code_generation(
                user_input=context.user_message,
                history_context=history_context,
                analysis=analysis,
            )
            await stream.progress(
                message="Code generated.",
                source=self.name,
                stage="generating",
            )

        # Stage 3: Review & optimise
        async with stream.stage("reviewing", source=self.name):
            await stream.thinking(
                "Reviewing and optimizing code...",
                source=self.name,
                stage="reviewing",
            )
            review = await pipeline.run_review(
                user_input=context.user_message,
                analysis=analysis,
                code=code,
            )
            final_code = review.optimized_code
            if review.changed:
                await stream.progress(
                    message=f"Code optimized: {review.review_notes}",
                    source=self.name,
                    stage="reviewing",
                )
            else:
                await stream.progress(
                    message="Code looks good — no changes needed.",
                    source=self.name,
                    stage="reviewing",
                )

        # Emit final content as a fenced code block for the chat area
        if analysis.render_type == "svg":
            lang_tag = "svg"
        elif analysis.render_type == "mermaid":
            lang_tag = "mermaid"
        else:
            lang_tag = "javascript"
        content_md = f"```{lang_tag}\n{final_code}\n```"
        await stream.content(content_md, source=self.name, stage="reviewing")

        # Structured result for the frontend viewer
        await stream.result(
            {
                "response": content_md,
                "render_type": analysis.render_type,
                "code": {
                    "language": lang_tag,
                    "content": final_code,
                },
                "analysis": analysis.model_dump(),
                "review": review.model_dump(),
            },
            source=self.name,
        )

    def _build_trace_bridge(self, stream: StreamBus):
        async def _trace_bridge(update: dict[str, Any]) -> None:
            event = str(update.get("event", "") or "")
            stage = str(update.get("phase") or update.get("stage") or "analyzing")
            base_metadata = {
                key: value
                for key, value in update.items()
                if key
                not in {"event", "state", "response", "chunk", "result", "tool_name", "tool_args"}
            }

            if event != "llm_call":
                return

            state = str(update.get("state", "running"))
            label = str(
                base_metadata.get("label", "") or stage.replace("_", " ").title()
            )
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
                    message=label,
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

        return _trace_bridge
