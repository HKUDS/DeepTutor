"""Math animator capability."""

from __future__ import annotations

import importlib.util
import time
from typing import Any

from deeptutor.capabilities.request_contracts import get_capability_request_schema
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id


class MathAnimatorCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="math_animator",
        description="Generate math animations or storyboard images with Manim.",
        stages=[
            "concept_analysis",
            "concept_design",
            "code_generation",
            "code_retry",
            "summary",
            "render_output",
        ],
        tools_used=[],
        cli_aliases=["animate"],
        request_schema=get_capability_request_schema("math_animator"),
        config_defaults={
            "output_mode": "video",
            "quality": "medium",
            "style_hint": "",
        },
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        if importlib.util.find_spec("manim") is None:
            raise RuntimeError(
                "math_animator requires optional dependencies. "
                "Install with `pip install 'deeptutor[math-animator]'` "
                "or `pip install -r requirements/math-animator.txt`."
            )
        from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
        from deeptutor.agents.math_animator.request_config import (
            validate_math_animator_request_config,
        )
        from deeptutor.capabilities._answer_now import extract_answer_now_context
        from deeptutor.services.llm.config import get_llm_config

        llm_config = get_llm_config()
        request_config = validate_math_animator_request_config(context.config_overrides)
        pipeline = MathAnimatorPipeline(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=llm_config.api_version,
            language=context.language,
            trace_callback=self._build_trace_bridge(stream),
        )

        answer_now_payload = extract_answer_now_context(context)
        if answer_now_payload is not None:
            await self._run_answer_now(
                context=context,
                stream=stream,
                payload=answer_now_payload,
                pipeline=pipeline,
                request_config=request_config,
            )
            return

        timings: dict[str, float] = {}
        turn_id = str(context.metadata.get("turn_id", "") or context.session_id or "math-animator")
        history_context = str(context.metadata.get("conversation_context_text", "") or "").strip()
        render_call_meta = build_trace_metadata(
            call_id=new_call_id("math-render"),
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
                message="Manim code prepared.",
                source=self.name,
                stage="code_generation",
            )
        timings["code_generation"] = round(time.perf_counter() - stage_start, 3)

        async def _on_retry(retry_attempt) -> None:
            await stream.progress(
                message=f"Retry {retry_attempt.attempt}: {retry_attempt.error}",
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
                message=f"Rendering {request_config.output_mode} with quality={request_config.quality}.",
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
            await stream.progress(
                message=(
                    f"Prepared {len(render_result.artifacts)} "
                    f"{'artifact' if len(render_result.artifacts) == 1 else 'artifacts'}."
                ),
                source=self.name,
                stage="render_output",
                metadata={**render_call_meta, "call_state": "complete"},
            )
        timings["render_output"] = 0.0
        visual_review = getattr(render_result, "visual_review", None)

        await stream.result(
            {
                "response": summary.summary_text,
                "summary": summary.model_dump(),
                "code": {
                    "language": "python",
                    "content": final_code,
                },
                "output_mode": request_config.output_mode,
                "artifacts": [artifact.model_dump() for artifact in render_result.artifacts],
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
        )

    async def _run_answer_now(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        payload: dict[str, Any],
        pipeline,  # MathAnimatorPipeline
        request_config,  # MathAnimatorRequestConfig
    ) -> None:
        """
        Fast-path for ``math_animator``:

        * Skip ``concept_analysis`` + ``concept_design`` + ``summary`` —
          we synthesise minimal stub objects from the partial trace.
        * **Keep** ``code_generation`` + ``render`` so the user still gets
          a real video / animation, which is the whole point of this
          capability.

        The result envelope mirrors the standard pipeline so
        ``MathAnimatorViewer`` renders the artefacts unchanged.
        """
        import time

        from deeptutor.agents.math_animator.models import ConceptAnalysis, SceneDesign
        from deeptutor.capabilities._answer_now import (
            format_trace_summary,
            make_skip_notice,
        )

        original = str(payload.get("original_user_message") or context.user_message).strip()
        partial = str(payload.get("partial_response") or "").strip()
        trace_summary = format_trace_summary(payload.get("events"), language=context.language)

        # Build minimal stubs so ``code_agent.generate(...)`` still has the
        # field shape it expects. We weave the partial trace into the
        # ``learning_goal`` / ``visual_style`` so the generator has at least
        # *some* design intent to work from.
        narrative_seed = "\n".join(line for line in partial.splitlines() if line.strip())[:400]
        analysis = ConceptAnalysis(
            learning_goal=original,
            math_focus=[],
            visual_targets=[],
            narrative_steps=[narrative_seed] if narrative_seed else [],
            reference_usage="",
            output_intent=request_config.output_mode,
        )
        design = SceneDesign(
            title=original[:80] or "Math animation",
            scene_outline=[],
            visual_style=request_config.style_hint or "",
            animation_notes=[trace_summary[:600]] if trace_summary else [],
            image_plan=[],
            code_constraints=[],
        )

        timings: dict[str, float] = {}
        turn_id = str(context.metadata.get("turn_id", "") or context.session_id or "math-animator")
        render_call_meta = build_trace_metadata(
            call_id=new_call_id("math-render"),
            phase="render_output",
            label="Render output",
            call_kind="math_render_output",
            trace_role="render",
            trace_kind="progress",
            output_mode=request_config.output_mode,
            quality=request_config.quality,
        )

        stage_start = time.perf_counter()
        async with stream.stage("code_generation", source=self.name):
            generated = await pipeline.run_code_generation(
                user_input=original,
                request_config=request_config,
                analysis=analysis,
                design=design,
            )
            await stream.progress(
                message="Manim code prepared (answer-now fast path).",
                source=self.name,
                stage="code_generation",
            )
        timings["code_generation"] = round(time.perf_counter() - stage_start, 3)

        async def _on_retry(retry_attempt) -> None:
            await stream.progress(
                message=f"Retry {retry_attempt.attempt}: {retry_attempt.error}",
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
                message=(
                    f"Rendering {request_config.output_mode} "
                    f"(quality={request_config.quality}) — answer-now fast path."
                ),
                source=self.name,
                stage="code_retry",
                metadata={**render_call_meta, "call_state": "running"},
            )
            final_code, render_result = await pipeline.run_render(
                turn_id=turn_id,
                user_input=original,
                request_config=request_config,
                initial_code=generated.code,
                on_retry=_on_retry,
                on_render_progress=_on_render_progress,
                on_retry_status=_on_retry_status,
            )
        timings["code_retry"] = round(time.perf_counter() - stage_start, 3)

        async with stream.stage("render_output", source=self.name):
            await stream.progress(
                message=(
                    f"Prepared {len(render_result.artifacts)} "
                    f"{'artifact' if len(render_result.artifacts) == 1 else 'artifacts'} "
                    "(answer-now)."
                ),
                source=self.name,
                stage="render_output",
                metadata={**render_call_meta, "call_state": "complete"},
            )
        timings["render_output"] = 0.0
        visual_review = getattr(render_result, "visual_review", None)

        notice = make_skip_notice(
            capability=self.name,
            language=context.language,
            stages_skipped=["concept_analysis", "concept_design", "summary"],
        )
        summary_text = (
            notice or "Answer-now: code generated and rendered without prior analysis/design."
        )
        if notice:
            await stream.content(summary_text, source=self.name, stage="summary")

        await stream.result(
            {
                "response": summary_text,
                "summary": {
                    "summary_text": summary_text,
                    "user_request": original,
                    "generated_output": "",
                    "key_points": [],
                    "answer_now": True,
                },
                "code": {
                    "language": "python",
                    "content": final_code,
                },
                "output_mode": request_config.output_mode,
                "artifacts": [artifact.model_dump() for artifact in render_result.artifacts],
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
                "metadata": {"answer_now": True},
            },
            source=self.name,
        )

    def _build_trace_bridge(self, stream: StreamBus):
        async def _trace_bridge(update: dict[str, Any]) -> None:
            event = str(update.get("event", "") or "")
            stage = str(update.get("phase") or update.get("stage") or "concept_analysis")
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
