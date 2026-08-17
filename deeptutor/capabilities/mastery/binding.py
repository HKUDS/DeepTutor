"""Moving a live turn from one mastery path to another.

A conversation and a path have independent lifetimes: a path outlives any one
chat, and a chat may work several paths in sequence. The binding between them
is therefore not a property of the session — it is state that has to be changed
in three places at once, and this module is the only thing allowed to change
it:

* **the lease** — exclusion is per path, so leaving one and entering another is
  a handoff, not two independent operations. Released by *turn*, since the path
  a turn began on is not the path it may end on.
* **the session preference** — what the next turn resumes on.
* **the live turn** — what the rest of *this* turn's tool calls operate on,
  applied through a caller-supplied binder so nothing here needs to know what a
  turn context is.

Order matters: release before acquire (one lease row per turn), and persist
only after the acquire succeeds, so a rejected handoff leaves the learner
exactly where they were.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import logging

from deeptutor.learning.identity import sanitize_mastery_path_id

logger = logging.getLogger(__name__)

# Rebinds the running turn to a path id. Injected by the loop capability, which
# is the only layer that holds the turn context.
PathBinder = Callable[[str], None]


class PathBindingError(RuntimeError):
    """The requested path cannot be entered."""


async def rebind_active_path(
    *,
    path_id: str,
    session_id: str,
    turn_id: str,
    bind_turn: PathBinder | None,
    require_existing: bool = True,
) -> str:
    """Move this turn (and the conversation) onto ``path_id``.

    Returns the resolved path id. Raises :class:`PathBindingError` when the
    target does not exist or is busy in another conversation.
    """
    from deeptutor.learning.storage import (
        LearningStore,
        PathLeaseConflictError,
    )

    target = sanitize_mastery_path_id(path_id)
    store = LearningStore()
    if require_existing and not await asyncio.to_thread(store.exists, target):
        raise PathBindingError(
            f"No mastery path {path_id!r} exists. Call mastery_paths for the "
            "ids you can switch to, or mastery_build to create one here."
        )

    # One lease row per turn: the old one has to go before the new one can be
    # taken, and both are scoped to this turn so a concurrent conversation on
    # either path is never disturbed.
    released = await asyncio.to_thread(store.release_leases_for_turn, turn_id)
    try:
        await asyncio.to_thread(store.acquire_path_lease, target, session_id, turn_id)
    except PathLeaseConflictError as exc:
        # Put the learner back where they were rather than stranding the turn
        # with no lease at all.
        if released and released != target:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(store.acquire_path_lease, released, session_id, turn_id)
        raise PathBindingError(
            f"Mastery path {target!r} is being tutored in another conversation "
            f"right now (session {exc.lease.session_id!r}). Try again once that "
            "turn finishes."
        ) from exc

    _apply(bind_turn, target)
    await _remember_on_session(session_id, target)
    return target


async def leave_active_path(
    *,
    session_id: str,
    turn_id: str,
    bind_turn: PathBinder | None,
) -> str:
    """Detach the conversation from any named path.

    The conversation falls back to the scratch path it owns itself — the same
    binding a mastery chat that was never pointed at a path would get — so the
    learner can start something new here without disturbing the course they
    stepped away from.
    """
    from deeptutor.learning.storage import LearningStore

    scratch = sanitize_mastery_path_id(session_id or "default")
    resolved = await rebind_active_path(
        path_id=scratch,
        session_id=session_id,
        turn_id=turn_id,
        bind_turn=bind_turn,
        require_existing=False,
    )
    if session_id:
        # Mark the conversation as the scratch path's owner, the same way an
        # unbound mastery turn resolves it, so deleting the conversation takes
        # the scratch path with it instead of leaving an empty orphan behind.
        # Ownership is sticky in the store, so this can only ever add it.
        await asyncio.to_thread(LearningStore().bind_session, resolved, session_id, owns_path=True)
    # Clear the stored association so the next turn resolves the fallback for
    # itself rather than being pinned to a scratch id that may be renamed.
    await _remember_on_session(session_id, "")
    return resolved


def _apply(bind_turn: PathBinder | None, path_id: str) -> None:
    if bind_turn is not None:
        bind_turn(path_id)


async def _remember_on_session(session_id: str, path_id: str) -> None:
    """Persist the association so the next turn resumes on the same path.

    Best-effort: the handoff itself has already happened, and a conversation
    that forgets its path merely falls back to its own scratch path next turn.
    """
    if not session_id:
        return
    try:
        from deeptutor.services.session import get_session_store

        await get_session_store().update_session_preferences(
            session_id, {"mastery_path_id": path_id}
        )
    except Exception:
        logger.warning(
            "Failed to persist mastery path %r on session %s", path_id, session_id, exc_info=True
        )


__all__ = ["PathBindingError", "leave_active_path", "rebind_active_path"]
