"""On-disk persistence for snapshot state + change log.

Each surface gets its own ``<memory_dir>/snapshot/<surface>/`` directory
holding:

- ``state.json``     — current ``{entity_id: fingerprint}`` map plus
                       a parallel ``labels`` map (so removals can show
                       the old human-readable title) and ``last_refresh``.
- ``changes.jsonl``  — append-only diff log (one ``ChangeEntry`` per line).

State writes are atomic via temp-file + rename. Changes are appended
line-by-line, which is naturally atomic on POSIX filesystems.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Iterator

from deeptutor.services.memory.paths import Surface, memory_root
from deeptutor.services.memory.snapshot.entity import ChangeEntry


def snapshot_dir(surface: Surface) -> Path:
    return memory_root() / "snapshot" / surface


def state_file(surface: Surface) -> Path:
    return snapshot_dir(surface) / "state.json"


def changes_file(surface: Surface) -> Path:
    return snapshot_dir(surface) / "changes.jsonl"


def load_state(surface: Surface) -> dict:
    path = state_file(surface)
    if not path.exists():
        return {"fingerprints": {}, "labels": {}, "last_refresh": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"fingerprints": {}, "labels": {}, "last_refresh": None}
    return {
        "fingerprints": data.get("fingerprints") or {},
        "labels": data.get("labels") or {},
        "last_refresh": data.get("last_refresh"),
    }


def save_state(
    surface: Surface,
    *,
    fingerprints: dict[str, str],
    labels: dict[str, str],
    last_refresh: str,
) -> None:
    target = state_file(surface)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    payload = {
        "fingerprints": fingerprints,
        "labels": labels,
        "last_refresh": last_refresh,
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def append_changes(surface: Surface, changes: list[ChangeEntry]) -> None:
    if not changes:
        return
    path = changes_file(surface)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for change in changes:
            fh.write(json.dumps(asdict(change), ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")


def iter_changes(surface: Surface) -> Iterator[ChangeEntry]:
    path = changes_file(surface)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield ChangeEntry(
                ts=obj.get("ts", ""),
                kind=obj.get("kind", "modified"),
                entity_id=obj.get("entity_id", ""),
                label=obj.get("label", ""),
                prev_fingerprint=obj.get("prev_fingerprint"),
                new_fingerprint=obj.get("new_fingerprint"),
            )


def clear_changes(surface: Surface) -> None:
    path = changes_file(surface)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
