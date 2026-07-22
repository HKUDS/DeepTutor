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
from deeptutor.services.llm.context_window import resolve_effective_context_window

from .protocol import SessionStoreProtocol

#: When the summarizer's output lands within this fraction of its hard token
#: cap, assume the provider cut it mid-sentence and trim the partial tail.
TRUNCATION_GUARD_RATIO = 0.95


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


def trim_incomplete_tail(text: str) -> str:
    """Drop the trailing partial line from output that hit a hard token cap.

    A summary cut mid-sentence would otherwise be persisted as-is; losing the
    last line is cheaper than carrying a corrupted entry forward.
    """
    lines = text.rstrip().split("\n")
    if len(lines) > 1:
        return "\n".join(lines[:-1]).rstrip()
    return text.rstrip()


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
        store: SessionStoreProtocol,
        history_budget_ratio: float = 0.35,
        summary_target_ratio: float = 0.40,
    ) -> None:
        self.store = store
        self.history_budget_ratio = history_budget_ratio
        self.summary_target_ratio = summary_target_ratio

    def _effective_context_window(self, llm_config: LLMConfig) -> int:
        return resolve_effective_context_window(
            context_window=getattr(llm_config, "context_window", None),
            model=str(getattr(llm_config, "model", "") or ""),
            max_tokens=getattr(llm_config, "max_tokens", None),
        )

    def _history_budget(self, llm_config: LLMConfig) -> int:
        effective_context_window = self._effective_context_window(llm_config)
        return max(256, int(effective_context_window * self.history_budget_ratio))

    def _summary_budget(self, budget: int) -> int:
        return max(96, int(budget * self.summary_target_ratio))

    def _recent_budget(self, budget: int) -> int:
        return max(128, budget - self._summary_budget(budget))

    def _rebuild_source_budget(self, llm_config: LLMConfig) -> int:
        # Raw-rebuild input may use up to half the effective context window;
        # beyond that we degrade to fold-in (existing summary + new turns).
        return max(1024, self._effective_context_window(llm_config) // 2)

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
        # The instruction targets ~80% of the hard cap so the model's own
        # length control — not the max_tokens cut — is the binding limit.
        target_tokens = max(96, int(summary_budget * 0.8))
        system_prompt = (
            "You maintain a running summary of a conversation so future turns can "
            "continue seamlessly. Rewrite the summary from the material provided, "
            "organized under these headings (omit any heading with no content):\n"
            "- Goals: what the user wants to accomplish, and why if stated\n"
            "- Key facts & context: stable facts, definitions, data points, names, "
            "references (files, links, IDs)\n"
            "- Decisions & preferences: choices made, options rejected, style or "
            "format preferences, capability/mode switches\n"
            "- Progress: what has been produced or completed so far\n"
            "- Open items: unanswered questions, pending tasks, known blockers\n"
            "Carry forward still-relevant entries from the existing summary unchanged "
            "unless new information contradicts them; drop only what is obsolete. "
            "Prefer concrete details (numbers, identifiers, exact terms) over "
            "abstract restatement. Never invent information."
        )
        if language.startswith("zh"):
            system_prompt = (
                "你负责维护一份对话的滚动摘要，供后续轮次无缝衔接。请基于给定材料重写摘要，"
                "按以下小节组织（无内容的小节直接省略）：\n"
                "- 目标：用户想完成什么，以及（如有说明）原因\n"
                "- 关键事实与上下文：稳定的事实、定义、数据、名称、引用（文件、链接、ID）\n"
                "- 决定与偏好：已做的选择、被否决的方案、风格/格式偏好、能力或模式切换\n"
                "- 进展：目前已经产出或完成的内容\n"
                "- 待办事项：未回答的问题、未完成的任务、已知阻塞\n"
                "已有摘要中仍然有效的条目应原样保留，仅在新信息与之矛盾时修改，只删除确已过时"
                "的内容。优先保留具体细节（数字、标识符、确切措辞），不要抽象转述，绝不虚构。"
            )
        user_prompt = (
            f"Update the summary using the material below. "
            f"Keep the total under {target_tokens} tokens.\n\n{source_text}"
        )
        if language.startswith("zh"):
            user_prompt = (
                f"请基于下面的材料更新摘要，总长度不超过 {target_tokens} tokens。\n\n{source_text}"
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
            summary = "".join(_chunks).strip()
            if count_tokens(summary) >= int(summary_budget * TRUNCATION_GUARD_RATIO):
                summary = trim_incomplete_tail(summary)
            return summary, events
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
        leaf_message_id: int | None = None,
    ) -> ContextBuildResult:
        session = await self.store.get_session(session_id)
        # When ``leaf_message_id`` is given (edit-branch turn), only the
        # ancestor path of that message is included in context — sibling
        # branches at any depth are excluded.
        messages = await self.store.get_messages_for_context(
            session_id, leaf_message_id=leaf_message_id
        )
        if session is None:
            return ContextBuildResult([], "", "", [], 0, self._history_budget(llm_config))

        budget = self._history_budget(llm_config)
        summary_budget = self._summary_budget(budget)
        recent_budget = self._recent_budget(budget)

        stored_summary = str(session.get("compressed_summary", "") or "").strip()
        summary_up_to_msg_id = int(session.get("summary_up_to_msg_id", 0) or 0)
        # Branch guard: the watermark must sit on this turn's ancestor chain.
        # After an edit-branch switch it may point into a sibling branch — the
        # stored summary would then carry content this branch never saw.
        # Discard both and rebuild from this branch's own messages.
        if summary_up_to_msg_id > 0 and not any(
            int(item.get("id", 0) or 0) == summary_up_to_msg_id for item in messages
        ):
            stored_summary = ""
            summary_up_to_msg_id = 0
        unsummarized = [
            item for item in messages if int(item.get("id", 0) or 0) > summary_up_to_msg_id
        ]

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

        older_unsummarized, recent_messages = self._select_recent_messages(
            unsummarized, recent_budget
        )
        # Everything not retained verbatim: previously summarized messages
        # plus the older unsummarized turns.
        prefix_messages = messages[: len(messages) - len(recent_messages)]
        prefix_transcript = format_messages_as_transcript(prefix_messages)

        # Anti-drift: while the raw prefix still fits the rebuild budget,
        # re-summarize from the original messages instead of folding the
        # previous summary into itself — summary-of-summary loses detail
        # monotonically. Only beyond that budget degrade to fold-in.
        rebuild_from_raw = bool(prefix_transcript) and count_tokens(
            prefix_transcript
        ) <= self._rebuild_source_budget(llm_config)
        merge_parts: list[str] = []
        if rebuild_from_raw:
            merge_parts.append(f"Conversation history to summarize:\n{prefix_transcript}")
        else:
            if stored_summary:
                merge_parts.append(f"Existing summary:\n{stored_summary}")
            older_transcript = format_messages_as_transcript(older_unsummarized)
            if older_transcript:
                merge_parts.append(f"Older turns to fold in:\n{older_transcript}")
        if not merge_parts and recent_messages:
            merge_parts.append(format_messages_as_transcript(recent_messages))

        summarize_ok = True
        try:
            new_summary, events = await self._summarize(
                session_id=session_id,
                language=language,
                source_text="\n\n".join(part for part in merge_parts if part.strip()),
                summary_budget=summary_budget,
                on_event=on_event,
            )
        except Exception:
            summarize_ok = False
            new_summary = ""
            events = []

        if summarize_ok and new_summary:
            # Advance the watermark only on a successful summarize — never
            # past turns that were not actually folded in.
            up_to_msg_id = summary_up_to_msg_id
            if prefix_messages:
                up_to_msg_id = max(summary_up_to_msg_id, int(prefix_messages[-1].get("id", 0) or 0))
            await self.store.update_summary(session_id, new_summary, up_to_msg_id)
            stored_summary = new_summary
            final_history = self._build_history(stored_summary, recent_messages)
        else:
            # Degrade for this turn only: keep the stale summary and as many
            # unsummarized turns as fit; nothing is marked as summarized, so
            # the next turn retries with the full material.
            final_history = self._build_history(stored_summary, unsummarized)
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
    "TRUNCATION_GUARD_RATIO",
    "build_history_text",
    "count_tokens",
    "format_messages_as_transcript",
    "trim_incomplete_tail",
]
