"""One retry for a structured call a reasoning model failed to answer.

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

This is the shared half of what ``blocks/_llm_writer.llm_json`` already did for
block generators; the pipeline agents (ideation, source explorer, spine
synthesiser, page planner) each parsed their own response and had no retry at
all.
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


async def json_with_reasoning_retry(
    run: Callable[[str | None], Awaitable[str]],
    *,
    expected_key: str | None = None,
    logger_instance: Any = None,
) -> dict[str, Any]:
    """Run ``run`` for a JSON object, retrying once at low reasoning effort.

    ``run`` receives the ``reasoning_effort`` to use (``None`` on the first
    attempt = whatever the model is configured for) and returns the raw
    response text. Returns ``{}`` when neither attempt produced an object, so
    callers keep their existing "empty means fall back" handling.
    """
    payload = parse_json_response(await run(None), logger_instance=logger_instance, fallback={})
    if json_payload_is_usable(payload, expected_key):
        return payload

    retried = parse_json_response(
        await run(RETRY_REASONING_EFFORT),
        logger_instance=logger_instance,
        fallback={},
    )
    if json_payload_is_usable(retried, expected_key):
        return retried

    for candidate in (payload, retried):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


__all__ = [
    "json_payload_is_usable",
    "json_with_reasoning_retry",
]
