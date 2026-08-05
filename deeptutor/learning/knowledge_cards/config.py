"""Configuration knobs for the knowledge-card draft runtime (KB-02).

Values are plain dataclasses so tests and the settings layer can override them
without coupling this task to a new settings file, mirroring the media runtime
(``deeptutor.services.media.config``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeCardLimits:
    """Bounds and policy for card content, blobs and the generation lease."""

    #: Maximum length of a generated title. Bounded so executor output can never
    #: push an unbounded blob into a durable record (§7.9.1 / requirement 5).
    max_title_chars: int = 200
    #: Maximum length of a generated body.
    max_body_chars: int = 6000
    #: Maximum serialized size of an output blob payload.
    max_blob_bytes: int = 64 * 1024
    #: How long a generation lease stays valid without renewal.
    lease_duration_seconds: float = 300.0
    #: Maximum generation attempts per card before retry is refused.
    max_generation_attempts: int = 20
    #: Maximum artifacts attachable to one card.
    max_artifact_attachments: int = 32


__all__ = ["KnowledgeCardLimits"]
