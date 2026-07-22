"""Orchestrates the math animator generation flow."""

from __future__ import annotations

import time
from typing import Any, Callable

from deeptutor.core.context import Attachment

from .agents import (
    CodeGeneratorAgent,
    ConceptAnalysisAgent,
    ConceptDesignAgent,
    SummaryAgent,
    VisualReviewAgent,
)
from .duration_utils import parse_target_duration_seconds
from .models import RenderResult, VisualReviewResult
from .renderer import ManimRenderService
from .request_config import MathAnimatorRequestConfig
from .retry_manager import CodeRetryManager
from .visual_review import VisualReviewService

# Imports for narration support
try:
    from ...services.tts import TTSClient, get_tts_client
    from ...services.tts.models import TTSAudioResult
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False


class MathAnimatorPipeline:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        api_version: str | None,
        language: str = "zh",
        trace_callback: Callable[[dict[str, Any]], Any] | None = None,
        enable_visual_review: bool = False,
    ) -> None:
        self.enable_visual_review = enable_visual_review
        self.analysis_agent = ConceptAnalysisAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.design_agent = ConceptDesignAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.code_agent = CodeGeneratorAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.summary_agent = SummaryAgent(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )
        self.visual_review_agent = (
            VisualReviewAgent(
                api_key=api_key,
                base_url=base_url,
                api_version=api_version,
                language=language,
            )
            if enable_visual_review
            else None
        )
        self.set_trace_callback(trace_callback)

    def set_trace_callback(self, callback: Callable[[dict[str, Any]], Any] | None) -> None:
        for agent in (
            self.analysis_agent,
            self.design_agent,
            self.code_agent,
            self.summary_agent,
            self.visual_review_agent,
        ):
            if agent is not None:
                agent.set_trace_callback(callback)

    async def run_analysis(
        self,
        *,
        user_input: str,
        history_context: str,
        request_config: MathAnimatorRequestConfig,
        attachments: list[Attachment],
    ):
        return await self.analysis_agent.process(
            user_input=user_input,
            history_context=history_context,
            output_mode=request_config.output_mode,
            style_hint=request_config.style_hint,
            attachments=attachments,
        )

    async def run_design(
        self,
        *,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        analysis,
    ):
        return await self.design_agent.process(
            user_input=user_input,
            output_mode=request_config.output_mode,
            analysis=analysis,
            style_hint=request_config.style_hint,
        )

    async def run_code_generation(
        self,
        *,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        analysis,
        design,
    ):
        duration_target_seconds = parse_target_duration_seconds(
            " ".join(
                part.strip()
                for part in (user_input, request_config.style_hint)
                if isinstance(part, str) and part.strip()
            )
        )
        return await self.code_agent.generate(
            user_input=user_input,
            output_mode=request_config.output_mode,
            analysis=analysis,
            design=design,
            duration_target_seconds=duration_target_seconds,
        )

    async def run_render(
        self,
        *,
        turn_id: str,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        initial_code: str,
        on_retry: Callable[[Any], Any] | None = None,
        on_render_progress: Callable[[str, bool], Any] | None = None,
        on_retry_status: Callable[[str], Any] | None = None,
    ) -> tuple[str, RenderResult]:
        renderer = ManimRenderService(turn_id, progress_callback=on_render_progress)
        duration_target_seconds = parse_target_duration_seconds(
            " ".join(
                part.strip()
                for part in (user_input, request_config.style_hint)
                if isinstance(part, str) and part.strip()
            )
        )
        review_callback: Callable[[str, RenderResult], Any] | None = None
        if self.enable_visual_review and self.visual_review_agent is not None:
            review_service = VisualReviewService(turn_id, progress_callback=on_render_progress)

            async def _review_callback(
                current_code: str, render_result: RenderResult
            ) -> VisualReviewResult:
                attachments = await review_service.build_attachments(render_result)
                return await self.visual_review_agent.process(
                    user_input=user_input,
                    output_mode=request_config.output_mode,
                    current_code=current_code,
                    render_result=render_result,
                    attachments=attachments,
                )

            review_callback = _review_callback

        retry_manager = CodeRetryManager(
            renderer=renderer,
            max_retries=4,
            on_retry=on_retry,
            on_status=on_retry_status,
            review_callback=review_callback,
            repair_callback=lambda current_code, error_message, attempt: self.code_agent.repair(
                user_input=user_input,
                output_mode=request_config.output_mode,
                current_code=current_code,
                error_message=error_message,
                attempt=attempt,
                duration_target_seconds=duration_target_seconds,
            ),
        )
        final_code, render_result = await retry_manager.render_with_retries(
            initial_code=initial_code,
            output_mode=request_config.output_mode,
            quality=request_config.quality,
        )
        return final_code, RenderResult.model_validate(render_result.model_dump())

    async def run_summary(
        self,
        *,
        user_input: str,
        request_config: MathAnimatorRequestConfig,
        analysis,
        design,
        render_result: RenderResult,
    ):
        return await self.summary_agent.process(
            user_input=user_input,
            output_mode=request_config.output_mode,
            analysis=analysis,
            design=design,
            render_result=render_result,
        )

    async def run(
        self,
        *,
        turn_id: str,
        user_input: str,
        history_context: str,
        request_config: MathAnimatorRequestConfig,
        attachments: list[Attachment],
    ) -> dict[str, Any]:
        timings: dict[str, float] = {}

        start = time.perf_counter()
        analysis = await self.run_analysis(
            user_input=user_input,
            history_context=history_context,
            request_config=request_config,
            attachments=attachments,
        )
        timings["concept_analysis"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        design = await self.run_design(
            user_input=user_input,
            request_config=request_config,
            analysis=analysis,
        )
        timings["concept_design"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        generated = await self.run_code_generation(
            user_input=user_input,
            request_config=request_config,
            analysis=analysis,
            design=design,
        )
        timings["code_generation"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        final_code, render_result = await self.run_render(
            turn_id=turn_id,
            user_input=user_input,
            request_config=request_config,
            initial_code=generated.code,
        )
        timings["code_retry"] = round(time.perf_counter() - start, 3)

        start = time.perf_counter()
        summary = await self.run_summary(
            user_input=user_input,
            request_config=request_config,
            analysis=analysis,
            design=design,
            render_result=render_result,
        )
        timings["summary"] = round(time.perf_counter() - start, 3)

        timings["render_output"] = timings["code_retry"]
        return {
            "analysis": analysis,
            "design": design,
            "code": final_code,
            "render_result": render_result,
            "summary": summary,
            "timings": timings,
        }


    async def generate_with_narration(
        self,
        *,
        turn_id: str,
        lecture_script: dict[str, Any],
        tts_provider: str = "edge",
        voice: str | None = None,
        output_mode: str = "video",
        quality: str = "medium",
        on_progress: Callable[[str], Any] | None = None,
    ) -> dict[str, Any]:
        """Generate animated video with narration audio synchronized.

        Args:
            turn_id: Unique identifier for this generation
            lecture_script: Lecture script with intro/segments/conclusion
            tts_provider: TTS provider name ("edge", "azure", etc.)
            voice: Voice identifier (provider-specific)
            output_mode: "video" or "image"
            quality: "low", "medium", or "high"
            on_progress: Progress callback

        Returns:
            dict with video_path, audio_path, and timing info
        """
        if not TTS_AVAILABLE:
            raise RuntimeError("TTS service not available")

        if on_progress:
            await on_progress("Generating narration audio...")

        # Step 1: Generate TTS audio
        tts = get_tts_client(provider=tts_provider)

        # Merge script segments for TTS
        full_script = self._merge_lecture_script(lecture_script)
        tts_result = await tts.synthesize(full_script, voice=voice)

        if on_progress:
            await on_progress(f"Audio generated: {tts_result.duration_seconds:.1f}s")

        # Step 2: Map TTS boundaries to segments
        timed_segments = self._map_boundaries_to_segments(
            lecture_script, tts_result.sentence_boundaries
        )

        # Step 3: Generate timed animation code
        if on_progress:
            await on_progress("Generating timed animation code...")

        # Use provided manim_code if available, otherwise generate timed code
        provided_code = lecture_script.get("manim_code")
        if provided_code:
            # Inject timing comments into the provided code
            timed_code = self._inject_timing_to_code(
                provided_code, timed_segments, tts_result.duration_seconds
            )
        else:
            # Use code agent with timing constraints
            timed_code = await self._generate_timed_code(
                timed_segments=timed_segments,
                total_duration=tts_result.duration_seconds,
            )

        # Step 4: Render video
        if on_progress:
            await on_progress("Rendering video...")

        render_result = await self.run_render(
            turn_id=turn_id,
            user_input=lecture_script.get("problem_id", "math_lecture"),
            request_config=MathAnimatorRequestConfig(
                output_mode=output_mode,
                quality=quality,
            ),
            initial_code=timed_code,
            on_render_progress=lambda msg, raw: on_progress(msg) if on_progress else None,
        )

        # Step 5: Return result with paths for FFmpeg muxing
        return {
            "video_path": render_result[1].artifacts[0].url if render_result[1].artifacts else None,
            "audio_path": tts_result.audio_path,
            "duration_seconds": tts_result.duration_seconds,
            "sentence_boundaries": [b.to_dict() for b in tts_result.sentence_boundaries],
            "timed_segments": timed_segments,
        }

    def _merge_lecture_script(self, lecture_script: dict[str, Any]) -> str:
        """Merge all script parts into a single text for TTS."""
        parts = []

        intro = lecture_script.get("intro", {})
        if intro:
            parts.append(intro.get("script", ""))

        for segment in lecture_script.get("segments", []):
            parts.append(segment.get("script", ""))

        conclusion = lecture_script.get("conclusion", {})
        if conclusion:
            parts.append(conclusion.get("script", ""))

        return "\n\n".join(parts)

    def _map_boundaries_to_segments(
        self,
        lecture_script: dict[str, Any],
        boundaries: list,
    ) -> list[dict[str, Any]]:
        """Map TTS sentence boundaries to lecture segments."""
        import re

        def split_sentences(text: str) -> list[str]:
            pattern = r"[^。！？.!?]+[。！？.!?]+"
            sentences = re.findall(pattern, text)
            return [s.strip() for s in sentences if s.strip()]

        result = []
        boundary_idx = 0

        all_segments = [
            ("intro", lecture_script.get("intro", {})),
        ]
        all_segments.extend(("segment", s) for s in lecture_script.get("segments", []))
        all_segments.append(("conclusion", lecture_script.get("conclusion", {})))

        for seg_type, segment in all_segments:
            if not segment:
                continue

            script = segment.get("script", "")
            segment_sentences = split_sentences(script)

            start_ms = 0
            end_ms = 0

            if boundary_idx < len(boundaries):
                start_ms = boundaries[boundary_idx].start_ms

                # Advance by number of sentences
                boundary_idx += len(segment_sentences)

                if boundary_idx <= len(boundaries):
                    end_ms = boundaries[boundary_idx - 1].end_ms
                else:
                    end_ms = boundaries[-1].end_ms

            result.append({
                "type": seg_type,
                "title": segment.get("title", ""),
                "script": script,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
                "visual_description": segment.get("visual_description", ""),
            })

        return result

    async def _generate_timed_code(
        self,
        timed_segments: list[dict[str, Any]],
        total_duration: float,
    ) -> str:
        """Generate Manim code with timing constraints.

        This is a simplified implementation that generates code with
        run_time hints. Full implementation would need to modify
        CodeGeneratorAgent to accept timing parameters.
        """
        # For MVP, generate a basic template with timing comments
        # Full implementation would integrate with code_agent.generate()

        code_parts = [
            "from manim import *",
            "",
            f"# Total duration: {total_duration:.1f}s",
            "",
            "class MathLectureScene(Scene):",
            "    def construct(self):",
        ]

        for seg in timed_segments:
            duration_sec = seg["duration_ms"] / 1000
            code_parts.append(f"        # {seg['title']} ({duration_sec:.1f}s)")
            code_parts.append(f"        # Visual: {seg['visual_description']}")
            code_parts.append(f"        self.wait({duration_sec:.1f})")
            code_parts.append("")

        return "\n".join(code_parts)

    def _inject_timing_to_code(
        self,
        manim_code: str,
        timed_segments: list[dict[str, Any]],
        total_duration: float,
    ) -> str:
        """Inject timing comments into provided Manim code.

        This preserves the LLM-generated visualizations while adding
        timing guidance as comments for future enhancement.
        """
        timing_header = [
            f"# Total duration: {total_duration:.1f}s",
            f"# Segments: {len(timed_segments)}",
        ]

        for seg in timed_segments:
            duration_sec = seg["duration_ms"] / 1000
            timing_header.append(
                f"# - {seg['title']}: {duration_sec:.1f}s "
                f"({seg['start_ms']/1000:.1f}s - {seg['end_ms']/1000:.1f}s)"
            )

        timing_header.append("")

        # Combine timing comments with the provided code
        return "\n".join(timing_header) + "\n" + manim_code


__all__ = ["MathAnimatorPipeline"]
