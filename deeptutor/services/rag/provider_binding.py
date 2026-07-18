"""Resolve a knowledge base's bound RAG provider.

DeepTutor owns the knowledge-base lifecycle and stores the authoritative
provider binding in ``kb_config.json``. Older KBs may only have
``metadata.json``, so metadata remains a legacy fallback. Retrieval and
incremental indexing should use this helper instead of hand-reading either file
directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deeptutor.knowledge.config_store import KBConfigStore
from deeptutor.services.rag.factory import DEFAULT_PROVIDER, normalize_provider_name


def load_kb_config_entry(kb_base_dir: str | Path, kb_name: str) -> dict[str, Any]:
    """Return the raw ``kb_config.json`` entry for ``kb_name``, if present.

    A missing config file reads as empty. A file that exists but does not
    parse raises ``KBConfigCorruptionError`` — silently returning ``{}``
    here would rebind the KB to the default provider and mask the damage.
    """
    config = KBConfigStore(Path(kb_base_dir) / "kb_config.json").read()
    knowledge_bases = config.get("knowledge_bases")
    if not isinstance(knowledge_bases, dict):
        return {}
    entry = knowledge_bases.get(kb_name, {})
    return entry if isinstance(entry, dict) else {}


def load_metadata_provider(kb_base_dir: str | Path, kb_name: str) -> str | None:
    """Return the provider stored in legacy ``metadata.json``, if present."""
    metadata_path = Path(kb_base_dir) / kb_name / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        with open(metadata_path, encoding="utf-8") as handle:
            provider = json.load(handle).get("rag_provider")
    except Exception:
        return None
    return normalize_provider_name(provider) if provider else None


def resolve_bound_provider(kb_base_dir: str | Path, kb_name: str | None) -> str:
    """Resolve the provider DeepTutor has bound to a KB.

    Order:
    1. ``kb_config.json``: authoritative runtime state.
    2. ``metadata.json``: legacy/import fallback.
    3. default provider.

    A corrupt ``kb_config.json`` raises ``KBConfigCorruptionError`` instead
    of falling through — resolving a damaged binding to the default provider
    would silently query the wrong engine.
    """
    if kb_name:
        entry = load_kb_config_entry(kb_base_dir, kb_name)
        provider = entry.get("rag_provider")
        if provider:
            return normalize_provider_name(provider)

        metadata_provider = load_metadata_provider(kb_base_dir, kb_name)
        if metadata_provider:
            return metadata_provider

    return DEFAULT_PROVIDER


__all__ = [
    "load_kb_config_entry",
    "load_metadata_provider",
    "resolve_bound_provider",
]
