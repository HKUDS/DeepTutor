"""Retry helpers for agents that need a JSON object from the LLM.

Thinking models sometimes return ``content: null`` (or empty streamed text)
while emitting reasoning. Structured stages must not treat that as a valid
``{}`` payload — they should nudge and retry a bounded number of times.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from deeptutor.agents._shared.json_output import require_json_object

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_STRUCTURED_ATTEMPTS = 3

_JSON_RETRY_NUDGE = (
    "\n\nIMPORTANT: Your previous reply was empty or not a valid JSON object "
    "(reasoning-only / null content fails this step). "
    "Reply with ONE JSON object only. No markdown fences, no prose outside JSON."
)


async def stream_and_validate_json(
    *,
    stream: Callable[..., AsyncIterator[str]],
    user_prompt: str,
    model_type: type[T],
    stream_kwargs: dict[str, Any] | None = None,
    build_messages: Callable[[str], list[dict[str, Any]]] | None = None,
    is_complete: Callable[[T], bool] | None = None,
    max_attempts: int = DEFAULT_STRUCTURED_ATTEMPTS,
) -> T:
    """Stream an LLM reply, parse a JSON object, and validate into *model_type*.

    On empty content, non-JSON text, validation failure, or an incomplete
    payload (``is_complete``), append a nudge and retry up to *max_attempts*.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    base_kwargs = dict(stream_kwargs or {})
    last_error: Exception | None = None
    prompt = user_prompt

    for attempt in range(1, max_attempts + 1):
        kwargs = dict(base_kwargs)
        kwargs["user_prompt"] = prompt
        if build_messages is not None:
            kwargs["messages"] = build_messages(prompt)

        chunks: list[str] = []
        async for chunk in stream(**kwargs):
            chunks.append(chunk)
        raw = "".join(chunks)

        try:
            payload = require_json_object(raw)
            parsed = model_type.model_validate(payload)
            if is_complete is not None and not is_complete(parsed):
                raise ValueError(f"{model_type.__name__} missing required fields after parse")
            if attempt > 1:
                logger.info(
                    "structured JSON recovered on attempt %s/%s for %s",
                    attempt,
                    max_attempts,
                    model_type.__name__,
                )
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            last_error = exc
            logger.warning(
                "structured JSON attempt %s/%s for %s failed: %s",
                attempt,
                max_attempts,
                model_type.__name__,
                exc,
            )
            prompt = user_prompt + _JSON_RETRY_NUDGE

    assert last_error is not None
    raise ValueError(
        f"LLM returned unusable structured output for {model_type.__name__} "
        f"after {max_attempts} attempt(s)"
    ) from last_error


__all__ = [
    "DEFAULT_STRUCTURED_ATTEMPTS",
    "stream_and_validate_json",
]
