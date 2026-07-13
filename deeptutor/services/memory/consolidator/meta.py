"""Per-doc consolidator metadata (``*.meta.json`` files).

For each L2/L3 markdown doc we keep a sidecar JSON capturing the set of
upstream ids "seen" at the last update. ``run_update`` uses set diff
against the live state to compute "what's new since last update" — a
purely id-based diff is robust against mtime / time-zone / replays.

Files
-----
* ``memory/L2/<surface>.meta.json``::

      {
        "version": 1,
        "last_update_at": "<iso-utc>",
        "seen_entity_refs": ["chat:01HZK4...", ...]
      }

* ``memory/L3/<slot>.meta.json``::

      {
        "version": 1,
        "last_update_at": "<iso-utc>",
        "seen_l2_entry_ids": {
          "chat": ["m_xxx", ...],
          "notebook": ["m_yyy"],
          ...
        }
      }

Atomic writes via temp + rename. Missing files behave as "first run".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile

from deeptutor.services.memory import paths
from deeptutor.services.memory.paths import L3Slot, Surface

logger = logging.getLogger(__name__)

_META_VERSION = 1


# ── L2 meta ─────────────────────────────────────────────────────────────


@dataclass
class L2Meta:
    last_update_at: str | None = None
    seen_entity_refs: set[str] = field(default_factory=set)


def l2_meta_path(surface: Surface) -> Path:
    return paths.l2_dir() / f"{surface}.meta.json"


def load_l2_meta(surface: Surface) -> L2Meta:
    return _load_meta_l2(l2_meta_path(surface))


def save_l2_meta(surface: Surface, *, seen_entity_refs: set[str]) -> L2Meta:
    path = l2_meta_path(surface)
    meta = L2Meta(
        last_update_at=_now_iso(),
        seen_entity_refs=set(seen_entity_refs),
    )
    _atomic_write_json(
        path,
        {
            "version": _META_VERSION,
            "last_update_at": meta.last_update_at,
            "seen_entity_refs": sorted(meta.seen_entity_refs),
        },
    )
    return meta


# ── L3 meta ─────────────────────────────────────────────────────────────


@dataclass
class L3Meta:
    last_update_at: str | None = None
    seen_l2_entry_ids: dict[str, set[str]] = field(default_factory=dict)


def l3_meta_path(slot: L3Slot) -> Path:
    return paths.l3_dir() / f"{slot}.meta.json"


def load_l3_meta(slot: L3Slot) -> L3Meta:
    return _load_meta_l3(l3_meta_path(slot))


def save_l3_meta(
    slot: L3Slot,
    *,
    seen_l2_entry_ids: dict[str, set[str]],
) -> L3Meta:
    path = l3_meta_path(slot)
    meta = L3Meta(
        last_update_at=_now_iso(),
        seen_l2_entry_ids={surface: set(ids) for surface, ids in seen_l2_entry_ids.items()},
    )
    _atomic_write_json(
        path,
        {
            "version": _META_VERSION,
            "last_update_at": meta.last_update_at,
            "seen_l2_entry_ids": {
                surface: sorted(ids) for surface, ids in meta.seen_l2_entry_ids.items()
            },
        },
    )
    return meta


# ── Internals ───────────────────────────────────────────────────────────


def _load_meta_l2(path: Path) -> L2Meta:
    data = _read_json(path)
    if not data:
        return L2Meta()
    refs = data.get("seen_entity_refs") or []
    return L2Meta(
        last_update_at=data.get("last_update_at"),
        seen_entity_refs=set(refs) if isinstance(refs, list) else set(),
    )


def _load_meta_l3(path: Path) -> L3Meta:
    data = _read_json(path)
    if not data:
        return L3Meta()
    raw = data.get("seen_l2_entry_ids") or {}
    if not isinstance(raw, dict):
        raw = {}
    return L3Meta(
        last_update_at=data.get("last_update_at"),
        seen_l2_entry_ids={
            surface: set(ids) if isinstance(ids, list) else set() for surface, ids in raw.items()
        },
    )


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("memory meta: failed to read %s: %s", path, exc)
        return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_str, path)
    finally:
        if os.path.exists(tmp_str):
            try:
                os.remove(tmp_str)
            except OSError:
                pass


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


__all__ = [
    "L2Meta",
    "L3Meta",
    "l2_meta_path",
    "l3_meta_path",
    "load_l2_meta",
    "load_l3_meta",
    "save_l2_meta",
    "save_l3_meta",
]
