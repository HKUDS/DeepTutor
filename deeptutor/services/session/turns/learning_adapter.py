"""Generated behavior slice of the unified turn runtime."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.learning.storage import MasteryPathLease
    from deeptutor.services.session.protocol import SessionStoreProtocol

    from .._turn_runtime_shared import _TurnExecution


class LearningTurnAdapter:
    if TYPE_CHECKING:
        store: SessionStoreProtocol
        _lock: asyncio.Lock
        _executions: dict[str, _TurnExecution]

        async def cancel_turn(self, turn_id: str) -> bool: ...

    async def _is_awaiting_user_reply(self, turn_id: str) -> bool:
        async with self._lock:
            execution = self._executions.get(turn_id)
            return execution is not None and execution.awaiting_user_reply

    async def _release_superseded_lease(self, path_id: str, lease: MasteryPathLease) -> None:
        """Free ``lease`` when its turn can no longer be working on the path.

        Two cases release it. A turn that is no longer ``running`` (finished,
        or orphaned by a restart) is simply gone. A turn parked inside
        ``ask_user`` is alive but idle — it holds the lease for as long as the
        learner takes to answer, which may be forever. Since the posed question
        is persisted on the path itself, the arriving turn resumes exactly
        where the parked one stopped, so handing the path over loses nothing;
        the parked turn is cancelled rather than left to mutate a path it no
        longer owns. Only a turn that is actively generating keeps the lease.
        """
        from deeptutor.learning.storage import LearningStore

        # Liveness is coordinator-owned. A request handled by another worker
        # must never infer that a persisted running turn is orphaned merely
        # because no Python task exists in this process.
        leased_turn = await self.store.get_turn(lease.turn_id)
        alive = leased_turn is not None and str(leased_turn.get("status") or "") == "running"
        if alive:
            if not await self._is_awaiting_user_reply(lease.turn_id):
                # Genuinely busy — leave the lease, and let the store report
                # the conflict to the caller.
                return
            await self.cancel_turn(lease.turn_id)
        # Scoped to the superseded turn id, so a lease already re-taken by
        # someone else survives.
        await asyncio.to_thread(
            LearningStore().release_path_lease,
            path_id,
            turn_id=lease.turn_id,
        )

    async def _acquire_mastery_path_lease(
        self,
        *,
        path_id: str,
        session_id: str,
        turn_id: str,
        owns_path: bool,
    ) -> None:
        """Bind a session to its path and take over from any superseded turn."""
        from deeptutor.learning.storage import LearningStore, PathLeaseConflictError

        learning_store = LearningStore()
        await asyncio.to_thread(
            learning_store.bind_session,
            path_id,
            session_id,
            owns_path=owns_path,
        )
        lease = await asyncio.to_thread(learning_store.get_path_lease, path_id)
        if lease is not None and lease.turn_id != turn_id and lease.session_id != "__path_api__":
            await self._release_superseded_lease(path_id, lease)
        try:
            await asyncio.to_thread(
                learning_store.acquire_path_lease,
                path_id,
                session_id,
                turn_id,
            )
        except PathLeaseConflictError as exc:
            raise RuntimeError(
                "mastery_path_busy: "
                f"path {path_id!r} is already active in session {exc.lease.session_id!r}"
            ) from exc

    @staticmethod
    async def _validate_mastery_session_topic(
        *,
        session_id: str,
        requested_path_id: str,
        remembered_path_id: str,
    ) -> None:
        """Reject a topic URL paired with an unrelated existing chat session.

        A new session has no associations and may start any topic. Historical
        sessions may resume any path they were durably bound to (including a
        legitimate in-chat path switch), while the remembered preference
        covers sessions created before explicit bindings were introduced.
        """

        from deeptutor.learning.storage import LearningStore

        learning_store = LearningStore()
        associations = await asyncio.to_thread(
            learning_store.list_paths_for_session,
            session_id,
        )
        known_path_ids = {str(item.get("path_id") or "") for item in associations}
        remembered = str(remembered_path_id or "").strip()
        if (
            (known_path_ids or remembered)
            and requested_path_id not in known_path_ids
            and (not remembered or requested_path_id != remembered)
        ):
            raise RuntimeError(
                "mastery_session_topic_mismatch: "
                f"session {session_id!r} does not belong to path {requested_path_id!r}"
            )
