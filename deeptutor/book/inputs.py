"""
BookInputs Fusion
=================

Merges the four input sources (user intent, chat history, notebook references,
knowledge bases) into a structured ``IdeationContext`` text block consumed by
``IdeationAgent``.

Reuses:
- ``deeptutor.services.session.get_session_store`` for chat history
- ``deeptutor.services.notebook.notebook_manager`` for notebook records
- ``deeptutor.agents.notebook.NotebookAnalysisAgent`` for context distillation
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from .models import (
    BookInputs,
    ChatMessageSnapshot,
    ChatSelection,
    NotebookRef,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Output container
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class IdeationContext:
    """Structured text+metadata bundle consumed by Stage 1 (Ideation)."""

    user_intent: str = ""
    chat_history_text: str = ""
    notebook_context: str = ""
    question_notebook_text: str = ""
    knowledge_bases: list[str] = field(default_factory=list)
    notebook_record_count: int = 0
    chat_message_count: int = 0
    question_entry_count: int = 0

    def render(self) -> str:
        """Render as a single multi-section prompt block."""
        sections: list[str] = []
        sections.append(f"[User Intent]\n{(self.user_intent or '(empty)').strip()}")

        if self.notebook_context.strip():
            sections.append(f"[Notebook Context]\n{self.notebook_context.strip()}")
        elif self.notebook_record_count == 0:
            sections.append("[Notebook Context]\n(no notebook records selected)")

        if self.question_notebook_text.strip():
            sections.append(f"[Question Notebook]\n{self.question_notebook_text.strip()}")
        elif self.question_entry_count == 0:
            sections.append("[Question Notebook]\n(no quiz entries selected)")

        if self.chat_history_text.strip():
            sections.append(f"[Past Conversations]\n{self.chat_history_text.strip()}")
        elif self.chat_message_count == 0:
            sections.append("[Past Conversations]\n(none)")

        if self.knowledge_bases:
            sections.append(
                "[Knowledge Sources]\n" + "\n".join(f"- {name}" for name in self.knowledge_bases)
            )
        else:
            sections.append("[Knowledge Sources]\n(no knowledge bases attached)")

        return "\n\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _clip_text(value: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


async def _resolve_chat_selections(
    selections: list[ChatSelection],
    *,
    limit_per_session: int = 60,
) -> list[ChatMessageSnapshot]:
    """Pull messages for one or more sessions, optionally filtered by id."""
    if not selections:
        return []
    try:
        from deeptutor.services.session import get_session_store

        store = get_session_store()
    except Exception as exc:
        logger.warning(f"Chat session store unavailable: {exc}")
        return []

    snapshots: list[ChatMessageSnapshot] = []
    for sel in selections:
        sid = (sel.session_id or "").strip()
        if not sid:
            continue
        try:
            messages = await store.get_messages(sid)
        except Exception as exc:
            logger.warning(f"Failed to fetch chat history for {sid}: {exc}")
            continue

        wanted_ids = {int(mid) for mid in sel.message_ids if mid is not None}
        candidates: list[dict[str, Any]]
        if wanted_ids:
            candidates = [
                m for m in messages if isinstance(m, dict) and int(m.get("id") or -1) in wanted_ids
            ]
        else:
            candidates = list(messages[-limit_per_session:])

        for msg in candidates:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            if role not in {"user", "assistant", "system"}:
                continue
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            snapshots.append(
                ChatMessageSnapshot(
                    role=role,
                    content=content,
                    capability=str(msg.get("capability") or ""),
                    created_at=float(msg.get("created_at") or 0.0),
                )
            )

    snapshots.sort(key=lambda m: m.created_at)
    return snapshots


def _format_chat_history(messages: list[ChatMessageSnapshot]) -> str:
    if not messages:
        return ""
    lines = []
    for msg in messages:
        snippet = _clip_text(msg.content, 600)
        prefix = msg.role.capitalize()
        if msg.capability:
            prefix = f"{prefix}/{msg.capability}"
        lines.append(f"- {prefix}: {snippet}")
    return "\n".join(lines)


def _normalize_notebook_refs(raw: list[dict[str, Any]] | None) -> list[NotebookRef]:
    refs: list[NotebookRef] = []
    if not raw:
        return refs
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            refs.append(NotebookRef.model_validate(item))
        except Exception as exc:
            logger.warning(f"Invalid notebook reference {item}: {exc}")
    return refs


async def _resolve_notebook_context(
    user_intent: str,
    notebook_refs: list[NotebookRef],
    *,
    language: str,
) -> tuple[str, int]:
    """Return (context_text, record_count). 0 records → empty context."""
    if not notebook_refs:
        return "", 0
    try:
        from deeptutor.services.notebook import notebook_manager

        records = notebook_manager.get_records_by_references(
            [ref.model_dump() for ref in notebook_refs]
        )
    except Exception as exc:
        logger.warning(f"Failed to resolve notebook records: {exc}")
        return "", 0

    if not records:
        return "", 0

    try:
        from deeptutor.agents.notebook import NotebookAnalysisAgent

        agent = NotebookAnalysisAgent(language=language)
        context = await agent.analyze(user_question=user_intent, records=records)
    except Exception as exc:
        logger.warning(f"NotebookAnalysisAgent failed: {exc}; using raw record summary fallback")
        # Fallback: list titles/summaries so we still inject *something*
        lines = []
        for record in records[:8]:
            title = str(record.get("title") or record.get("id") or "(untitled)")
            summary = _clip_text(str(record.get("summary") or record.get("output") or ""), 400)
            notebook = str(record.get("notebook_name") or "")
            lines.append(f"- [{notebook}] {title}: {summary}")
        context = "\n".join(lines)

    return context, len(records)


def _format_quiz_entry(item: dict[str, Any]) -> str:
    q = _clip_text(str(item.get("question") or ""), 240)
    ans = _clip_text(str(item.get("correct_answer") or ""), 80)
    user_ans = _clip_text(str(item.get("user_answer") or ""), 80)
    mark = "✓" if item.get("is_correct") else "✗"
    return f"- [{mark}] Q: {q}\n  A: {ans}\n  User: {user_ans or '(no attempt)'}"


async def _resolve_question_notebook(
    category_ids: list[int] | None,
    entry_ids: list[int] | None,
    *,
    limit_per_category: int = 50,
) -> tuple[str, int]:
    """Pull quiz entries by category and/or by entry id, render a digest."""
    if not category_ids and not entry_ids:
        return "", 0
    try:
        from deeptutor.services.session import get_session_store

        store = get_session_store()
    except Exception as exc:
        logger.warning(f"Question notebook unavailable: {exc}")
        return "", 0

    blocks: list[str] = []
    seen: set[int] = set()

    for cat_id in category_ids or []:
        try:
            result = await store.list_notebook_entries(
                category_id=int(cat_id), limit=limit_per_category
            )
        except Exception as exc:
            logger.warning(f"list_notebook_entries({cat_id}) failed: {exc}")
            continue
        items = result.get("items") or []
        if not items:
            continue
        lines = [f"## Category {cat_id}"]
        for item in items[:limit_per_category]:
            eid = int(item.get("id") or 0)
            if eid in seen:
                continue
            seen.add(eid)
            lines.append(_format_quiz_entry(item))
        blocks.append("\n".join(lines))

    if entry_ids:
        loose: list[str] = []
        for eid in entry_ids:
            if int(eid) in seen:
                continue
            try:
                item = await store.get_notebook_entry(int(eid))
            except Exception as exc:
                logger.warning(f"get_notebook_entry({eid}) failed: {exc}")
                continue
            if not item:
                continue
            seen.add(int(eid))
            loose.append(_format_quiz_entry(item))
        if loose:
            blocks.append("## Picked entries\n" + "\n".join(loose))

    return "\n\n".join(blocks), len(seen)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_chat_selections(
    raw: list[dict[str, Any]] | None,
    legacy_session_id: str = "",
) -> list[ChatSelection]:
    sels: list[ChatSelection] = []
    if raw:
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                sels.append(ChatSelection.model_validate(item))
            except Exception as exc:
                logger.warning(f"Invalid chat selection {item}: {exc}")
    if not sels and legacy_session_id:
        sels.append(ChatSelection(session_id=legacy_session_id, message_ids=[]))
    return sels


async def build_book_inputs(
    *,
    user_intent: str,
    chat_session_id: str = "",
    chat_selections: list[dict[str, Any]] | None = None,
    notebook_refs: list[dict[str, Any]] | None = None,
    knowledge_bases: list[str] | None = None,
    question_categories: list[int] | None = None,
    question_entries: list[int] | None = None,
    language: str = "en",
    chat_history_limit: int = 60,
) -> tuple[BookInputs, IdeationContext]:
    """Capture the four-source snapshot and produce the IdeationContext."""

    intent = (user_intent or "").strip()
    refs = _normalize_notebook_refs(notebook_refs)
    kb_list = [kb.strip() for kb in (knowledge_bases or []) if isinstance(kb, str) and kb.strip()]
    cat_ids = [int(c) for c in (question_categories or []) if c is not None]
    entry_ids = [int(e) for e in (question_entries or []) if e is not None]
    sels = _normalize_chat_selections(chat_selections, chat_session_id)

    chat_messages = await _resolve_chat_selections(sels, limit_per_session=chat_history_limit)
    chat_history_text = _format_chat_history(chat_messages)

    notebook_context, record_count = await _resolve_notebook_context(
        intent, refs, language=language
    )
    question_text, question_count = await _resolve_question_notebook(cat_ids, entry_ids)

    book_inputs = BookInputs(
        user_intent=intent,
        chat_session_id=chat_session_id,
        chat_selections=sels,
        chat_history=chat_messages,
        notebook_refs=refs,
        knowledge_bases=kb_list,
        question_categories=cat_ids,
        question_entries=entry_ids,
        language=language,
    )
    ideation_ctx = IdeationContext(
        user_intent=intent,
        chat_history_text=chat_history_text,
        notebook_context=notebook_context,
        question_notebook_text=question_text,
        knowledge_bases=kb_list,
        notebook_record_count=record_count,
        chat_message_count=len(chat_messages),
        question_entry_count=question_count,
    )

    return book_inputs, ideation_ctx


__all__ = ["IdeationContext", "build_book_inputs"]
