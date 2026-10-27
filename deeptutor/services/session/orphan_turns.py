"""Terminal writes for live turns whose worker no longer exists.

A turn row outlives the process that was executing it. After a restart the row
still reads ``running`` while nothing is generating, so every later request that
asks "is this turn alive?" from the durable row alone answers yes forever. The
two independent owners of that question — the application service clearing a
session it is about to reuse, and the mastery path lease it is about to
supersede — must settle the row identically, or one of them keeps believing a
dead turn is running and the learner stays locked out.

The only safe liveness signal is the coordinator lease, never the row's status
or its age: a turn parked on an ``ask_user`` card emits no events, so
``updated_at`` stops advancing while a person thinks, and a sweep on age would
cancel that reader mid-answer.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


#: The turn row stopped being owned by a worker that could have written it.
#: Distinct from a model or tool failure: nothing went wrong in the turn, the
#: process holding it went away.
ORPHANED_TURN_ERROR = "The worker executing this turn was lost; regenerate to retry"

#: Same loss, seen from the composer: the learner's own message went unanswered
#: and the thing to do is send it again rather than regenerate a missing reply.
ORPHANED_SUBMISSION_ERROR = (
    "The worker executing this turn was lost; resend your answer as a new message"
)

_LIVE_STATUSES = frozenset({"queued", "running", "waiting_input"})
_FAILURE_CODE = "worker_lost"


class _ReapableStore(Protocol):
    async def get_turn(self, turn_id: str) -> dict[str, Any] | None: ...
    async def transition_turn(
        self,
        turn_id: str,
        status: str,
        *,
        expected_status: str | None = None,
        fencing_token: int | None = None,
        error: str = "",
        failure_code: str = "",
        retryable: bool = False,
    ) -> bool: ...
    async def append_events(
        self,
        turn_id: str,
        events: list[dict[str, Any]],
        *,
        fencing_token: int | None = None,
    ) -> list[dict[str, Any]]: ...


class _EventSink(Protocol):
    async def publish_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]: ...


def _worker_lost_events(turn: dict[str, Any], error: str) -> list[dict[str, Any]]:
    """The error+done pair a terminal stream needs, in protocol order."""
    metadata = {
        "turn_terminal": True,
        "status": "failed",
        "error_code": _FAILURE_CODE,
        "retryable": True,
    }
    return [
        {
            "type": "error",
            "source": "turn_recovery",
            "stage": "recovery",
            "content": error,
            "metadata": metadata,
            "session_id": turn.get("session_id", ""),
        },
        {
            "type": "done",
            "source": "turn_recovery",
            "stage": "recovery",
            "content": "",
            "metadata": {
                "status": "failed",
                "error_code": _FAILURE_CODE,
                "retryable": True,
            },
            "session_id": turn.get("session_id", ""),
        },
    ]


async def reap_orphaned_turn(
    store: _ReapableStore,
    coordinator: _EventSink | None,
    turn_id: str,
    *,
    error: str = ORPHANED_TURN_ERROR,
) -> bool:
    """Fail a live turn nothing is executing; return whether it was reaped.

    Idempotent under races: the status transition is a compare-and-set on the
    current status and fencing token, so a recovery pass or an executor write
    that wins first makes this a no-op that reports ``False``.
    """
    try:
        turn = await store.get_turn(turn_id)
    except Exception:
        return False
    if turn is None or str(turn.get("status") or "") not in _LIVE_STATUSES:
        return False

    events = _worker_lost_events(turn, error)
    try:
        transitioned = await store.transition_turn(
            turn_id,
            "failed",
            expected_status=str(turn["status"]),
            fencing_token=int(turn.get("fencing_token") or 0),
            error=error,
            failure_code=_FAILURE_CODE,
            retryable=True,
        )
        if not transitioned:
            return False
        await store.append_events(
            turn_id,
            events,
            fencing_token=int(turn.get("fencing_token") or 0),
        )
    except Exception:
        logger.warning("Could not reap orphaned turn %s", turn_id, exc_info=True)
        return False

    if coordinator is not None:
        for event in events:
            with contextlib.suppress(Exception):
                await coordinator.publish_event(turn_id, event)
    return True


__all__ = [
    "ORPHANED_SUBMISSION_ERROR",
    "ORPHANED_TURN_ERROR",
    "reap_orphaned_turn",
]
