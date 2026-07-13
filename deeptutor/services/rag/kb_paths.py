"""Resolve the on-disk directory backing a knowledge base.

Ordinary KBs live at ``<kb_base_dir>/<kb_name>``. A *linked* KB is a pointer to
an engine index the user already built elsewhere: its ``kb_config.json`` entry
carries an ``external_path`` we resolve to instead, so retrieval reads that
folder in place — no copy, no re-index.

This is the single seam every pipeline goes through to find a KB's storage
root. Pipelines must never compute ``Path(kb_base_dir) / kb_name`` directly, or
linked KBs would resolve to a non-existent local folder and silently return no
results.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.kb_types import external_root_of

KB_CONFIG_FILENAME = "kb_config.json"


def resolve_kb_dir(kb_base_dir: str | Path, kb_name: str) -> Path:
    """Return the directory holding ``kb_name``'s index.

    For a linked KB this is the user's external folder; for every other KB it
    is the conventional ``<kb_base_dir>/<kb_name>``.
    """
    base = Path(kb_base_dir)
    external = _external_path(base, kb_name)
    if external:
        return Path(external).expanduser()
    return base / kb_name


def _external_path(base: Path, kb_name: str) -> str | None:
    """Read a KB entry's external pointer from ``kb_config.json``, if any."""
    cfg = base / KB_CONFIG_FILENAME
    if not cfg.exists():
        return None
    try:
        with open(cfg, encoding="utf-8") as handle:
            entry = json.load(handle).get("knowledge_bases", {}).get(kb_name, {})
    except Exception:
        return None
    return external_root_of(entry)


__all__ = ["resolve_kb_dir"]
