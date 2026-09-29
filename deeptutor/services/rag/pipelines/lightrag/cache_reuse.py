"""Seed a rebuild with content-bound LightRAG indexing responses (#1577)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

from deeptutor.services.file_io import atomic_write_json

from .engine import workspace_for

logger = logging.getLogger(__name__)

_CACHE_FILE = "kv_store_llm_response_cache.json"
# Query answers and keyword extraction depend on the current graph and must
# never cross a full rebuild. These types are produced from source content by
# the pinned LightRAG SDK and include the model identity in their hash.
_INDEX_TYPES = frozenset({"extract", "summary", "analysis", "smartheading"})
_CACHE_KEY = re.compile(r"^[^:]+:([a-z]+):[0-9a-f]{32,64}$")


def _policy_identity(policy: Any) -> tuple[str, str, str] | None:
    """Read both current nested role fingerprints and older flat policies."""
    if not isinstance(policy, dict):
        return None
    extract = policy.get("extract")
    if isinstance(extract, dict):
        vlm = policy.get("vlm") if isinstance(policy.get("vlm"), dict) else {}
        vlm_snapshot = vlm.get("snapshot") if isinstance(vlm.get("snapshot"), dict) else {}
        fingerprint = extract.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            return (
                fingerprint,
                str(vlm.get("mode") or "disabled"),
                str(vlm_snapshot.get("fingerprint") or ""),
            )
    fingerprint = policy.get("fingerprint")
    if isinstance(fingerprint, str) and fingerprint:
        return (fingerprint, "", "")
    return None


def _read_policy_identity(root: Path) -> tuple[str, str, str] | None:
    try:
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Interrupted versions have no publication marker but may already
        # have a durable cache worth preserving.
        return None
    return _policy_identity(meta.get("indexing_policy")) if isinstance(meta, dict) else None


def _index_entries(path: Path) -> dict[str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable LightRAG cache %s: %s", path, type(exc).__name__)
        return {}
    if not isinstance(payload, dict):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        match = _CACHE_KEY.fullmatch(key) if isinstance(key, str) else None
        if (
            match
            and match.group(1) in _INDEX_TYPES
            and isinstance(value, dict)
            and value.get("cache_type") == match.group(1)
            and isinstance(value.get("return"), str)
            and value["return"]
        ):
            entries[key] = value
    return entries


def inherit_index_cache(kb_dir: Path, target_root: Path, policy: dict[str, Any]) -> bool:
    """Carry only verified indexing responses into a fresh version workspace.

    Merge matching published versions with the immediately preceding
    interrupted version, which may have no ``meta.json``. A partial interrupted
    cache must not hide the rest of an older published cache. Newer entries win
    on duplicate content keys; query answers never enter the merge.
    """
    target = target_root / workspace_for(target_root) / _CACHE_FILE
    if target.exists():
        return False
    target_identity = _policy_identity(policy)
    target_version = int(target_root.name.removeprefix("version-"))
    candidates: list[tuple[int, int, int, Path]] = []
    for root in kb_dir.glob("version-*"):
        if not root.is_dir() or root == target_root:
            continue
        try:
            version = int(root.name.removeprefix("version-"))
        except ValueError:
            continue
        if version >= target_version:
            continue
        donor_identity = _read_policy_identity(root)
        # An unpublished predecessor may already have useful content-addressed
        # extraction calls. Published versions must match the current roles.
        if donor_identity is None and version == target_version - 1:
            identity_rank = 3
        elif donor_identity is not None and (
            target_identity is None or donor_identity == target_identity
        ):
            identity_rank = 2
        else:
            continue
        paths = [root / _CACHE_FILE, *root.glob(f"deeptutor_*/{_CACHE_FILE}")]
        for path in paths:
            if path.is_file() and not path.is_symlink():
                candidates.append((identity_rank, version, int(path.parent != root), path))
    if not candidates:
        return False

    merged: dict[str, dict[str, Any]] = {}
    used = 0
    for _, _, _, donor in sorted(candidates):
        entries = _index_entries(donor)
        if not entries:
            continue
        merged.update(entries)
        used += 1
    if not merged:
        return False
    atomic_write_json(target, merged)
    logger.info("Inherited %d LightRAG indexing cache entries from %d donors", len(merged), used)
    return True


__all__ = ["inherit_index_cache"]
