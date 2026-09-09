"""Coercion for provider ``usage`` payloads.

Token counts arrive in three shapes and every reader used to guess for itself:

* a plain dict — DeepTutor's own :class:`~deeptutor.services.llm.types.TutorStreamChunk`
  carries ``usage: dict[str, int]``, and the native adapters build one directly;
* a pydantic model — the OpenAI SDK's ``CompletionUsage``;
* a bare object with attributes — some gateways and the Responses API SDK.

Four call sites each re-derived that guess, so teaching the codebase a new
shape meant finding all four (the bug fixed in #919 was exactly one of them
missing the dict case). This module is the only place the guessing happens.

Key names differ by API dialect — chat completions says ``prompt_tokens`` while
the Responses API says ``input_tokens`` — so :func:`token_counts` takes the
source names and always returns DeepTutor's canonical triple.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CANONICAL_KEYS: tuple[str, str, str] = ("prompt_tokens", "completion_tokens", "total_tokens")


def usage_mapping(payload: Any, *, keys: Sequence[str] = CANONICAL_KEYS) -> dict[str, Any]:
    """Return *payload* as a plain mapping, or ``{}`` when it carries nothing.

    ``keys`` is only consulted for the bare-object case: a mapping and a
    pydantic model already hand over every field they have, while an arbitrary
    object has to be asked for names.
    """
    if payload is None:
        return {}
    if isinstance(payload, Mapping):
        return dict(payload)
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            dumped = dump()
        except Exception:  # a model_dump that needs arguments is not ours to call
            dumped = None
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {key: getattr(payload, key) for key in keys if hasattr(payload, key)}


def token_counts(
    payload: Any,
    *,
    prompt: str = "prompt_tokens",
    completion: str = "completion_tokens",
    total: str = "total_tokens",
) -> dict[str, int]:
    """Canonical ``{prompt,completion,total}_tokens`` triple from any usage shape.

    Returns ``{}`` when the payload reports no tokens at all, so callers can
    keep using truthiness to mean "this frame had no usage report" — a
    zero-filled dict would look like a real report of zero.

    ``total`` falls back to ``prompt + completion``: providers that omit it
    (or send it as 0) still get a usable total.
    """
    frame = usage_mapping(payload, keys=(prompt, completion, total))
    if not frame:
        return {}
    prompt_tokens = _as_int(frame.get(prompt))
    completion_tokens = _as_int(frame.get(completion))
    total_tokens = _as_int(frame.get(total)) or prompt_tokens + completion_tokens
    if not (prompt_tokens or completion_tokens or total_tokens):
        return {}
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def usage_breakdown(
    payload: Any,
    *,
    prompt: str = "prompt_tokens",
    completion: str = "completion_tokens",
    total: str = "total_tokens",
) -> dict[str, int]:
    """Return canonical token counts plus an optional reasoning-token count.

    OpenAI-compatible chat completions put the reasoning count under
    ``completion_tokens_details`` while Responses API payloads use
    ``output_tokens_details``.  Keeping the detail in this small normalized
    frame lets diagnostics distinguish a response that spent its budget on
    reasoning from one that generated visible output, without changing the
    accounting contract of :func:`token_counts`.
    """
    counts = token_counts(payload, prompt=prompt, completion=completion, total=total)
    if not counts:
        return {}

    frame = usage_mapping(
        payload,
        keys=(
            prompt,
            completion,
            total,
            "reasoning_tokens",
            "completion_tokens_details",
            "output_tokens_details",
        ),
    )
    reasoning = frame.get("reasoning_tokens")
    if reasoning is None:
        for key in ("completion_tokens_details", "output_tokens_details"):
            details = usage_mapping(frame.get(key), keys=("reasoning_tokens",))
            if details.get("reasoning_tokens") is not None:
                reasoning = details.get("reasoning_tokens")
                break
    reasoning_tokens = _as_int(reasoning)
    if reasoning is not None:
        counts["reasoning_tokens"] = reasoning_tokens
    return counts


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["CANONICAL_KEYS", "token_counts", "usage_breakdown", "usage_mapping"]
