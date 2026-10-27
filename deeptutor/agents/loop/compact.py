"""Shorten the copy of a turn that is sent to the model.

The loop's own message list is the session record and is not replaced. A
compact view keeps the system prompt and the most recent rounds, and replaces
everything older with one continuation note. Result ids in that note are how
the model reads omitted text back.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Any

logger = logging.getLogger(__name__)

Summarizer = Callable[[list[dict[str, Any]]], Awaitable[str]]


def split_rounds(
    messages: list[dict[str, Any]],
    keep_rounds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Split into leading system messages, older rounds, and the kept tail.

    Returns None when there are not enough assistant rounds to shorten.
    """
    start = 0
    head: list[dict[str, Any]] = []
    while start < len(messages) and messages[start].get("role") == "system":
        head.append(messages[start])
        start += 1
    rest = messages[start:]
    assistant_at = [index for index, message in enumerate(rest) if message.get("role") == "assistant"]
    if keep_rounds < 0 or len(assistant_at) <= keep_rounds:
        return None
    cut = assistant_at[-keep_rounds] if keep_rounds else len(rest)
    return head, rest[:cut], rest[cut:]


def _clip(value: Any, limit: int = 240) -> str:
    text = value if isinstance(value, str) else ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def deterministic_note(middle: list[dict[str, Any]]) -> str:
    """Continuation note that keeps result ids and drops long excerpts."""
    from deeptutor.agents.loop.stored_results import result_id_in

    lines = [
        "Earlier rounds were shortened so this request can continue.",
        "The original rounds remain in the session.",
        "Read omitted tool output with read_stored_result using the result_id, offset, and limit.",
        "Do not call the original tool again just to see the rest.",
    ]
    for message in middle:
        role = message.get("role")
        content = message.get("content")
        if role == "tool":
            result_id = result_id_in(str(content or ""))
            name = str(message.get("name") or "tool")
            if result_id:
                lines.append(f"- {name} result_id={result_id}")
            else:
                lines.append(f"- {name}: {_clip(content)}")
        elif role == "assistant":
            note = _clip(content)
            if note:
                lines.append(f"- assistant: {note}")
        elif role == "user" and not message.get("_context_snapshot"):
            note = _clip(content)
            if note:
                lines.append(f"- user: {note}")
    lines.append("Continue the task from the recent rounds that follow this note.")
    return "\n".join(lines)


async def summarize_earlier_rounds(pipeline: Any, middle: list[dict[str, Any]]) -> str:
    """Ask for a short continuation note. Fall back to the deterministic note."""
    note = deterministic_note(middle)
    config = getattr(pipeline, "llm_config", None)
    if config is None:
        return note
    try:
        from deeptutor.services.llm.factory import complete_with_config

        rewritten = await complete_with_config(
            config,
            prompt=(
                "Rewrite the note below as a short continuation brief for an agent "
                "that is mid-task. Keep every result_id exactly. Do not copy long "
                "excerpts. Do not drop unfinished work.\n\n"
                + note
            ),
            system_prompt=(
                "You compress an in-progress session. Return only the brief."
            ),
            max_tokens=512,
        )
    except Exception:
        logger.warning("session compact summary failed; using the deterministic note", exc_info=True)
        return note
    rewritten = str(rewritten or "").strip()
    if not rewritten:
        return note
    # The deterministic note is the source of ids. If the rewrite drops one, keep the note.
    for line in note.splitlines():
        if "result_id=" in line and line.split("result_id=", 1)[1].split()[0] not in rewritten:
            return note
    return rewritten


async def compact_view(
    messages: list[dict[str, Any]],
    *,
    keep_rounds: int,
    summarize: Summarizer,
) -> list[dict[str, Any]] | None:
    """Return a shorter request copy, or None when nothing can be shortened."""
    parts = split_rounds(messages, keep_rounds)
    if parts is None:
        return None
    head, middle, tail = parts
    if not middle:
        return None
    summary = await summarize(middle)
    return [
        *head,
        {"role": "user", "content": f"[Session compact]\n{summary}"},
        *tail,
    ]
