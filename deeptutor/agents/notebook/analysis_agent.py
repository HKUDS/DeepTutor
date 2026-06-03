"""Notebook analysis agent for cross-record grounding."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.trace import build_trace_metadata, derive_trace_metadata, new_call_id
from deeptutor.services.config import parse_language
from deeptutor.services.llm import clean_thinking_tags, get_llm_config, get_token_limit_kwargs
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.prompt.language import append_language_directive
from deeptutor.services.prompt.manager import get_prompt_manager
from deeptutor.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

EventSink = Callable[[StreamEvent], Awaitable[None]]


def _clip_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


class NotebookAnalysisAgent:
    """Analyze selected notebook records before the main capability runs."""

    def __init__(self, language: str = "en") -> None:
        self.language = parse_language(language)
        self.llm_config = get_llm_config()
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        # Prompts come from deeptutor/agents/notebook/prompts/{en,zh}/analysis_agent.yaml
        # so the three-stage notebook reasoning loop stays bilingual without
        # carrying language-specific text in this file.
        self._prompts = get_prompt_manager().load_prompts(
            "notebook", "analysis_agent", self.language
        )

    async def analyze(
        self,
        *,
        user_question: str,
        records: list[dict[str, Any]],
        emit: EventSink | None = None,
    ) -> str:
        thinking_text = await self._stage_thinking(
            user_question=user_question, records=records, emit=emit
        )
        selected_records = await self._stage_acting(
            user_question=user_question,
            thinking_text=thinking_text,
            records=records,
            emit=emit,
        )
        observation = await self._stage_observing(
            user_question=user_question,
            thinking_text=thinking_text,
            selected_records=selected_records,
            emit=emit,
        )

        if emit is not None:
            await emit(
                StreamEvent(
                    type=StreamEventType.RESULT,
                    source="notebook_analysis",
                    metadata={
                        "observation": observation,
                        "selected_record_ids": [
                            record.get("id", "") for record in selected_records
                        ],
                    },
                )
            )
        return observation

    async def _stage_thinking(
        self,
        *,
        user_question: str,
        records: list[dict[str, Any]],
        emit: EventSink | None,
    ) -> str:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("notebook-thinking"),
            phase="thinking",
            label="Notebook reasoning",
            call_kind="llm_reasoning",
            trace_id="notebook-thinking",
            trace_role="thought",
            trace_group="stage",
        )
        await self._emit_stage_start("notebook_thinking", trace_meta, emit)
        chunks: list[str] = []
        async for chunk in llm_stream(
            prompt=self._thinking_prompt(user_question, records),
            system_prompt=self._thinking_system_prompt(),
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            temperature=0.2,
            **self._token_kwargs(900),
        ):
            if not chunk:
                continue
            chunks.append(chunk)
            if emit is not None:
                await emit(
                    StreamEvent(
                        type=StreamEventType.THINKING,
                        source="notebook_analysis",
                        stage="notebook_thinking",
                        content=chunk,
                        metadata=derive_trace_metadata(trace_meta, trace_kind="llm_chunk"),
                    )
                )
        await self._emit_stage_end("notebook_thinking", trace_meta, emit)
        return clean_thinking_tags("".join(chunks), self.binding, self.model).strip()

    async def _stage_acting(
        self,
        *,
        user_question: str,
        thinking_text: str,
        records: list[dict[str, Any]],
        emit: EventSink | None,
    ) -> list[dict[str, Any]]:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("notebook-acting"),
            phase="acting",
            label="Notebook selection",
            call_kind="tool_planning",
            trace_id="notebook-acting",
            trace_role="tool",
            trace_group="tool_call",
        )
        await self._emit_stage_start("notebook_acting", trace_meta, emit)
        _chunks: list[str] = []
        async for _c in llm_stream(
            prompt=self._acting_prompt(user_question, thinking_text, records),
            system_prompt=self._acting_system_prompt(),
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            temperature=0.1,
            **self._token_kwargs(500),
        ):
            _chunks.append(_c)
        raw = "".join(_chunks)
        payload = parse_json_response(raw, logger_instance=logger, fallback={})
        selected_ids = payload.get("selected_record_ids") if isinstance(payload, dict) else []
        if not isinstance(selected_ids, list):
            selected_ids = []

        wanted = []
        seen: set[str] = set()
        record_map = {str(record.get("id", "")): record for record in records}
        for record_id in selected_ids:
            key = str(record_id or "").strip()
            if not key or key in seen or key not in record_map:
                continue
            wanted.append(record_map[key])
            seen.add(key)
            if len(wanted) >= 5:
                break

        if not wanted:
            wanted = records[: min(5, len(records))]

        if emit is not None:
            await emit(
                StreamEvent(
                    type=StreamEventType.TOOL_CALL,
                    source="notebook_analysis",
                    stage="notebook_acting",
                    content="notebook_lookup",
                    metadata=derive_trace_metadata(
                        trace_meta,
                        trace_kind="tool_call",
                        args={"selected_record_ids": [record.get("id", "") for record in wanted]},
                    ),
                )
            )
            await emit(
                StreamEvent(
                    type=StreamEventType.TOOL_RESULT,
                    source="notebook_analysis",
                    stage="notebook_acting",
                    content=self._tool_result_text(wanted),
                    metadata=derive_trace_metadata(
                        trace_meta,
                        trace_kind="tool_result",
                        tool="notebook_lookup",
                    ),
                )
            )
        await self._emit_stage_end("notebook_acting", trace_meta, emit)
        return wanted

    async def _stage_observing(
        self,
        *,
        user_question: str,
        thinking_text: str,
        selected_records: list[dict[str, Any]],
        emit: EventSink | None,
    ) -> str:
        trace_meta = build_trace_metadata(
            call_id=new_call_id("notebook-observing"),
            phase="observing",
            label="Notebook observation",
            call_kind="llm_observation",
            trace_id="notebook-observing",
            trace_role="observe",
            trace_group="stage",
        )
        await self._emit_stage_start("notebook_observing", trace_meta, emit)
        chunks: list[str] = []
        async for chunk in llm_stream(
            prompt=self._observing_prompt(user_question, thinking_text, selected_records),
            system_prompt=self._observing_system_prompt(),
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            temperature=0.2,
            **self._token_kwargs(1200),
        ):
            if not chunk:
                continue
            chunks.append(chunk)
            if emit is not None:
                await emit(
                    StreamEvent(
                        type=StreamEventType.OBSERVATION,
                        source="notebook_analysis",
                        stage="notebook_observing",
                        content=chunk,
                        metadata=derive_trace_metadata(trace_meta, trace_kind="observation"),
                    )
                )
        await self._emit_stage_end("notebook_observing", trace_meta, emit)
        return clean_thinking_tags("".join(chunks), self.binding, self.model).strip()

    async def _emit_stage_start(
        self,
        stage: str,
        metadata: dict[str, Any],
        emit: EventSink | None,
    ) -> None:
        if emit is None:
            return
        await emit(
            StreamEvent(
                type=StreamEventType.STAGE_START,
                source="notebook_analysis",
                stage=stage,
                metadata=metadata,
            )
        )

    async def _emit_stage_end(
        self,
        stage: str,
        metadata: dict[str, Any],
        emit: EventSink | None,
    ) -> None:
        if emit is None:
            return
        await emit(
            StreamEvent(
                type=StreamEventType.STAGE_END,
                source="notebook_analysis",
                stage=stage,
                metadata=metadata,
            )
        )

    def _stage_section(self, stage: str) -> dict[str, Any]:
        section = self._prompts.get(stage)
        return section if isinstance(section, dict) else {}

    def _stage_text(self, stage: str, field: str) -> str:
        section = self._stage_section(stage)
        return str(section.get(field, "")).strip()

    def _thinking_system_prompt(self) -> str:
        return append_language_directive(self._stage_text("thinking", "system"), self.language)

    def _acting_system_prompt(self) -> str:
        return append_language_directive(self._stage_text("acting", "system"), self.language)

    def _observing_system_prompt(self) -> str:
        return append_language_directive(self._stage_text("observing", "system"), self.language)

    def _thinking_prompt(self, user_question: str, records: list[dict[str, Any]]) -> str:
        return self._stage_text("thinking", "user_template").format(
            user_question=user_question.strip() or "(empty)",
            catalog=self._summary_catalog(records),
        )

    def _acting_prompt(
        self,
        user_question: str,
        thinking_text: str,
        records: list[dict[str, Any]],
    ) -> str:
        return self._stage_text("acting", "user_template").format(
            user_question=user_question.strip() or "(empty)",
            thinking_text=thinking_text or "(empty)",
            catalog=self._summary_catalog(records),
        )

    def _observing_prompt(
        self,
        user_question: str,
        thinking_text: str,
        selected_records: list[dict[str, Any]],
    ) -> str:
        detailed_blocks = (
            "\n\n".join(
                [
                    "\n".join(
                        [
                            f"Record ID: {record.get('id', '')}",
                            f"Notebook: {record.get('notebook_name', '')}",
                            f"Title: {record.get('title', '')}",
                            f"Summary: {record.get('summary', '')}",
                            f"Content:\n{_clip_text(record.get('output', ''), 2500)}",
                        ]
                    )
                    for record in selected_records
                ]
            )
            or "(none)"
        )
        return self._stage_text("observing", "user_template").format(
            user_question=user_question.strip() or "(empty)",
            thinking_text=thinking_text or "(empty)",
            detailed_blocks=detailed_blocks,
        )

    def _summary_catalog(self, records: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for record in records:
            lines.append(
                " | ".join(
                    [
                        f"id={record.get('id', '')}",
                        f"notebook={record.get('notebook_name', '')}",
                        f"type={record.get('type', '')}",
                        f"title={_clip_text(record.get('title', ''), 80)}",
                        f"summary={_clip_text(record.get('summary', '') or record.get('title', ''), 240)}",
                    ]
                )
            )
        return "\n".join(lines) if lines else "(none)"

    def _tool_result_text(self, records: list[dict[str, Any]]) -> str:
        blocks = []
        for record in records:
            blocks.append(
                "\n".join(
                    [
                        f"- {record.get('id', '')} | {record.get('notebook_name', '')} | {record.get('title', '')}",
                        _clip_text(record.get("output", ""), 400),
                    ]
                )
            )
        return "\n\n".join(blocks) if blocks else "(none)"

    def _token_kwargs(self, max_tokens: int) -> dict[str, Any]:
        if not self.model:
            return {}
        return get_token_limit_kwargs(self.model, max_tokens)
