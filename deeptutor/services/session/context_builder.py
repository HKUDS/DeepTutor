"""
Build bounded conversation history for unified chat sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.trace import build_trace_metadata, merge_trace_metadata, new_call_id
from deeptutor.services.llm.config import LLMConfig

from .sqlite_store import SQLiteSessionStore


def count_tokens(text: str) -> int:
    """Estimate token count with tiktoken when available."""
    if not text:
        return 0
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 4)


def format_messages_as_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    role_map = {
        "user": "User",
        "assistant": "Assistant",
        "system": "System",
    }
    for item in messages:
        content = str(item.get("content", "") or "").strip()
        if not content:
            continue
        role = role_map.get(str(item.get("role", "user")), "User")
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def build_history_text(history: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in history:
        role = str(item.get("role", "user"))
        content = str(item.get("content", "") or "").strip()
        if not content:
            continue
        if role == "system":
            lines.append(f"Conversation summary:\n{content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
        else:
            lines.append(f"User: {content}")
    return "\n\n".join(lines)


@dataclass
class ContextBuildResult:
    conversation_history: list[dict[str, Any]]
    conversation_summary: str
    context_text: str
    events: list[StreamEvent]
    token_count: int
    budget: int


class _ContextSummaryAgent(BaseAgent):
    """Small helper agent for compressing older conversation turns."""

    def __init__(self, language: str = "en") -> None:
        super().__init__(
            module_name="chat",
            agent_name="context_summary_agent",
            language=language,
        )

    async def process(self, *_args, **_kwargs) -> dict[str, Any]:
        raise NotImplementedError


class ContextBuilder:
    """Construct a bounded conversation history plus optional summary trace."""

    def __init__(
        self,
        store: SQLiteSessionStore,
        history_budget_ratio: float = 0.35,
        summary_target_ratio: float = 0.40,
    ) -> None:
        self.store = store
        self.history_budget_ratio = history_budget_ratio
        self.summary_target_ratio = summary_target_ratio

    def _history_budget(self, llm_config: LLMConfig) -> int:
        configured = int(getattr(llm_config, "max_tokens", 4096) or 4096)
        return max(256, int(configured * self.history_budget_ratio))

    def _summary_budget(self, budget: int) -> int:
        return max(96, int(budget * self.summary_target_ratio))

    def _recent_budget(self, budget: int) -> int:
        return max(128, budget - self._summary_budget(budget))

    def _build_history(self, summary: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        cleaned_summary = summary.strip()
        if cleaned_summary:
            history.append({"role": "system", "content": cleaned_summary})
        history.extend(
            {
                "role": item.get("role", "user"),
                "content": str(item.get("content", "") or ""),
            }
            for item in messages
            if item.get("role") in {"user", "assistant"}
            and str(item.get("content", "") or "").strip()
        )
        return history

    async def _append_event(
        self,
        events: list[StreamEvent],
        event: StreamEvent,
        on_event: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> None:
        events.append(event)
        if on_event is not None:
            await on_event(event)

    def _select_recent_messages(
        self,
        messages: list[dict[str, Any]],
        recent_budget: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        selected: list[dict[str, Any]] = []
        total = 0
        for item in reversed(messages):
            content = str(item.get("content", "") or "")
            tokens = count_tokens(content)
            if selected and total + tokens > recent_budget:
                break
            selected.insert(0, item)
            total += tokens
        cutoff = len(messages) - len(selected)
        return messages[:cutoff], selected

    async def _summarize(
        self,
        *,
        session_id: str,
        language: str,
        source_text: str,
        summary_budget: int,
        on_event: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> tuple[str, list[StreamEvent]]:
        events: list[StreamEvent] = []
        if not source_text.strip():
            return "", events

        agent = _ContextSummaryAgent(language=language)
        trace_meta = build_trace_metadata(
            call_id=new_call_id("context-summary"),
            phase="summarize_context",
            label="Summarize context",
            call_kind="llm_summarization",
            trace_id=session_id,
        )

        async def _trace_bridge(update: dict[str, Any]) -> None:
            if str(update.get("event", "")) != "llm_call":
                return
            state = str(update.get("state", "running"))
            metadata = {
                key: value
                for key, value in update.items()
                if key not in {"event", "state", "response", "chunk"}
            }
            if state == "running":
                await self._append_event(
                    events,
                    StreamEvent(
                        type=StreamEventType.PROGRESS,
                        source="context_builder",
                        stage="summarize_context",
                        content="Compressing conversation history...",
                        metadata=merge_trace_metadata(
                            metadata,
                            {"trace_kind": "call_status", "call_state": "running"},
                        ),
                    ),
                    on_event,
                )
            elif state == "complete":
                response = str(update.get("response", "") or "")
                if response:
                    await self._append_event(
                        events,
                        StreamEvent(
                            type=StreamEventType.CONTENT,
                            source="context_builder",
                            stage="summarize_context",
                            content=response,
                            metadata=merge_trace_metadata(
                                metadata,
                                {"trace_kind": "llm_output"},
                            ),
                        ),
                        on_event,
                    )
                await self._append_event(
                    events,
                    StreamEvent(
                        type=StreamEventType.PROGRESS,
                        source="context_builder",
                        stage="summarize_context",
                        content="",
                        metadata=merge_trace_metadata(
                            metadata,
                            {"trace_kind": "call_status", "call_state": "complete"},
                        ),
                    ),
                    on_event,
                )
            elif state == "error":
                await self._append_event(
                    events,
                    StreamEvent(
                        type=StreamEventType.ERROR,
                        source="context_builder",
                        stage="summarize_context",
                        content=str(update.get("response", "") or "Context summarization failed."),
                        metadata=merge_trace_metadata(metadata, {"call_state": "error"}),
                    ),
                    on_event,
                )

        agent.set_trace_callback(_trace_bridge)
        await self._append_event(
            events,
            StreamEvent(
                type=StreamEventType.STAGE_START,
                source="context_builder",
                stage="summarize_context",
                metadata=trace_meta,
            ),
            on_event,
        )
        system_prompt = (
            "You compress conversation history for future turns. Preserve factual context, "
            "user goals, constraints, decisions, unresolved questions, and any capability "
            "switches. Keep the summary concise and faithful. Use bullet points only if useful."
        )
        if language.startswith("zh"):
            system_prompt = (
                "你负责把对话历史压缩成后续轮次可直接使用的上下文。保留用户目标、约束、已做决定、"
                "未解决问题，以及能力切换带来的关键信息。总结要忠实、紧凑，不要虚构。"
            )
        user_prompt = (
            f"Compress the following conversation history into <= {summary_budget} tokens.\n\n"
            f"{source_text}"
        )
        if language.startswith("zh"):
            user_prompt = (
                f"请把下面的对话历史压缩到不超过 {summary_budget} tokens 的长度，"
                "供后续对话直接继承上下文。\n\n"
                f"{source_text}"
            )
        try:
            _chunks: list[str] = []
            async for _c in agent.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=summary_budget,
                stage="summarize_context",
                trace_meta=trace_meta,
            ):
                _chunks.append(_c)
            summary = "".join(_chunks)
            return summary.strip(), events
        finally:
            await self._append_event(
                events,
                StreamEvent(
                    type=StreamEventType.STAGE_END,
                    source="context_builder",
                    stage="summarize_context",
                    metadata=trace_meta,
                ),
                on_event,
            )

    async def build(
        self,
        *,
        session_id: str,
        llm_config: LLMConfig,
        language: str = "en",
        on_event: Callable[[StreamEvent], Awaitable[None]] | None = None,
    ) -> ContextBuildResult:
        session = await self.store.get_session(session_id)
        messages = await self.store.get_messages_for_context(session_id)
        if session is None:
            return ContextBuildResult([], "", "", [], 0, self._history_budget(llm_config))

        budget = self._history_budget(llm_config)
        summary_budget = self._summary_budget(budget)
        recent_budget = self._recent_budget(budget)

        stored_summary = str(session.get("compressed_summary", "") or "").strip()
        summary_up_to_msg_id = int(session.get("summary_up_to_msg_id", 0) or 0)
        unsummarized = [item for item in messages if int(item.get("id", 0) or 0) > summary_up_to_msg_id]

        current_history = self._build_history(stored_summary, unsummarized)
        current_tokens = count_tokens(build_history_text(current_history))
        if current_tokens <= budget:
            return ContextBuildResult(
                conversation_history=current_history,
                conversation_summary=stored_summary,
                context_text=build_history_text(current_history),
                events=[],
                token_count=current_tokens,
                budget=budget,
            )

        older_unsummarized, recent_messages = self._select_recent_messages(unsummarized, recent_budget)
        merge_parts: list[str] = []
        if stored_summary:
            merge_parts.append(f"Existing summary:\n{stored_summary}")
        older_transcript = format_messages_as_transcript(older_unsummarized)
        if older_transcript:
            merge_parts.append(f"Older turns to fold in:\n{older_transcript}")
        if not merge_parts and recent_messages:
            merge_parts.append(format_messages_as_transcript(recent_messages))

        try:
            new_summary, events = await self._summarize(
                session_id=session_id,
                language=language,
                source_text="\n\n".join(part for part in merge_parts if part.strip()),
                summary_budget=summary_budget,
                on_event=on_event,
            )
        except Exception:
            new_summary = stored_summary
            events = []

        up_to_msg_id = summary_up_to_msg_id
        if older_unsummarized:
            up_to_msg_id = int(older_unsummarized[-1]["id"])
        elif stored_summary:
            up_to_msg_id = summary_up_to_msg_id

        if new_summary:
            await self.store.update_summary(session_id, new_summary, up_to_msg_id)
            stored_summary = new_summary

        final_history = self._build_history(stored_summary, recent_messages)
        while len(final_history) > 1 and count_tokens(build_history_text(final_history)) > budget:
            summary_prefix = 1 if final_history and final_history[0].get("role") == "system" else 0
            if len(final_history) <= summary_prefix + 1:
                break
            final_history.pop(summary_prefix)

        final_text = build_history_text(final_history)
        return ContextBuildResult(
            conversation_history=final_history,
            conversation_summary=stored_summary,
            context_text=final_text,
            events=events,
            token_count=count_tokens(final_text),
            budget=budget,
        )


__all__ = [
    "ContextBuildResult",
    "ContextBuilder",
    "build_history_text",
    "count_tokens",
    "format_messages_as_transcript",
]
