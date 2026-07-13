"""Quiz history loader — surfaces prior quiz items in the same session.

Used by :class:`QuestionPipeline` so the Explore phase can articulate
which topics have already been tested, which the learner got wrong, and
how the next round should avoid duplication / optionally target weak
spots.

Single public entry point:

* :func:`load_session_quiz_history` — async, takes ``session_id`` and an
  upper bound, returns a chronological list of
  :class:`~deeptutor.agents.question.pipeline.QuizHistoryEntry`.

Source of truth: the ``notebook_entries`` table (populated by
``POST /sessions/{id}/quiz-results``). Messages are *not* consulted —
they're free-text and would require fragile parsing.

Fails closed: any error returns an empty list (so the pipeline simply
treats the session as if no quizzes had been asked before).
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.agents.question.pipeline import QuizHistoryEntry

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 30


async def load_session_quiz_history(
    session_id: str,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> list[QuizHistoryEntry]:
    """Return prior quiz items for ``session_id`` in chronological order.

    "Chronological" means oldest-first in the returned list, even though
    the underlying table sorts DESC for pagination — the order matters
    for the LLM prompt (which reads top-to-bottom as "this is what we've
    covered so far").

    The boolean ``is_correct`` field on notebook entries defaults to 0
    even when no answer was submitted; we treat an empty ``user_answer``
    as "unanswered" and surface ``is_correct=None`` for it so the explore
    prompt can render "unknown" instead of misleading "incorrect".
    """
    if not session_id or max_entries <= 0:
        return []
    try:
        from deeptutor.services.session.sqlite_store import get_sqlite_session_store

        store = get_sqlite_session_store()
        result = await store.list_notebook_entries(
            session_id=session_id,
            limit=max(1, int(max_entries)),
            offset=0,
        )
    except Exception:
        logger.warning("Failed to load quiz history for session %s", session_id, exc_info=True)
        return []

    items: list[dict[str, Any]] = list(result.get("items") or [])
    # Store returns DESC, but rows with identical ``created_at`` (a single
    # upsert call writes all rows at the same timestamp) come back in
    # insertion order — so a plain reverse() would still flip them. Sort
    # explicitly by (created_at ASC, id ASC) so the prompt reads earliest
    # → latest, deterministically.
    items.sort(key=lambda r: (float(r.get("created_at") or 0.0), int(r.get("id") or 0)))

    entries: list[QuizHistoryEntry] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        if not question:
            continue
        user_answer = str(raw.get("user_answer") or "").strip()
        correct_answer = str(raw.get("correct_answer") or "").strip()
        # The DB column is a 0/1 INTEGER with default 0 — we can't tell
        # "answered wrong" from "not answered yet" purely from is_correct.
        # The user_answer field is authoritative for "did they attempt this".
        if not user_answer:
            is_correct: bool | None = None
        else:
            is_correct = bool(raw.get("is_correct"))
        entries.append(
            QuizHistoryEntry(
                question=question,
                question_type=str(raw.get("question_type") or "").strip(),
                correct_answer=correct_answer,
                user_answer=user_answer,
                is_correct=is_correct,
                turn_id=str(raw.get("turn_id") or "").strip(),
            )
        )
    return entries


__all__ = ["DEFAULT_MAX_ENTRIES", "load_session_quiz_history"]
