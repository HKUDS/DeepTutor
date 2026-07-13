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
from typing import Any, Literal


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
