"""The data contract for multiple-choice mastery questions.

A choice question crosses four boundaries with different shapes for the same
data: the model registers option *bodies* through ``mastery_quiz``, the learner
answers a *label* (``"C"``) on an interactive ``ask_user`` card, deterministic
grading must compare like with like, and the Question Bank persists the full
option text. This module owns the translation between those shapes so the tool
layer (:mod:`deeptutor.capabilities.mastery.tools`) reads as orchestration:

* :func:`parse_options` — option strings → a ``{label: body}`` map.
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
import re
from typing import Any

logger = logging.getLogger(__name__)

# Matches a labelled option like ``"C: body"`` / ``"C) body"`` / ``"C、body"``,
# capturing the label letter and the body. Used to recover the label a model
# embedded in the option text instead of supplying it positionally.
OPTION_PREFIX_RE = re.compile(r"^\s*([A-Z])\s*[.:：、)）-]\s*(.+)$", re.IGNORECASE)


def parse_options(options: list[str]) -> dict[str, str]:
    """Map option strings to ``{label: body}``.

    ``"C: the answer"`` → ``{"C": "the answer"}``; a bare single character
    ``"C"`` maps to itself (a label-only registration); anything else gets a
    positional label (A, B, C, … then 27, 28, … past Z).
    """
    result: dict[str, str] = {}
    for idx, raw in enumerate(options):
        text = str(raw or "").strip()
        if not text:
            continue
        match = OPTION_PREFIX_RE.match(text)
        if match:
            result[match.group(1).upper()] = match.group(2).strip()
        elif len(text) == 1 and text.isalnum():
            result[text.upper()] = text
        else:
            result[chr(ord("A") + idx) if idx < 26 else str(idx + 1)] = text
    return result


def has_option_bodies(options: dict[str, str]) -> bool:
    """Whether a choice map holds real answer text, not only A/B/C labels."""
    return len(options) >= 2 and all(
        value.strip() and value.strip().upper() != key.upper() for key, value in options.items()
    )


def format_options(options: dict[str, str]) -> list[str]:
    """Render a ``{label: body}`` map back to canonical ``"label: body"`` strings."""
    return [f"{label}: {body}" for label, body in options.items()]


def resolve_answer(expected_answer: str, options: dict[str, str]) -> str:
    """Resolve a model-supplied choice answer to its stable option label.

    Models occasionally send ``"Step 6"`` or the full option text even though
    the interactive card returns ``"C"``. Resolve a unique textual match at
    registration time so deterministic grading compares like with like. Returns
    ``""`` when nothing matches or the match is ambiguous.
    """
    expected = str(expected_answer or "").strip()
    if not expected:
        return ""

    key = expected.upper()
    if key in options:
        return key

    prefix_match = OPTION_PREFIX_RE.match(expected)
    if prefix_match and prefix_match.group(1).upper() in options:
        return prefix_match.group(1).upper()

    needle = expected.casefold()
    exact = [label for label, text in options.items() if text.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    contained = [label for label, text in options.items() if needle in text.casefold()]
    return contained[0] if len(contained) == 1 else ""


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
