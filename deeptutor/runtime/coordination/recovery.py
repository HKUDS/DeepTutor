"""Leader-only recovery of turns whose owner lease has been lost."""

from __future__ import annotations

import logging

from deeptutor.services.session.protocol import TurnRepository

from .protocol import RuntimeCoordinator
from .types import TurnFailureCode, TurnStatus

logger = logging.getLogger(__name__)


class TurnRecoveryService:
    def __init__(
        self,
        coordinator: RuntimeCoordinator,
        repository: TurnRepository,
    ) -> None:
        self.coordinator = coordinator
        self.repository = repository
        self.backlog = 0

    async def recover_once(self) -> int:
        turn_ids = await self.coordinator.list_expired_turn_ids()
        if self.coordinator.mode == "memory":
            # A process restart loses the in-memory lease index entirely. The
            # durable active rows are then the only way to discover old turns.
            # Admission acquires its lease before inserting the row; the lease
            # check in _recover_turn protects both new and parked live turns.
            persisted = await self.repository.list_nonterminal_turns()
            candidates = set(turn_ids)
            for turn in persisted:
                turn_id = str(turn["id"])
                if await self.coordinator.get_lease(turn_id) is None:
                    candidates.add(turn_id)
            turn_ids = sorted(candidates)
        self.backlog = len(turn_ids)
        recovered = 0
        for turn_id in turn_ids:
            try:
                outcome = await self._recover_turn(turn_id)
                # An expired id can belong to a different user repository.
                # Do not globally acknowledge it until the leader finds the
                # repository that owns the turn.
                if outcome is None:
                    continue
                if outcome:
                    recovered += 1
                await self.coordinator.acknowledge_expired_turn(turn_id)
            except Exception:
                logger.exception("Failed to recover expired turn %s", turn_id)
        self.backlog = max(0, self.backlog - recovered)
        return recovered

    async def _recover_turn(self, turn_id: str) -> bool | None:
        turn = await self.repository.get_turn(turn_id)
        if turn is None:
            return None
        if turn.get("status") not in {
            TurnStatus.QUEUED.value,
            TurnStatus.RUNNING.value,
            TurnStatus.WAITING_INPUT.value,
        }:
            return False
        # Recheck at recovery time, not just when collecting expired IDs.
        # None also prevents acknowledging a candidate whose lease is live.
        if await self.coordinator.get_lease(turn_id) is not None:
            return None
        token = int(turn.get("fencing_token") or 0)
        # Preserve any events still available from an expired worker before
        # allocating terminal sequence numbers from the durable journal.
        pending = await self.coordinator.read_events(turn_id)
        if pending:
            await self.repository.append_events(turn_id, pending, fencing_token=token)
        transitioned = await self.repository.transition_turn(
            turn_id,
            TurnStatus.FAILED.value,
            expected_status=str(turn["status"]),
            fencing_token=token,
            error="The worker executing this turn was lost; regenerate to retry",
            failure_code=TurnFailureCode.WORKER_LOST.value,
            retryable=True,
        )
        if not transitioned:
            return False
        # Persist first: a fresh coordinator starts at seq=1, which would
        # collide with pre-crash events and be ignored by resumed clients.
        events = await self.repository.append_events(
            turn_id,
            [
                {
                    "type": "error",
                    "source": "turn_recovery",
                    "stage": "recovery",
                    "content": "The worker executing this turn was lost; regenerate to retry",
                    "metadata": {
                        "turn_terminal": True,
                        "status": TurnStatus.FAILED.value,
                        "error_code": TurnFailureCode.WORKER_LOST.value,
                        "retryable": True,
                    },
                    "session_id": turn.get("session_id", ""),
                },
                {
                    "type": "done",
                    "source": "turn_recovery",
                    "stage": "recovery",
                    "content": "",
                    "metadata": {
                        "status": TurnStatus.FAILED.value,
                        "error_code": TurnFailureCode.WORKER_LOST.value,
                        "retryable": True,
                    },
                    "session_id": turn.get("session_id", ""),
                },
            ],
            fencing_token=token,
        )
        for event in events:
            await self.coordinator.publish_event(turn_id, event)
        return True


__all__ = ["TurnRecoveryService"]
