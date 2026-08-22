"""Core data models for the MarginNote 4 bridge.

These types describe MN4 objects as they land in DeepTutor after sync.
The MN4 Add-on serialises its native objects (notes, excerpts, cards, mindmap
nodes, documents) into :class:`MarginNoteObject` rows that the sync store
indexes and the capability tools query.

Design notes
------------
* Every object carries a stable ``object_id`` derived from MN4's internal ID,
  so re-syncs update in place instead of creating duplicates.
* Text fields (``title``, ``excerpt``, ``content``) are plain strings — no
  HTML or MN4 markup. The Add-on is responsible for flattening rich text.
* ``raw`` preserves the original MN4 JSON for fields DeepTutor does not model
  yet, so the schema can grow without re-syncing.
* ``device_id`` ties each object to the paired device that synced it, so a
  user with multiple devices can tell which copy is authoritative.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# Object types — what kind of MN4 entity a row represents.
# --------------------------------------------------------------------------- #

NOTE = "note"  # A highlight, underline, or text selection annotation.
EXCERPT = "excerpt"  # An excerpt block (longer quoted passage).
CARD = "card"  # A flashcard with front/back.
MINDMAP_NODE = "mindmap_node"  # A node in the study mindmap.
DOCUMENT = "document"  # A source document (PDF, EPUB, web).
COMMENT = "comment"  # A free-form comment attached to a note or node.

ALL_TYPES: frozenset[str] = frozenset({NOTE, EXCERPT, CARD, MINDMAP_NODE, DOCUMENT, COMMENT})


@dataclass(slots=True)
class MarginNoteObject:
    """One synced MarginNote 4 entity.

    Attributes:
        object_id:  Stable ID from MN4 (its internal ``noteId`` / ``nodeId``).
        object_type:  One of :data:`ALL_TYPES`.
        title:  Display title (note title, card title, node text, doc title).
        content:  Primary text body. For a card this is the front; for an
            annotation it is the excerpt text; for a mindmap node it is the
            node's text content.
        excerpt:  Quoted source text (the highlighted passage), when the object
            is anchored to a document. ``None`` for cards without a source.
        document_id:  ID of the source document, when the object belongs to one.
        document_title:  Human-readable title of the source document.
        page:  Page number in the source document, when known.
        tags:  User-assigned tags.
        links:  IDs of linked MN4 objects (parent/child in mindmap,
            linked cards, etc.).
        color:  MN4 highlight colour label, when applicable.
        created_at:  ISO-8601 timestamp from MN4.
        updated_at:  ISO-8601 timestamp from MN4 (last modification).
        synced_at:  ISO-8601 timestamp when DeepTutor received this version.
        device_id:  The paired device that synced this object.
        raw:  Original MN4 JSON payload, preserved verbatim for forward compat.
    """

    object_id: str
    object_type: str
    title: str = ""
    content: str = ""
    excerpt: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page: int | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    color: str | None = None
    created_at: str = ""
    updated_at: str = ""
    synced_at: str = ""
    device_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON responses and storage."""
        return asdict(self)


@dataclass(slots=True)
class SyncBatch:
    """A batch of objects pushed by a device during incremental sync.

    Attributes:
        device_id:  The paired device pushing this batch.
        cursor:  Monotonic sync position this batch advances from.
        objects:  New or updated objects since the previous cursor.
        deleted_ids:  IDs tombstoned since the previous cursor.
    """

    device_id: str
    cursor: str = ""
    objects: list[MarginNoteObject] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SyncResult:
    """Outcome of ingesting a :class:`SyncBatch` into the store."""

    stored: int = 0
    updated: int = 0
    deleted: int = 0
    new_cursor: str = ""


@dataclass(slots=True)
class PairedDevice:
    """A MarginNote 4 device registered with this DeepTutor instance.

    Attributes:
        device_id:  Stable identifier generated at pairing time.
        device_name:  Human-readable label (e.g. "MacBook Pro", "iPad").
        device_kind:  ``macos`` or ``ipados``.
        paired_at:  ISO-8601 timestamp.
        last_seen:  ISO-8601 timestamp of last sync or heartbeat.
        active:  Whether the device is currently enabled.
    """

    device_id: str
    device_name: str = ""
    device_kind: str = "macos"
    paired_at: str = ""
    last_seen: str = ""
    active: bool = True


@dataclass(slots=True)
class LearningEvent:
    """A study event observed on the MN4 side (Phase 3).

    Captures a review or study interaction so DeepTutor can track mastery
    without touching MN4's private FSRS scheduling data.

    Attributes:
        event_id:  Unique event identifier.
        object_id:  The MN4 object studied (usually a card).
        event_type:  ``review``, ``study``, ``flag``, ``confidence``.
        outcome:  ``again``, ``hard``, ``good``, ``easy`` (or free text).
        timestamp:  ISO-8601.
        device_id:  Device that observed the event.
    """

    event_id: str
    object_id: str
    event_type: str = "review"
    outcome: str = ""
    timestamp: str = ""
    device_id: str = ""


__all__ = [
    "ALL_TYPES",
    "CARD",
    "COMMENT",
    "DOCUMENT",
    "EXCERPT",
    "LearningEvent",
    "MINDMAP_NODE",
    "NOTE",
    "MarginNoteObject",
    "PairedDevice",
    "SyncBatch",
    "SyncResult",
]
