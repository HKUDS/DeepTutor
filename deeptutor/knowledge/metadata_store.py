"""Atomic, lock-guarded access to a knowledge base's ``metadata.json``."""

from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.config_store import KBConfigStore


def get_metadata_store(metadata_file: Path | str) -> KBConfigStore:
    """Return the shared store for metadata without KB-config-specific validation."""
    return KBConfigStore(
        metadata_file,
        default_factory=dict,
        validate_kb_schema=False,
        create_parent=False,
    )
