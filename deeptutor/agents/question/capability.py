"""Deep Question Capability.

Routes one user turn through the right quiz-generation path:

* followup — single-call ``FollowupAgent`` reply about one prior question.
* custom mode — new ``QuestionPipeline`` (explore → plan → per-question loop).
* mimic mode  — same pipeline, but PDF parsing produces the templates
  and ``templates_override`` skips explore + plan.
"""

from __future__ import annotations

import asyncio
import base64
import tempfile
from typing import Any

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.core.agentic.usage import UsageTracker
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.trace import merge_trace_metadata
from deeptutor.i18n import StatusI18n
from deeptutor.runtime.request_contracts import get_capability_request_schema


class DeepQuestionCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="deep_question",
        description="Fast question generation (Template batches -> Generate).",
        stages=["ideation", "generation"],
        tools_used=["rag", "web_search", "code_execution"],
        cli_aliases=["quiz"],
        request_schema=get_capability_request_schema("deep_question"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        from deeptutor.services.llm.config import get_llm_config
        from deeptutor.services.path_service import get_path_service

        llm_config = get_llm_config()
        kb_name = context.knowledge_bases[0] if context.knowledge_bases else None
        turn_id = str(context.metadata.get("turn_id", "") or context.session_id or "deep-question")
        output_dir = get_path_service().get_task_workspace("deep_question", turn_id)
        i18n = StatusI18n(self.name, context.language, module="question")

        overrides = context.config_overrides
        followup_question_context = context.metadata.get("question_followup_context", {}) or {}
        if isinstance(followup_question_context, dict) and followup_question_context.get(
            "question"
        ):
            from deeptutor.agents.question.agents.followup_agent import FollowupAgent

            usage = UsageTracker(model=getattr(llm_config, "model", None))
            agent = FollowupAgent(
                language=context.language,
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                api_version=llm_config.api_version,
                token_tracker=usage,
            )
            agent.set_trace_callback(self._build_trace_bridge(stream, i18n=i18n))
            async with stream.stage("generation", source=self.name):
                answer = await agent.process(
                    user_message=context.user_message,
                    question_context=followup_question_context,
                    history_context=str(
                        context.metadata.get("conversation_context_text", "") or ""
                    ).strip(),
                    attachments=context.attachments,
                )
                if answer:
                    await stream.content(answer, source=self.name, stage="generation")
                followup_payload: dict[str, Any] = {
                    "response": answer or "",
                    "mode": "followup",
                    "question_id": followup_question_context.get("question_id", ""),
                }
                await emit_capability_result(
                    stream, followup_payload, source=self.name, usage=usage
                )
            return

        mode = str(overrides.get("mode", "custom") or "custom").strip().lower()
        topic = str(overrides.get("topic") or context.user_message or "").strip()
        num_questions = int(overrides.get("num_questions", 1) or 1)
        difficulty = str(overrides.get("difficulty", "") or "")
        raw_types = overrides.get("question_types") or []
        question_types = list(raw_types) if isinstance(raw_types, list) else []
        raw_counts = overrides.get("per_type_counts") or {}
        per_type_counts = (
            {str(k): int(v) for k, v in raw_counts.items() if isinstance(v, int) and v > 0}
            if isinstance(raw_counts, dict)
            else {}
        )
        history_context = str(context.metadata.get("conversation_context_text", "") or "").strip()

        if mode != "mimic":
            # New custom-mode pipeline: explore → plan → per-question quiz loop.
            # The pipeline owns its own stream.content / stream.result emission;
            # nothing here to render afterwards.
            from deeptutor.agents.question.history import load_session_quiz_history
            from deeptutor.agents.question.pipeline import QuestionPipeline
            from deeptutor.agents.question.request_config import (
                build_question_runtime_config,
            )
            from deeptutor.services.config import load_config_with_main

            if not topic:
                await stream.error(
                    i18n.t(
                        "topic_required",
                        "Topic is required for custom question generation.",
                    ),
                    source=self.name,
                )
                return

            quiz_history = await load_session_quiz_history(context.session_id or "")
            runtime_config = build_question_runtime_config(
                base_config=load_config_with_main("main.yaml"),
            )
            pipeline = QuestionPipeline(
                language=context.language,
                kb_name=kb_name,
                enabled_tools=list(context.enabled_tools or []),
                runtime_config=runtime_config,
            )
            await pipeline.run(
                context=context,
                user_message=topic,
                num_questions=num_questions,
                difficulty=difficulty,
                question_types=question_types,
                per_type_counts=per_type_counts,
                conversation_context=history_context,
                attachments=context.attachments,
                quiz_history=quiz_history,
                stream=stream,
            )
            return

        # Mimic mode — also runs through QuestionPipeline, but parses the
        # exam paper into templates first and passes them via
        # ``templates_override`` so explore + plan are skipped.
        await self._run_mimic_mode(
            context=context,
            stream=stream,
            kb_name=kb_name,
            output_dir=output_dir,
            overrides=overrides,
            history_context=history_context,
            num_questions=num_questions,
            i18n=i18n,
        )

    async def _run_mimic_mode(
        self,
        *,
        context: UnifiedContext,
        stream: StreamBus,
        kb_name: str | None,
        output_dir,
        overrides: dict[str, Any],
        history_context: str,
        num_questions: int,
        i18n: StatusI18n | None = None,
    ) -> None:
        """Resolve an exam paper → templates → ``QuestionPipeline.run`` with
        ``templates_override``. No legacy AgentCoordinator involvement.

        Three input shapes:

        * Uploaded PDF attachment      → write to tmpfile, parse with MinerU
        * Server-side parsed directory → skip parsing, just extract questions
        * ``[Attached Documents]`` in  → no paper available; fall back to
          the user_message text          custom-mode pipeline with a
                                         "mimic the attached source" hint
                                         prefixed onto the user_message
        """
        from deeptutor.agents.question.history import load_session_quiz_history
        from deeptutor.agents.question.mimic_source import (
            parse_exam_paper_to_templates,
        )
        from deeptutor.agents.question.pipeline import QuestionPipeline
        from deeptutor.agents.question.request_config import (
            build_question_runtime_config,
        )
        from deeptutor.services.config import load_config_with_main
        from deeptutor.services.parsing.engines.mineru.config import MinerUError

        if i18n is None:
            i18n = StatusI18n(self.name, context.language, module="question")
        paper_path = str(overrides.get("paper_path", "") or "").strip()
        max_questions = int(overrides.get("max_questions", 10) or 10)
        pdf_attachment = next(
            (
                attachment
                for attachment in context.attachments
                if attachment.filename.lower().endswith(".pdf")
                or attachment.type == "pdf"
                or attachment.mime_type == "application/pdf"
            ),
            None,
        )

        runtime_config = build_question_runtime_config(
            base_config=load_config_with_main("main.yaml"),
        )
        pipeline = QuestionPipeline(
            language=context.language,
            kb_name=kb_name,
            enabled_tools=list(context.enabled_tools or []),
            runtime_config=runtime_config,
        )
        quiz_history = await load_session_quiz_history(context.session_id or "")

        async def _emit_parse_notice(message: str) -> None:
            async with stream.stage("exploring", source=self.name):
                await stream.thinking(message, source=self.name, stage="exploring")

        if pdf_attachment and pdf_attachment.base64:
            # Bridge MinerU's progress lines (emitted from the parser worker
            # thread) back onto the event loop so the trace panel streams them
            # live — model downloads and per-page parsing would otherwise look
            # like a silent multi-minute hang.
            loop = asyncio.get_running_loop()

            def _parse_progress(line: str) -> None:
                asyncio.run_coroutine_threadsafe(
                    stream.thinking(line, source=self.name, stage="exploring"),
                    loop,
                )

            try:
                async with stream.stage("exploring", source=self.name):
                    await stream.thinking(
                        i18n.t(
                            "parsing_uploaded",
                            "Parsing uploaded exam paper and extracting templates...",
                        ),
                        source=self.name,
                        stage="exploring",
                    )
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as temp_pdf:
                        temp_pdf.write(base64.b64decode(pdf_attachment.base64))
                        temp_pdf.flush()
                        templates, _ = await parse_exam_paper_to_templates(
                            temp_pdf.name,
                            max_questions=max_questions,
                            paper_mode="upload",
                            output_dir=output_dir,
                            progress_callback=_parse_progress,
                        )
            except MinerUError as exc:
                await stream.error(str(exc), source=self.name)
                return
            await pipeline.run(
                context=context,
                user_message=context.user_message,
                num_questions=len(templates) or num_questions,
                difficulty="",
                conversation_context=history_context,
                attachments=context.attachments,
                quiz_history=quiz_history,
                templates_override=templates,
                stream=stream,
            )
            return

        if paper_path:
            await _emit_parse_notice(
                i18n.t(
                    "parsing_directory",
                    "Loading parsed exam paper and extracting templates...",
                )
            )
            try:
                templates, _ = await parse_exam_paper_to_templates(
                    paper_path,
                    max_questions=max_questions,
                    paper_mode="parsed",
                    output_dir=output_dir,
                )
            except MinerUError as exc:
                await stream.error(str(exc), source=self.name)
                return
            await pipeline.run(
                context=context,
                user_message=context.user_message,
                num_questions=len(templates) or num_questions,
                difficulty="",
                conversation_context=history_context,
                attachments=context.attachments,
                quiz_history=quiz_history,
                templates_override=templates,
                stream=stream,
            )
            return

        if "[Attached Documents]" in context.user_message:
            # No paper available — degrade to custom-mode generation but
            # bias the pipeline toward shadowing the attached source by
            # prefixing the user message with an explicit instruction.
            mimic_hint = (
                "[Mimic the attached source document as closely as possible: "
                "style, difficulty, structure, and assessed concepts.]\n\n"
            )
            await pipeline.run(
                context=context,
                user_message=mimic_hint + context.user_message,
                num_questions=max_questions,
                difficulty="",
                conversation_context=history_context,
                attachments=context.attachments,
                quiz_history=quiz_history,
                stream=stream,
            )
            return

        await stream.error(
            i18n.t(
                "mimic_needs_paper",
                "Mimic mode requires either an uploaded PDF or a parsed exam directory.",
            ),
            source=self.name,
        )

    def _build_trace_bridge(self, stream: StreamBus, i18n: StatusI18n | None = None):
        async def _trace_bridge(update: dict[str, Any]) -> None:
            event = str(update.get("event", "") or "")
            stage = str(update.get("phase") or update.get("stage") or "generation")
            base_metadata = {
                key: value
                for key, value in update.items()
                if key
                not in {"event", "state", "response", "chunk", "result", "tool_name", "tool_args"}
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
                    return

            if event == "tool_call":
                await stream.tool_call(
                    tool_name=str(update.get("tool_name", "") or "tool"),
                    args=update.get("tool_args", {}) or {},
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata,
                        {"trace_kind": "tool_call"},
                    ),
                )
                return

            if event == "tool_result":
                state = str(update.get("state", "complete"))
                result = str(update.get("result", "") or "")
                if state == "error":
                    await stream.error(
                        result,
                        source=self.name,
                        stage=stage,
                        metadata=merge_trace_metadata(
                            base_metadata,
                            {"trace_kind": "tool_result"},
                        ),
                    )
                    return
                await stream.tool_result(
                    tool_name=str(update.get("tool_name", "") or "tool"),
                    result=result,
                    source=self.name,
                    stage=stage,
                    metadata=merge_trace_metadata(
                        base_metadata,
                        {"trace_kind": "tool_result"},
                    ),
                )

        return _trace_bridge
