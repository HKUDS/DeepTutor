"""Compatibility adapter for legacy question-generation entry points.

The old ``AgentCoordinator`` implementation was replaced by
``QuestionPipeline``. A few API/tool modules still import the coordinator
name, so this module preserves that surface while delegating all real work
to the new pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import logging
from pathlib import Path
from typing import Any

from deeptutor.agents.question.mimic_source import parse_exam_paper_to_templates
from deeptutor.agents.question.pipeline import QuestionPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent
from deeptutor.core.stream_bus import StreamBus
from deeptutor.services.path_service import get_path_service
from deeptutor.services.settings.interface_settings import get_ui_language

logger = logging.getLogger(__name__)

WsCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class AgentCoordinator:
    """Legacy facade backed by :class:`QuestionPipeline`.

    New code should prefer ``DeepQuestionCapability`` or ``QuestionPipeline``
    directly. This class exists so older WebSocket routes and the
    ``tools.question.exam_mimic`` helper keep importing and running.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        kb_name: str | None = None,
        language: str | None = None,
        output_dir: str | None = None,
        enabled_tools: list[str] | None = None,
        enable_idea_rag: bool | None = None,
    ) -> None:
        # The new pipeline reads provider settings from the shared config
        # service. Keep these attributes only for compatibility/debugging.
        self.api_key = api_key
        self.base_url = base_url
        self.api_version = api_version
        self.kb_name = (kb_name or "").strip() or None
        self.enable_idea_rag = True if enable_idea_rag is None else bool(enable_idea_rag)
        self.language = language or get_ui_language(default="en")
        self.output_dir = output_dir
        self.enabled_tools = list(enabled_tools or [])
        self._ws_callback: WsCallback | None = None

    def set_ws_callback(self, callback: WsCallback | None) -> None:
        self._ws_callback = callback

    async def generate_from_topic(
        self,
        *,
        user_topic: str,
        num_questions: int = 1,
        difficulty: str = "",
        question_types: list[str] | None = None,
        per_type_counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Generate a quiz from a topic using the new pipeline."""

        context = self._build_context(user_message=user_topic)
        pipeline = self._build_pipeline()
        stream = self._new_stream_bus()
        result = await self._run_with_forwarding(
            stream,
            pipeline.run(
                context=context,
                user_message=user_topic,
                num_questions=max(1, int(num_questions or 1)),
                difficulty=difficulty,
                question_types=question_types or [],
                per_type_counts=per_type_counts or {},
                stream=stream,
            ),
        )
        return self._legacy_summary(result)

    async def generate_from_exam(
        self,
        *,
        exam_paper_path: str,
        max_questions: int = 10,
        paper_mode: str = "upload",
    ) -> dict[str, Any]:
        """Generate mimic questions from an uploaded PDF or parsed paper dir."""

        paper_path = str(exam_paper_path or "").strip()
        if not paper_path:
            return {"success": False, "error": "exam_paper_path is required."}

        try:
            await self._emit_callback(
                {
                    "type": "status",
                    "stage": "parsing",
                    "content": "Extracting question templates from exam paper...",
                }
            )
            output_dir = self._resolve_output_dir()
            templates, trace = await parse_exam_paper_to_templates(
                paper_path,
                max_questions=max(1, int(max_questions or 1)),
                paper_mode=paper_mode,
                output_dir=output_dir,
            )
            if not templates:
                return {
                    "success": False,
                    "error": "No questions could be extracted from the exam paper.",
                    "template_count": 0,
                    "results": [],
                    "trace": trace,
                }

            context = self._build_context(user_message="Mimic this exam paper")
            pipeline = self._build_pipeline()
            stream = self._new_stream_bus()
            result = await self._run_with_forwarding(
                stream,
                pipeline.run(
                    context=context,
                    user_message=context.user_message,
                    num_questions=len(templates),
                    templates_override=templates,
                    stream=stream,
                ),
            )
            summary = self._legacy_summary(result)
            summary["trace"] = trace
            return summary
        except Exception as exc:
            logger.exception("Legacy AgentCoordinator.generate_from_exam failed: %s", exc)
            return {"success": False, "error": str(exc), "results": []}

    def _build_context(self, *, user_message: str) -> UnifiedContext:
        kb_name = self._active_kb_name()
        return UnifiedContext(
            session_id=self._session_id(),
            user_message=user_message,
            enabled_tools=self.enabled_tools,
            active_capability="deep_question",
            knowledge_bases=[kb_name] if kb_name else [],
            language=self.language,
        )

    def _build_pipeline(self) -> QuestionPipeline:
        return QuestionPipeline(
            language=self.language,
            kb_name=self._active_kb_name(),
            enabled_tools=self.enabled_tools,
        )

    def _active_kb_name(self) -> str | None:
        return self.kb_name if self.enable_idea_rag else None

    def _new_stream_bus(self) -> StreamBus:
        return StreamBus()

    async def _run_with_forwarding(
        self,
        stream: StreamBus,
        pipeline_call: Awaitable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Run a pipeline coroutine and forward its stream events if possible."""

        forwarder = asyncio.create_task(self._forward_stream(stream))
        try:
            return await pipeline_call
        finally:
            await stream.close()
            try:
                await forwarder
            except Exception:
                logger.debug("Question stream forwarding task failed", exc_info=True)

    async def _forward_stream(self, stream: StreamBus) -> None:
        async for event in stream.subscribe():
            await self._emit_callback(self._event_payload(event))

    @staticmethod
    def _event_payload(event: StreamEvent) -> dict[str, Any]:
        payload = event.to_dict()
        if event.type.value == "result":
            payload.setdefault("content", event.metadata.get("response", ""))
        return payload

    async def _emit_callback(self, payload: dict[str, Any]) -> None:
        if self._ws_callback is None:
            return
        maybe_awaitable = self._ws_callback(payload)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    def _resolve_output_dir(self) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return get_path_service().get_question_dir() / "mimic_papers"

    def _session_id(self) -> str:
        if self.output_dir:
            return Path(self.output_dir).name or "legacy-question"
        return "legacy-question"

    @staticmethod
    def _legacy_summary(result: dict[str, Any]) -> dict[str, Any]:
        summary = dict(result.get("summary") or {})
        if not summary:
            summary["success"] = False
            summary["results"] = []
        summary.setdefault("response", result.get("response", ""))
        summary.setdefault("mode", result.get("mode", "custom"))
        if "metadata" in result:
            summary.setdefault("metadata", result["metadata"])
        summary.setdefault("results", [])
        for item in summary["results"]:
            if isinstance(item, dict) and "success" not in item:
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                item["success"] = not bool(metadata.get("error"))
        summary.setdefault("requested", summary.get("template_count", 0))
        summary.setdefault("completed", 0)
        summary.setdefault("failed", 0)
        summary.setdefault("success", bool(summary.get("completed")))
        return summary


__all__ = ["AgentCoordinator"]
