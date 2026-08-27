"""The data contract for multiple-choice mastery questions.

A choice question crosses four boundaries with different shapes for the same
data: the model registers option *bodies* through ``mastery_quiz``, the learner
answers a *label* (``"C"``) on an interactive ``ask_user`` card, deterministic
grading must compare like with like, and the Question Bank persists the full
option text. This module owns the translation between those shapes so the tool
layer (:mod:`deeptutor.capabilities.mastery.tools`) reads as orchestration:

* :func:`parse_options` — option strings → a ``{label: body}`` map.
* :func:`option_label_intent` / :func:`canonical_labels` — were the options
  meant to be labelled A/B/C, and do those labels form a well-formed set?
* :func:`has_option_bodies` — did the model send real bodies, not bare labels?
* :func:`format_options` — a ``{label: body}`` map → canonical option strings.
* :func:`resolve_answer` — a model-supplied answer → its stable option label.
* :func:`recover_options_from_turn` — bodies recovered from a legacy turn's
  ``ask_user`` event, for paths registered before the contract was enforced.

Everything here is pure except :func:`recover_options_from_turn`, which takes a
session store by dependency injection rather than importing one, keeping this
module free of infrastructure wiring.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.learning.pending import (
    canonical_labels,
    format_options,
    has_option_bodies,
    is_readable_choice_answer,
    option_label_intent,
    parse_options,
    resolve_answer,
    resolve_choice_submission,
)

logger = logging.getLogger(__name__)


def _normalized_prompt(value: str) -> str:
    """Alphanumeric-only, case-folded form for tolerant prompt matching."""
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


async def recover_options_from_turn(store: Any, turn_id: str, question: str) -> dict[str, str]:
    """Recover choice bodies from the most recent matching ``ask_user`` card.

    A compatibility fallback for questions registered by older versions, where
    ``mastery_quiz`` persisted only ``["A", "B", ...]`` even though the full
    descriptions were present in the turn's ``ask_user`` event. ``store`` is
    injected so this stays decoupled from the session layer.
    """
    if not turn_id or not hasattr(store, "get_turn_events"):
        return {}
    try:
        events = await store.get_turn_events(turn_id)
    except Exception:
        logger.warning("Failed to load turn events for mastery option recovery", exc_info=True)
        return {}

    target = _normalized_prompt(question)
    for event in reversed(events):
        if event.get("type") != "tool_call":
            continue
        metadata = event.get("metadata") or {}
        if metadata.get("tool_name") != "ask_user":
            continue
        for item in reversed((metadata.get("args") or {}).get("questions") or []):
            if not isinstance(item, dict):
                continue
            recovered = {
                str(option.get("label") or "").strip().upper(): str(
                    option.get("description") or ""
                ).strip()
                for option in (item.get("options") or [])
                if isinstance(option, dict)
                and str(option.get("label") or "").strip()
                and str(option.get("description") or "").strip()
            }
            if not has_option_bodies(recovered):
                continue
            prompt = _normalized_prompt(str(item.get("prompt") or ""))
            if prompt == target or prompt.startswith(target) or target.startswith(prompt):
                return recovered
    return {}


__all__ = [
    "canonical_labels",
    "format_options",
    "has_option_bodies",
    "is_readable_choice_answer",
    "option_label_intent",
    "parse_options",
    "recover_options_from_turn",
    "resolve_answer",
    "resolve_choice_submission",
]
