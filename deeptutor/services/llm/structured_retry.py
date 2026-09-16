"""One retry for a structured call a reasoning model failed to answer.

This is the project's single rule for that failure. Any step that asks a
model for a whole structured payload in one shot should route through it
rather than growing its own retry, because every such step has the same
two indistinguishable outcomes and the same escape hatch.

A reasoning model pays for its hidden tokens out of the same ``max_tokens``
budget as its visible answer. When a prompt is large and the requested payload
is a whole JSON object — a book proposal, a spine, a page plan — the thinking
phase can consume the budget before a single character of JSON is emitted. The
provider does not raise: it returns a truncated body, or none at all, and
``parse_json_response`` hands back the caller's fallback. Every Book stage then
degrades silently — most visibly the spine, which collapses to one placeholder
"Overview" chapter (#1316).

The escape hatch is to ask the same model for the same thing with its thinking
turned down, which frees the budget for the answer — at
:data:`~deeptutor.services.llm.reasoning_params.RETRY_REASONING_EFFORT`, which
is where the choice of level and its reason live.

The streaming half of the same rule lives in
:class:`~deeptutor.runtime.agentic.labeled_step.LabeledStepResult`, whose
``reasoning_only`` flag reports the same starvation for a step that emits
labelled text rather than a payload: a round that produced reasoning, no
visible text and no tool calls. Two detectors, one disease — a budget spent
on hidden tokens — and one remedy, which is to ask again with thinking
turned down.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT
from deeptutor.utils.json_parser import parse_json_response


def json_payload_is_usable(payload: Any, expected_key: str | None) -> bool:
    """Whether a parsed payload is worth keeping without a retry."""
    if not isinstance(payload, dict) or not payload:
        return False
    if expected_key is None:
        return True
    return bool(payload.get(expected_key))


async def payload_with_reasoning_retry(
    run: Callable[[str | None], Awaitable[str]],
    *,
    is_usable: Callable[[Any], bool],
    logger_instance: Any = None,
) -> Any:
    """Run ``run`` for a parsed payload, retrying once at low reasoning effort.

    ``run`` receives the ``reasoning_effort`` to use (``None`` on the first
    attempt = whatever the model is configured for) and returns the raw
    response text.

    ``is_usable`` decides what "the model answered" means for this call site,
    and it belongs to the caller: a step expecting an object keyed by
    ``sections`` and a step that also accepts a bare array cannot share one
    definition, and hard-coding either would make the other silently discard a
    good answer. Returns the first usable payload, else the first non-empty
    one, else ``None``.
    """
    first = parse_json_response(await run(None), logger_instance=logger_instance, fallback=None)
    if is_usable(first):
        return first

    retried = parse_json_response(
        await run(RETRY_REASONING_EFFORT),
        logger_instance=logger_instance,
        fallback=None,
    )
    if is_usable(retried):
        return retried

    for candidate in (first, retried):
        if candidate:
            return candidate
    return None


async def json_with_reasoning_retry(
    run: Callable[[str | None], Awaitable[str]],
    *,
    expected_key: str | None = None,
    logger_instance: Any = None,
) -> dict[str, Any]:
    """The object-shaped case of :func:`payload_with_reasoning_retry`.

    Guarantees a ``dict`` — callers index it directly — so a model that
    answered with a bare array is treated as not having answered. Returns
    ``{}`` when neither attempt produced an object, so callers keep their
    existing "empty means fall back" handling.
    """
    payload = await payload_with_reasoning_retry(
        run,
        is_usable=lambda value: json_payload_is_usable(value, expected_key),
        logger_instance=logger_instance,
    )
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "json_payload_is_usable",
    "json_with_reasoning_retry",
    "payload_with_reasoning_retry",
]
