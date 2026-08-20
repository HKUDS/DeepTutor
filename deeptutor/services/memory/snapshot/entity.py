"""Snapshot data types.

An ``Entity`` is one unit of L1 content for a non-KB surface — e.g. one
notebook record, one co-writer document, one book, one chat session.
The snapshot is the *current* set of these on disk; the diff log records
how that set has changed across refreshes.

These types are intentionally pure dataclasses with no I/O. Adapters
build ``Entity`` lists; ``diff.diff_snapshots`` consumes two ``state``
dicts to produce ``ChangeEntry`` records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass
class Entity:
    id: str
    label: str
    ts: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class Stamped(Protocol):
    """The three fields the diff engine actually reads off an entity.

    Declared read-only so a frozen carrier (:class:`EntityStamp`) satisfies it
    as readily as a mutable one (:class:`Entity`); the diff never writes back.
    """

    @property
    def id(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def fingerprint(self) -> str: ...


@dataclass(frozen=True, slots=True)
class EntityStamp:
    """Just enough of an :class:`Entity` to identify and date it — no ``content``.

    The diff compares fingerprints and carries labels for the change log; it
    never looks at ``content``. Building content anyway costs the chat surface
    every message body of every session, which is affordable for a
    user-initiated refresh and not affordable for something that runs whenever
    a page loads. A surface may therefore offer a *probe* that produces stamps
    directly; see :func:`~deeptutor.services.memory.snapshot.adapters.read_stamps`.

    A probe MUST derive ``id`` / ``label`` / ``fingerprint`` exactly as its full
    adapter does, or a probe-driven refresh and a content-driven one would
    disagree about what changed.

    ``ts`` takes no part in the diff — it rides along because "what happened
    recently" is a question worth answering without reading content either
    (:func:`deeptutor.services.memory.recall.recent` asks exactly that).
    """

    id: str
    label: str
    fingerprint: str
    ts: str = ""


ChangeKind = Literal["added", "modified", "removed"]


@dataclass
class ChangeEntry:
    ts: str
    kind: ChangeKind
    entity_id: str
    label: str
    prev_fingerprint: str | None = None
    new_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["ChangeEntry", "ChangeKind", "Entity", "EntityStamp", "Stamped"]
