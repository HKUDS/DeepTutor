"""Video lesson capability: a Remotion explainer the learner plays in the browser."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.capability_protocol import TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.trace import merge_trace_metadata
from deeptutor.i18n import StatusI18n
from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.runtime.bootstrap.builtin_capabilities import builtin_capability_manifest
from deeptutor.runtime.stream_bus import StreamBus

MAX_ATTEMPTS = 3


class VideoLessonCapability(TurnCapability):
    manifest = builtin_capability_manifest("video_lesson")

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        from deeptutor.agents.video_lesson.lesson_writer import LessonWriterAgent
        from deeptutor.agents.video_lesson.narration import narrate, voice_module
        from deeptutor.agents.video_lesson.runtime import (
            build_lesson,
            ensure_runtime,
            prepare_workdir,
            write_page,
        )
        from deeptutor.services.llm.config import get_llm_config
        from deeptutor.services.path_service import get_path_service

        llm_config = get_llm_config()
        usage = UsageTracker(model=getattr(llm_config, "model", None))
        i18n = StatusI18n(self.name, context.language, module="video_lesson")
        paths = get_path_service()
        turn_id = str(context.metadata.get("turn_id", "") or context.session_id or "video-lesson")
        base_dir = paths.get_agent_dir("video_lesson") / turn_id
        history = str(context.metadata.get("conversation_context_text", "") or "")

        writer = LessonWriterAgent(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=llm_config.api_version,
            language=context.language,
        )
        writer.set_trace_callback(self._build_trace_bridge(stream, i18n))
        writer.start(user_input=context.user_message, history=history)

        # npm install (first use only) overlaps the first, much longer, LLM call.
        runtime_ready = asyncio.create_task(ensure_runtime())
        timings: dict[str, float] = {"code_generation": 0.0, "render_check": 0.0}
        voice_cache: dict = {}
        narrated = False
        attempts: list[dict[str, Any]] = []
        draft = None
        build = None
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                started = time.perf_counter()
                async with stream.stage("code_generation", source=self.name):
                    await stream.progress(
                        message=i18n.t("writing", "Writing the explainer animation."),
                        source=self.name,
                        stage="code_generation",
                    )
                    draft = await writer.write(attempt=attempt)
                timings["code_generation"] += round(time.perf_counter() - started, 3)
                if not draft.code:
                    attempts.append(
                        {"attempt": attempt, "stage": "parse", "errors": ["no ```tsx block"]}
                    )
                    writer.add_feedback(
                        previous=draft.raw,
                        stage="parse",
                        errors=["The reply had no ```tsx code block."],
                    )
                    continue

                started = time.perf_counter()
                async with stream.stage("render_check", source=self.name):
                    if not runtime_ready.done():
                        await stream.progress(
                            message=i18n.t("preparing_runtime", "Preparing the Remotion runtime."),
                            source=self.name,
                            stage="render_check",
                        )
                    if draft.narration:
                        await stream.progress(
                            message=i18n.t("narrating", "Recording the narration."),
                            source=self.name,
                            stage="render_check",
                        )
                    clips, _ = await asyncio.gather(
                        narrate(draft.narration, context.language, voice_cache), runtime_ready
                    )
                    narrated = any(clip.audio for clip in clips.values())
                    await stream.progress(
                        message=i18n.t(
                            "checking", "Compiling the animation and checking its frames."
                        ),
                        source=self.name,
                        stage="render_check",
                    )
                    lesson = prepare_workdir(
                        base_dir / "source", draft.code, voice=voice_module(clips)
                    )
                    build = await build_lesson(lesson, base_dir / "source" / "player.js")
                timings["render_check"] += round(time.perf_counter() - started, 3)
                attempts.append({"attempt": attempt, "stage": build.stage, "errors": build.errors})
                if build.ok:
                    break
                await stream.progress(
                    message=i18n.t(
                        "retry",
                        f"Check {attempt} failed: {build.errors[0] if build.errors else build.stage}",
                        attempt=attempt,
                        error=build.errors[0] if build.errors else build.stage,
                    ),
                    source=self.name,
                    stage="render_check",
                    metadata={"trace_layer": "raw"},
                )
                writer.add_feedback(previous=draft.raw, stage=build.stage, errors=build.errors)
        finally:
            if not runtime_ready.done():
                runtime_ready.cancel()
            await asyncio.gather(runtime_ready, return_exceptions=True)

        if draft is None or build is None or not build.ok:
            last = attempts[-1]["errors"] if attempts else []
            raise RuntimeError(
                f"The video lesson did not pass its checks after {MAX_ATTEMPTS} attempts: "
                + "; ".join(last[:3])
            )

        async with stream.stage("render_output", source=self.name):
            title = draft.title or context.user_message.strip()[:60]
            page = write_page(
                base_dir / "source" / "player.js",
                base_dir / "artifacts" / "lesson.html",
                title=title,
                language=context.language,
            )
            (base_dir / "source" / "player.js").unlink(missing_ok=True)
            fps, frames = 30, max((f.get("frame", 0) for f in build.frames), default=0) + 1
            seconds = round(frames / fps)
            await stream.progress(
                message=i18n.t("ready", f"Video lesson ready ({seconds} s).", seconds=seconds),
                source=self.name,
                stage="render_output",
            )
            if draft.summary:
                await stream.content(draft.summary, source=self.name, stage="render_output")

        rel = page.resolve().relative_to(paths.user_data_dir.resolve()).as_posix()
        await emit_capability_result(
            stream,
            {
                "response": draft.summary,
                "title": title,
                "artifacts": [
                    {
                        "type": "html",
                        "url": f"/files/outputs/{rel}",
                        "filename": page.name,
                        "content_type": "text/html",
                        "label": title,
                    }
                ],
                "code": {"language": "tsx", "content": draft.code},
                "render": {
                    "attempts": attempts,
                    "duration_seconds": seconds,
                    "narrated": narrated,
                },
                "timings": timings,
            },
            source=self.name,
            usage=usage,
        )

    def _build_trace_bridge(self, stream: StreamBus, i18n: StatusI18n):
        async def _trace_bridge(update: dict[str, Any]) -> None:
            if str(update.get("event", "") or "") != "llm_call":
                return
            stage = str(update.get("phase") or update.get("stage") or "code_generation")
            base_metadata = {
                key: value
                for key, value in update.items()
                if key
                not in {"event", "state", "response", "chunk", "result", "tool_name", "tool_args"}
            }
            state = str(update.get("state", "running"))
            label = str(base_metadata.get("label", "") or stage.replace("_", " ").title())
            if state in {"running", "complete"}:
                await stream.progress(
                    message=label,
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata, {"trace_kind": "call_status", "call_state": state}
                    ),
                )
            elif state == "streaming":
                chunk = str(update.get("chunk", "") or "")
                if chunk:
                    await stream.thinking(
                        chunk,
                        source=self.name,
                        stage=stage,
                        metadata=merge_trace_metadata(base_metadata, {"trace_kind": "llm_chunk"}),
                    )
            elif state == "error":
                await stream.error(
                    str(
                        update.get("response", "") or i18n.t("llm_call_failed", "LLM call failed.")
                    ),
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata, {"trace_kind": "call_status", "call_state": "error"}
                    ),
                )

        return _trace_bridge
