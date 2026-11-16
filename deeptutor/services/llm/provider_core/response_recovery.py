"""Bound a single live Responses operation; never create or replay tool writes.

Recovery state is private to the active provider call. We do not change response
retention, persist credentials, reopen jobs after restart, or claim cancellation
of a remote operation. Unsupported/uncertain outcomes stop at the turn owner.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from deeptutor.services.llm.exceptions import LLMOperationPaused

PROGRESS_DEADLINE_S = 300.0
RECOVERY_ALLOWANCE_S = 30.0
LOOKUP_TIMEOUT_S = 8.0
CLOSE_TIMEOUT_S = 2.0


async def bounded(awaitable, seconds):
    """Detach a non-cooperative transport after the local deadline."""
    task = asyncio.ensure_future(awaitable)
    task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0, seconds))
        if not done:
            raise TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()


def _field(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


async def guarded_responses(stream, *, progress, retrieve=None, owner=lambda: None, idle_s=90.0):
    binding = owner()
    response_id = None
    sequence = -1
    states = set()
    completed_items = set()
    iterator = stream.__aiter__()
    terminal = False

    async def recover():
        if not response_id or retrieve is None:
            raise LLMOperationPaused("same-operation retrieval is unavailable")
        until = time.monotonic() + RECOVERY_ALLOWANCE_S
        while time.monotonic() < until:
            if owner() != binding:
                raise LLMOperationPaused("operation ownership or provider configuration changed")
            try:
                result = await bounded(
                    retrieve(response_id), min(LOOKUP_TIMEOUT_S, until - time.monotonic())
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                raise LLMOperationPaused("the original response could not be retrieved") from None
            if owner() != binding or _field(result, "id") != response_id:
                raise LLMOperationPaused("the retrieved response identity could not be verified")
            status = _field(result, "status")
            if status == "completed":
                return SimpleNamespace(type="response.completed", response=result, recovered=True)
            if status not in {"queued", "in_progress"}:
                raise LLMOperationPaused(
                    "the original response is failed, cancelled or unavailable"
                )
            await asyncio.sleep(min(1.0, max(0, until - time.monotonic())))
        raise LLMOperationPaused("the original response is still pending")

    while not terminal:
        remaining = PROGRESS_DEADLINE_S - (time.monotonic() - progress._last_output)
        try:
            if remaining <= 0:
                raise TimeoutError
            event = await bounded(iterator.__anext__(), min(idle_s, remaining))
        except (TimeoutError, StopAsyncIteration):
            yield await recover()
            return
        if owner() != binding:
            raise LLMOperationPaused("operation ownership or provider configuration changed")
        number = _field(event, "sequence_number")
        if isinstance(number, int) and not isinstance(number, bool):
            if number <= sequence:
                continue
            sequence = number
        kind = _field(event, "type")
        response = _field(event, "response")
        incoming_id = _field(response, "id")
        if incoming_id:
            if response_id and response_id != incoming_id:
                raise LLMOperationPaused("the stream changed response identity")
            response_id = incoming_id
        next_state = _field(response, "status")
        if (
            next_state
            in {"queued", "in_progress", "completed", "incomplete", "failed", "cancelled"}
            and next_state not in states
        ):
            states.add(next_state)
            progress.note_output()
        if kind in {"response.output_item.added", "response.output_item.done"}:
            identity = (kind, _field(_field(event, "item"), "id"))
            if identity[1]:
                if identity in completed_items:
                    continue
                if len(completed_items) >= 10000:
                    raise LLMOperationPaused("the response item limit was reached")
                completed_items.add(identity)
                progress.note_output()
        progress.note_event(kind)
        progress.report_if_silent(90.0)
        terminal = kind in {"response.completed", "response.incomplete", "response.failed", "error"}
        yield event
