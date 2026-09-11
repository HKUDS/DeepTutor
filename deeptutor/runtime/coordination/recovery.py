"""Leader-only recovery of turns whose owner lease has expired."""

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
        await self.coordinator.publish_event(
            turn_id,
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
        )
        await self.coordinator.publish_event(
            turn_id,
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
        )
        events = await self.coordinator.read_events(turn_id)
        if events:
            await self.repository.append_events(
                turn_id,
                events,
                fencing_token=int(turn.get("fencing_token") or 0),
            )
        return await self.repository.transition_turn(
            turn_id,
            TurnStatus.FAILED.value,
            expected_status=str(turn["status"]),
            fencing_token=int(turn.get("fencing_token") or 0),
            error="The worker executing this turn was lost; regenerate to retry",
            failure_code=TurnFailureCode.WORKER_LOST.value,
            retryable=True,
        )


__all__ = ["TurnRecoveryService"]
