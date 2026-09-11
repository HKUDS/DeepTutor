"""Plugin-driven visualization capability built on the shared chat loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.trace import merge_trace_metadata
from deeptutor.i18n import StatusI18n
from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.runtime.request_contracts import (
    VisualizeRequestConfig,
    get_capability_request_schema,
    validate_visualize_request_config,
)
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.visualizers.protocol import (
    REQUESTED_VISUALIZER_KEY,
    VISUALIZATION_RESULT_KEY,
    VISUALIZE_MODE_KEY,
)
from deeptutor.visualizers.registry import get_visualizer_registry
from deeptutor.visualizers.store import VisualizerStoreError

logger = logging.getLogger(__name__)

# Default (English) copy for the tool-calling diagnosis, kept beside the code
# that emits it. StatusI18n prefers the localized strings in this capability's
# prompt files and falls back to these.
_TOOL_CALLING_DISABLED_WARNING = (
    "Tool calling is disabled for {target}, but a visualization only reaches "
    "the canvas through the submit_visualization tool call. Enable it in "
    "Settings → Models → LLM → Capabilities → Tool calling → Supported."
)
_NO_PAYLOAD_TOOL_CALLING_DISABLED = (
    "No visualization was committed: tool calling is disabled for {target}, so "
    "the model could not call submit_visualization — the only way to hand a "
    "payload to the canvas. Local servers (LM Studio, Ollama, vLLM, llama.cpp) "
    "are opted out by default; declare the model as tool-capable in "
    "Settings → Models → LLM → Capabilities → Tool calling → Supported, "
    "then run the visualization again."
)
_NO_PAYLOAD = "The visualization agent finished without a valid canvas payload."

# Stages exposed in the manifest. The first three cover the text-emitting
# path (svg/chartjs/mermaid/html); the rest cover the manim subprocess
# path. A given turn only streams a subset of these.
_VISUALIZE_STAGES = [
    "analyzing",
    "generating",
    "reviewing",
    "concept_analysis",
    "concept_design",
    "code_generation",
    "code_retry",
    "summary",
    "render_output",
]

_MANIM_RENDER_TYPES = {"manim_video", "manim_image"}

# Visualizer packages contribute model-facing payload documentation. Keep the
# reused chat loop's read/grounding surface, but never let package instructions
# unlock state-changing built-ins such as exec, write_memory, write_note, cron,
# github or deferred tool loading.
_VISUALIZE_SAFE_BUILTINS = (
    "rag",
    "kb_files",
    "read_source",
    "read_memory",
    "list_notebook",
    "read_skill",
    "web_fetch",
    "ask_user",
)


class VisualizeCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="visualize",
        description=(
            "Generate a validated visualization with any installed visualizer "
            "type, or render a Manim animation/storyboard artifact."
        ),
        stages=_VISUALIZE_STAGES,
        tools_used=["submit_visualization"],
        cli_aliases=["visualize", "viz"],
        request_schema=get_capability_request_schema("visualize"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        request_config = validate_visualize_request_config(context.config_overrides)
        render_mode = request_config.render_mode
        i18n = StatusI18n(self.name, context.language, module="visualize")
        registry = get_visualizer_registry()

        history_context = str(context.metadata.get("conversation_context_text", "") or "").strip()
        async with stream.stage("analyzing", source=self.name):
            await stream.progress(
                i18n.t("analyzing", "Analyzing visualization requirements..."),
                source=self.name,
                stage="analyzing",
            )
            if render_mode != "auto" and registry.get(render_mode) is None:
                available = ", ".join(plugin.manifest.id for plugin in registry.installed())
                raise VisualizerStoreError(
                    f"visualizer '{render_mode}' is not installed or is disabled. "
                    f"Available: {available or 'none'}"
                )

        # Artifact renderers retain their specialized subprocess pipeline.
        if render_mode in _MANIM_RENDER_TYPES:
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()
            await self._run_manim_path(
                context=context,
                stream=stream,
                render_type=render_mode,
                visualize_config=request_config,
                history_context=history_context,
                usage=UsageTracker(model=getattr(llm_config, "model", None)),
                i18n=i18n,
            )
            return

        # The generic capability only marks the turn and owns the final
        # envelope. Generation, retrieval, repair and tool dispatch all run in
        # the shared Chat Engine through VisualizationLoopCapability.
        from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline

        # A visualization only reaches the canvas through the
        # submit_visualization tool call, so a provider that is never handed
        # tool schemas has no way to commit one: it answers in prose, and the
        # loop capability's output policy discards that prose. Local
        # OpenAI-compatible servers (LM Studio, Ollama, vLLM, llama.cpp) are
        # opted out of native tools by default, which used to surface only as
        # a bare "no valid canvas payload" error after a full five-round loop.
        # Say so up front, and keep the finding for the failure message.
        #
        # This deliberately does not abort the turn: the DSML fallback still
        # recovers text-format tool calls from some local DeepSeek
        # deployments, so a run without native tools can still succeed.
        tool_calling_disabled_for = self._tool_calling_disabled_for()
        if tool_calling_disabled_for:
            await stream.progress(
                i18n.t(
                    "tool_calling_disabled",
                    _TOOL_CALLING_DISABLED_WARNING,
                    target=tool_calling_disabled_for,
                ),
                source=self.name,
                stage="generating",
                metadata={"trace_kind": "warning"},
            )

        context.metadata[VISUALIZE_MODE_KEY] = True
        context.metadata[REQUESTED_VISUALIZER_KEY] = render_mode
        context.metadata.pop(VISUALIZATION_RESULT_KEY, None)
        if context.allowed_builtin_tools is None:
            context.allowed_builtin_tools = list(_VISUALIZE_SAFE_BUILTINS)
        else:
            allowed = set(context.allowed_builtin_tools)
            context.allowed_builtin_tools = [
                name for name in _VISUALIZE_SAFE_BUILTINS if name in allowed
            ]
        pipeline = AgenticChatPipeline(
            language=context.language,
            max_rounds=5,
            temperature=0.15,
            max_tokens=16000,
            event_source=self.name,
            event_stage="generating",
            emit_result=False,
        )
        loop_result = await pipeline.run(context, stream)
        envelope = context.metadata.get(VISUALIZATION_RESULT_KEY)
        if not isinstance(envelope, dict):
            if tool_calling_disabled_for:
                raise RuntimeError(
                    i18n.t(
                        "no_payload_tool_calling_disabled",
                        _NO_PAYLOAD_TOOL_CALLING_DISABLED,
                        target=tool_calling_disabled_for,
                    )
                )
            raise RuntimeError(i18n.t("no_payload", _NO_PAYLOAD))

        payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
        data = payload.get("data")
        plugin = registry.get(str(envelope.get("render_type") or ""))
        language_tag = plugin.manifest.language_tag if plugin is not None else "text"
        serialized = (
            data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2)
        )
        content_md = f"```{language_tag}\n{serialized}\n```"
        await stream.content(content_md, source=self.name, stage="reviewing")

        result = {
            **envelope,
            # Legacy compatibility for existing consumers while they migrate
            # to renderer/payload/presentation.
            "response": content_md,
            "code": {"language": language_tag, "content": serialized},
            "analysis": {
                "render_type": envelope.get("render_type"),
                "description": (envelope.get("presentation") or {}).get("description", ""),
                "engine": "chat_agent_loop",
                "requested_type": render_mode,
            },
            "review": {
                "changed": False,
                "review_notes": "Accepted by the installed visualizer validator.",
            },
            "engine": "chat_agent_loop",
            "loop": loop_result,
        }
        await emit_capability_result(
            stream,
            result,
            source=self.name,
            usage=pipeline.usage,
        )

    @staticmethod
    def _tool_calling_disabled_for() -> str:
        """``"binding/model"`` when this turn gets no tool schemas, else ``""``.

        Mirrors the resolution ``AgenticChatPipeline`` performs for the same
        LLM config, so the warning and the failure message describe the loop
        that actually ran. Probing must never be why a visualization fails, so
        an unreadable config reports "enabled" and leaves the generic
        diagnosis in place.
        """
        try:
            from deeptutor.runtime.agentic.client import can_use_native_tool_calling
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()
            binding = str(getattr(llm_config, "binding", None) or "openai")
            model = str(getattr(llm_config, "model", None) or "")
            if can_use_native_tool_calling(binding=binding, model=model or None):
                return ""
            return f"{binding}/{model}" if model else binding
        except Exception:  # pragma: no cover - defensive: never block a turn
            logger.debug("Tool-calling probe unavailable for visualize", exc_info=True)
            return ""

    async def _run_manim_path(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        render_type: str,
        visualize_config: VisualizeRequestConfig,
        history_context: str,
        usage: UsageTracker | None = None,
        i18n: StatusI18n | None = None,
    ) -> None:
        """
        Manim sub-pipeline. Mirrors ``MathAnimatorCapability.run`` but emits
        the final result with ``render_type`` as the discriminator so the
        unified frontend dispatcher can route to ``MathAnimatorViewer``.
        """
        import importlib.util
        import time

        if importlib.util.find_spec("manim") is None:
            raise RuntimeError(
                "Manim rendering requires optional dependencies. "
                "Install with `pip install 'deeptutor[math-animator]'` "
                "or `pip install -r requirements/math-animator.txt`."
            )

        from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
        from deeptutor.agents.math_animator.request_config import MathAnimatorRequestConfig
        from deeptutor.core.trace import build_trace_metadata, new_call_id
        from deeptutor.services.llm.config import get_llm_config

        if i18n is None:
            i18n = StatusI18n(self.name, context.language, module="visualize")
        output_mode = "image" if render_type == "manim_image" else "video"
        request_config = MathAnimatorRequestConfig(
            output_mode=output_mode,  # type: ignore[arg-type]
            quality=visualize_config.quality,
            style_hint=visualize_config.style_hint,
        )

        llm_config = get_llm_config()
        workspace = context.runtime.workspace
        pipeline = MathAnimatorPipeline(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=llm_config.api_version,
            language=context.language,
            trace_callback=self._build_trace_bridge(stream, i18n=i18n),
            workspace_output_dir=workspace.output_dir if workspace else None,
            workspace_root=workspace.root if workspace else None,
            workspace_id=workspace.workspace_id if workspace else "",
        )

        timings: dict[str, float] = {}
        turn_id = str(
            context.metadata.get("turn_id", "") or context.session_id or "visualize-manim"
        )
        render_call_meta = build_trace_metadata(
            call_id=new_call_id("manim-render"),
            phase="render_output",
            label="Render output",
            call_kind="math_render_output",
            trace_role="render",
            trace_kind="progress",
            output_mode=request_config.output_mode,
            quality=request_config.quality,
        )

        stage_start = time.perf_counter()
        async with stream.stage("concept_analysis", source=self.name):
            analysis = await pipeline.run_analysis(
                user_input=context.user_message,
                history_context=history_context,
                request_config=request_config,
                attachments=context.attachments,
            )
        timings["concept_analysis"] = round(time.perf_counter() - stage_start, 3)

        stage_start = time.perf_counter()
        async with stream.stage("concept_design", source=self.name):
            design = await pipeline.run_design(
                user_input=context.user_message,
                request_config=request_config,
                analysis=analysis,
            )
        timings["concept_design"] = round(time.perf_counter() - stage_start, 3)

        stage_start = time.perf_counter()
        async with stream.stage("code_generation", source=self.name):
            generated = await pipeline.run_code_generation(
                user_input=context.user_message,
                request_config=request_config,
                analysis=analysis,
                design=design,
            )
            await stream.progress(
                message=i18n.t("manim_code_prepared", "Manim code prepared."),
                source=self.name,
                stage="code_generation",
            )
        timings["code_generation"] = round(time.perf_counter() - stage_start, 3)

        async def _on_retry(retry_attempt) -> None:
            await stream.progress(
                message=i18n.t(
                    "manim_retry",
                    f"Retry {retry_attempt.attempt}: {retry_attempt.error}",
                    attempt=retry_attempt.attempt,
                    error=retry_attempt.error,
                ),
                source=self.name,
                stage="code_retry",
                metadata={**render_call_meta, "trace_layer": "raw"},
            )

        async def _on_render_progress(message: str, raw: bool) -> None:
            await stream.progress(
                message=message,
                source=self.name,
                stage="render_output",
                metadata={
                    **render_call_meta,
                    "trace_layer": "raw" if raw else "summary",
                },
            )

        async def _on_retry_status(message: str) -> None:
            await stream.progress(
                message=message,
                source=self.name,
                stage="code_retry",
                metadata={"trace_layer": "summary"},
            )

        stage_start = time.perf_counter()
        async with stream.stage("code_retry", source=self.name):
            await stream.progress(
                message=i18n.t(
                    "manim_rendering",
                    (
                        f"Rendering {request_config.output_mode} "
                        f"with quality={request_config.quality}."
                    ),
                    mode=request_config.output_mode,
                    quality=request_config.quality,
                ),
                source=self.name,
                stage="code_retry",
                metadata={**render_call_meta, "call_state": "running"},
            )
            final_code, render_result = await pipeline.run_render(
                turn_id=turn_id,
                user_input=context.user_message,
                request_config=request_config,
                initial_code=generated.code,
                on_retry=_on_retry,
                on_render_progress=_on_render_progress,
                on_retry_status=_on_retry_status,
            )
        timings["code_retry"] = round(time.perf_counter() - stage_start, 3)

        stage_start = time.perf_counter()
        async with stream.stage("summary", source=self.name):
            summary = await pipeline.run_summary(
                user_input=context.user_message,
                request_config=request_config,
                analysis=analysis,
                design=design,
                render_result=render_result,
            )
            if summary.summary_text:
                await stream.content(summary.summary_text, source=self.name, stage="summary")
        timings["summary"] = round(time.perf_counter() - stage_start, 3)

        async with stream.stage("render_output", source=self.name):
            artifact_count = len(render_result.artifacts)
            artifact_key = "manim_artifacts_one" if artifact_count == 1 else "manim_artifacts_many"
            await stream.progress(
                message=i18n.t(
                    artifact_key,
                    (
                        f"Prepared {artifact_count} "
                        f"{'artifact' if artifact_count == 1 else 'artifacts'}."
                    ),
                    count=artifact_count,
                ),
                source=self.name,
                stage="render_output",
                metadata={**render_call_meta, "call_state": "complete"},
            )
        timings["render_output"] = 0.0
        visual_review = getattr(render_result, "visual_review", None)
        workspace_items = list(getattr(render_result, "workspace_items", []) or [])
        if workspace_items:
            await stream.sources(
                [{"type": "workspace_item", **item} for item in workspace_items],
                source=self.name,
                stage="render_output",
            )

        await emit_capability_result(
            stream,
            {
                "response": summary.summary_text,
                "render_type": render_type,
                "summary": summary.model_dump(),
                "code": {
                    "language": "python",
                    "content": final_code,
                },
                "output_mode": request_config.output_mode,
                "artifacts": [artifact.model_dump() for artifact in render_result.artifacts],
                "workspace_items": workspace_items,
                "timings": timings,
                "render": {
                    "quality": request_config.quality,
                    "retry_attempts": render_result.retry_attempts,
                    "retry_history": [item.model_dump() for item in render_result.retry_history],
                    "source_code_path": render_result.source_code_path,
                    "visual_review": visual_review.model_dump() if visual_review else None,
                },
                "analysis": analysis.model_dump(),
                "design": design.model_dump(),
            },
            source=self.name,
            usage=usage,
        )

    def _build_trace_bridge(self, stream: StreamBus, i18n: StatusI18n | None = None):
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
            label = str(base_metadata.get("label", "") or stage.replace("_", " ").title())
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
                fallback = (
                    i18n.t("llm_call_failed", "LLM call failed.")
                    if i18n is not None
                    else "LLM call failed."
                )
                await stream.error(
                    str(update.get("response", "") or fallback),
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata,
                        {"trace_kind": "call_status", "call_state": "error"},
                    ),
                )

        return _trace_bridge
