"""Workspace snapshot subsystem for L1 memory.

Public API:

- :func:`read_snapshot` — current entities for a surface (no I/O on
  ``state.json`` / ``changes.jsonl``).
- :func:`refresh_snapshot` — re-read workspace, diff against last
  persisted state, append changes, persist new state. Returns the
  computed change list. Idempotent: a no-change refresh writes nothing
  to the changes log.
- :func:`read_changes` — paginated history of past refreshes for one
  surface (git-log-style display source).
- :func:`current_state` — the persisted ``state.json`` for a surface
  (consolidator uses ``last_refresh`` to gate L2 updates).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from deeptutor.services.memory.paths import Surface
from deeptutor.services.memory.snapshot import adapters, store
from deeptutor.services.memory.snapshot.diff import diff_snapshots
from deeptutor.services.memory.snapshot.entity import ChangeEntry, Entity


def read_snapshot(surface: Surface) -> list[Entity]:
    return adapters.read_entities(surface)


def pending_changes(surface: Surface, entities: list[Entity] | None = None) -> list[ChangeEntry]:
    """Compute the diff between current workspace and the last persisted state.

    Pure / read-only: never writes to ``state.json`` or ``changes.jsonl``.
    Used by the L1 view to show "what would a refresh capture right now".
    """
    if entities is None:
        entities = adapters.read_entities(surface)
    curr_fp = {e.id: e.fingerprint for e in entities}
    curr_labels = {e.id: e.label for e in entities}

    prev = store.load_state(surface)
    prev_fp = prev.get("fingerprints") or {}
    prev_labels = prev.get("labels") or {}

    return diff_snapshots(
        prev_fp,
        curr_fp,
        label_map=curr_labels,
        prev_label_map=prev_labels,
    )


def refresh_snapshot(surface: Surface) -> list[ChangeEntry]:
    entities = adapters.read_entities(surface)
    changes = pending_changes(surface, entities)
    curr_fp = {e.id: e.fingerprint for e in entities}
    curr_labels = {e.id: e.label for e in entities}
    store.append_changes(surface, changes)
    store.save_state(
        surface,
        fingerprints=curr_fp,
        labels=curr_labels,
        last_refresh=datetime.now(tz=timezone.utc).isoformat(),
    )
    return changes


def read_changes(surface: Surface, *, limit: int = 200, offset: int = 0) -> list[ChangeEntry]:
    bound = max(1, min(limit, 1000))
    all_changes: list[ChangeEntry] = list(store.iter_changes(surface))
    # Most recent first — the file is append-order, reverse it.
    all_changes.reverse()
    return all_changes[offset : offset + bound]


def current_state(surface: Surface) -> dict:
    return store.load_state(surface)


def clear_changes(surface: Surface) -> None:
    store.clear_changes(surface)


__all__ = [
    "Entity",
    "ChangeEntry",
    "read_snapshot",
    "pending_changes",
    "refresh_snapshot",
    "read_changes",
    "current_state",
    "clear_changes",
    "adapters",
]


# Iterable kept for static-analyzer happiness when consumers import *.
_: Iterable = []
