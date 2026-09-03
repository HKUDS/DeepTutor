"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from deeptutor.core.stream import StreamEvent, StreamEventType

from .._turn_runtime_shared import (
    _clip_text,
    _looks_like_error_payload,
    _sanitize_session_title,
    _TurnExecution,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from deeptutor.services.session.protocol import SessionStoreProtocol


class SessionTitleService:
    if TYPE_CHECKING:
        store: SessionStoreProtocol

        async def _publish_live_event(
            self,
            execution: _TurnExecution,
            event: StreamEvent,
        ) -> dict[str, Any]: ...

    async def _maybe_generate_session_title(
        self,
        *,
        execution: _TurnExecution,
        session_id: str,
        ui_language: str,
    ) -> None:
        """Generate a short LLM-written title for a freshly-named session.

        Runs only when the session still carries the ``New conversation``
        sentinel — once a user manually renames the chat (or this method
        has already filled in a title), it short-circuits. Runs on the task
        model when one is configured, and otherwise on the LLM scope already
        active on the calling task, which is the user's currently selected
        model.
        """
        if not session_id:
            return
        session = await self.store.get_session(session_id)
        if not session:
            return
        current_title = str(session.get("title") or "").strip()
        if current_title and current_title != "New conversation":
            return

        messages = await self.store.get_messages(session_id)
        first_user = ""
        first_assistant = ""
        for m in messages:
            role = str(m.get("role") or "")
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            if role == "user" and not first_user:
                first_user = content
            elif role == "assistant" and not first_assistant:
                first_assistant = content
            if first_user and first_assistant:
                break
        if not first_user or not first_assistant:
            return

        title = ""
        try:
            from deeptutor.services.llm import stream as llm_stream

            zh = str(ui_language or "").lower().startswith("zh")
            if zh:
                sys_prompt = (
                    "你需要为一段对话生成一个简洁的标题。"
                    "直接输出标题文本，不要引号、不要 Markdown 格式、"
                    '不要末尾标点、不要 "标题：" 这类前缀。'
                    "标题控制在 4-10 个汉字以内。"
                )
                user_prompt = (
                    "请基于以下对话生成标题：\n\n"
                    f"[用户]\n{_clip_text(first_user, 800)}\n\n"
                    f"[助手]\n{_clip_text(first_assistant, 1500)}"
                )
            else:
                sys_prompt = (
                    "You generate a concise, descriptive title for a "
                    "conversation. Output only the title as plain text "
                    "— no quotes, no markdown, no trailing punctuation, "
                    'no "Title:" prefix. Keep it 4-8 words.'
                )
                user_prompt = (
                    "Generate a title for this conversation:\n\n"
                    f"[User]\n{_clip_text(first_user, 800)}\n\n"
                    f"[Assistant]\n{_clip_text(first_assistant, 1500)}"
                )

            async def _collect_title() -> str:
                buf: list[str] = []
                async for c in llm_stream(
                    prompt=user_prompt,
                    system_prompt=sys_prompt,
                    temperature=0.3,
                    max_tokens=80,
                ):
                    buf.append(c)
                return "".join(buf)

            from deeptutor.services.model_selection.tasks import task_llm_scope

            # The scope is entered before the task is created so `wait_for`'s
            # inner task copies it; with no task model configured it is a no-op.
            with task_llm_scope():
                raw_title = await asyncio.wait_for(_collect_title(), timeout=20.0)
            if _looks_like_error_payload(raw_title):
                logger.debug("Title model streamed an error payload — falling back")
                raw_title = ""
            title = _sanitize_session_title(raw_title)
        except asyncio.TimeoutError:
            logger.debug("Title LLM call timed out — falling back")
        except Exception:
            logger.debug("Title LLM call failed", exc_info=True)

        if not title:
            # Fallback: truncate the first user message so the sidebar
            # doesn't sit on "New conversation" indefinitely when the
            # title model errors out.
            title = first_user[:50] + ("..." if len(first_user) > 50 else "")

        if not title:
            return

        try:
            await self.store.update_session_title(session_id, title)
        except Exception:
            # Not debug: the conversation keeps its placeholder title forever
            # and nothing else reports it. A silent failure here is how the
            # sidebar ends up permanently wrong.
            logger.warning(
                "Could not store generated title for session %s", session_id, exc_info=True
            )
            return

        await self._publish_live_event(
            execution,
            StreamEvent(
                type=StreamEventType.SESSION_META,
                source="turn_runtime",
                stage="title",
                content=title,
                metadata={"title": title, "session_id": session_id},
            ),
        )
