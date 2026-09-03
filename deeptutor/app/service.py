"""One application service used by WebSocket, CLI, and Python SDK adapters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import time
from typing import Any

from deeptutor.runtime.coordination import RuntimeCoordinator
from deeptutor.services.session.protocol import SessionStoreProtocol
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

from .contracts import TurnRequest


class TurnApplicationService:
    def __init__(
        self,
        store_provider: Any,
        runtime_registry: Any,
        coordinator: RuntimeCoordinator,
    ) -> None:
        self.store_provider = store_provider
        self.runtime_registry = runtime_registry
        self.coordinator = coordinator

    def _resolve(self) -> tuple[SessionStoreProtocol, TurnRuntimeManager]:
        store = self.store_provider.get()
        return store, self.runtime_registry.get(store)

    async def start_turn(
        self, payload: TurnRequest | dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        request = (
            payload if isinstance(payload, TurnRequest) else TurnRequest.model_validate(payload)
        )
        payload = request.to_payload()
        store, runtime = self._resolve()
        session, turn = await runtime.start_turn(payload)
        await store.update_session_preferences(
            session["id"],
            {
                "language": str(payload.get("language") or "en"),
                "notebook_references": list(payload.get("notebook_references") or []),
                "history_references": list(payload.get("history_references") or []),
                "partner_group_references": list(payload.get("partner_group_references") or []),
            },
        )
        return session, turn

    async def regenerate_last_turn(
        self,
        session_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        _store, runtime = self._resolve()
        return await runtime.regenerate_last_turn(session_id, overrides=overrides)

    # How long to keep reading after DONE before closing the stream.
    #
    # DONE is not a turn's last event. The runtime deliberately publishes
    # post-turn metadata after it — notably the LLM-written session title,
    # which ``SessionTitleService`` emits once the answer is saved so the
    # composer and the duration clock stop immediately rather than waiting on
    # the title model. Both loops below used to ``return`` the instant they
    # saw DONE, so every post-DONE event was dropped: the title landed in
    # ``turn_events`` and in the database while no subscriber ever received
    # it, which is why a finished conversation could sit on "New conversation"
    # indefinitely. The frontend even holds its socket open for 15s waiting
    # for that frame; it never had a chance to arrive.
    #
    # End of stream is the turn's lease disappearing, not a timeout.
    #
    # The turn task releases its lease in its own ``finally``, which runs after
    # every post-turn event has been published. So "lease gone" is an honest
    # end-of-stream signal and needs no guessing about how long a title model
    # might take — an idle timeout would have to exceed that model's own 20s
    # ceiling to be safe, and would then hold every finished stream open for
    # 20s whenever no title was written at all.
    #
    # The cap below exists only for a leaked lease; it is not the normal path.
    _POST_DONE_MAX_SECONDS = 30.0

    @staticmethod
    def _done_has_tail(event: dict[str, Any]) -> bool:
        """Can more events follow this DONE?"""
        status = str((event.get("metadata") or {}).get("status") or "completed")
        return status == "completed"

    async def subscribe_turn(
        self,
        turn_id: str,
        after_seq: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        store, _runtime = self._resolve()
        last_seq = max(0, int(after_seq))
        done = False
        tail_possible = False

        # Durable replay covers a process/Redis restart. Shared-stream replay
        # then fills the live tail owned by any worker.
        for event in await store.get_events(turn_id, last_seq):
            seq = int(event.get("seq") or 0)
            if seq <= last_seq:
                continue
            last_seq = seq
            if str(event.get("type") or "") == "done":
                done = True
                tail_possible = self._done_has_tail(event)
            yield event
        if done:
            # The turn had already finished before this subscription opened, so
            # the durable replay above carried its post-DONE events too. Only
            # bail out once the terminal row confirms that; a turn still marked
            # running with a DONE in its journal is mid-teardown and its title
            # may not be written yet.
            turn = await store.get_turn(turn_id)
            if not tail_possible or turn is None or str(turn.get("status") or "") != "running":
                return

        first_done_at: float | None = time.monotonic() if done else None
        while True:
            emitted = False
            for event in await self.coordinator.read_events(turn_id, last_seq):
                seq = int(event.get("seq") or 0)
                if seq <= last_seq:
                    continue
                emitted = True
                last_seq = seq
                if str(event.get("type") or "") == "done":
                    done = True
                    tail_possible = self._done_has_tail(event)
                    if first_done_at is None:
                        first_done_at = time.monotonic()
                yield event
            if done and not tail_possible:
                return
            if done:
                now = time.monotonic()
                if first_done_at is None:
                    first_done_at = now
                # The turn task publishes its post-turn events before releasing
                # the lease, so once the lease is gone the tail is complete.
                if await self.coordinator.get_lease(turn_id) is None:
                    return
                if now - first_done_at >= self._POST_DONE_MAX_SECONDS:
                    return
                if not emitted:
                    await asyncio.sleep(0.1)
                continue
            turn = await store.get_turn(turn_id)
            if turn is None:
                return
            status = str(turn.get("status") or "")
            if status in {"completed", "failed", "cancelled"}:
                # A terminal row without DONE can only be legacy data. Keep the
                # compatibility envelope stable while all new paths journal
                # DONE before the terminal CAS.
                metadata = {
                    "status": status,
                    "synthesized": True,
                    "error_code": str(turn.get("failure_code") or ""),
                    "retryable": bool(turn.get("retryable")),
                }
                yield {
                    "type": "done",
                    "source": "turn_application",
                    "stage": "",
                    "content": "",
                    "metadata": metadata,
                    "session_id": turn.get("session_id", ""),
                    "turn_id": turn_id,
                    "seq": last_seq + 1,
                    "timestamp": time.time(),
                }
                return
            if not emitted:
                await asyncio.sleep(0.1)

    async def subscribe_session(
        self,
        session_id: str,
        after_seq: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        active = await self.check_active_turn(session_id)
        turn_id = str((active or {}).get("turn_id") or "")
        if not turn_id:
            return
        async for event in self.subscribe_turn(turn_id, after_seq):
            yield event

    async def check_active_turn(self, session_id: str) -> dict[str, Any] | None:
        store, _runtime = self._resolve()
        turn = await store.get_active_turn(session_id)
        if turn is None:
            return None
        turn_id = str(turn.get("id") or turn.get("turn_id") or "")
        lease = await self.coordinator.get_lease(turn_id)
        return {
            "turn_id": turn_id,
            "status": str(turn.get("status") or "running") if lease else "recovering",
            "owner_id": lease.owner_id if lease else str(turn.get("owner_id") or ""),
        }

    async def cancel_turn(self, turn_id: str, *, command_id: str | None = None) -> bool:
        store, _runtime = self._resolve()
        turn = await store.get_turn(turn_id)
        if turn is None or turn.get("status") not in {
            "queued",
            "running",
            "waiting_input",
        }:
            return False
        if await self.coordinator.get_lease(turn_id) is None:
            return False
        await self.coordinator.submit_command(turn_id, "cancel", {}, command_id=command_id)
        # A duplicate command ID means the mutation was already accepted. The
        # WebSocket adapter must acknowledge that retry as success so a client
        # that lost the first ACK can retire its durable outbox entry.
        return True

    async def submit_user_reply(
        self,
        turn_id: str,
        text: str | None = None,
        *,
        answers: list[dict[str, Any]] | None = None,
        command_id: str | None = None,
    ) -> bool:
        if await self.coordinator.get_lease(turn_id) is None:
            return False
        await self.coordinator.submit_command(
            turn_id,
            "submit_user_reply",
            {"text": text or "", "answers": answers},
            command_id=command_id,
        )
        return True

    async def submit_user_input(
        self,
        turn_id: str,
        content: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        if await self.coordinator.get_lease(turn_id) is None:
            return False
        await self.coordinator.submit_command(
            turn_id,
            "user_input",
            {"content": content},
            command_id=command_id,
        )
        return True

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        store, _runtime = self._resolve()
        return await store.list_sessions(limit=limit, offset=offset)

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        store, _runtime = self._resolve()
        return await store.get_session_with_messages(session_id)

    async def rename_session(self, session_id: str, title: str) -> bool:
        store, _runtime = self._resolve()
        return await store.update_session_title(session_id, title)

    async def delete_session(self, session_id: str) -> bool:
        store, _runtime = self._resolve()
        active = await store.list_active_turns(session_id)
        for turn in active:
            await self.cancel_turn(str(turn["id"]))
        if active:
            return False
        return await store.delete_session(session_id)


__all__ = ["TurnApplicationService"]
