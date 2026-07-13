"""L1 raw event trace: append-only JSONL files, one per surface per UTC day.

Trace capture must never break the producing surface — every append is
wrapped and failures are logged-and-swallowed. Writes are serialized
per-surface with an asyncio lock so multiple turns in the same process
don't interleave JSON lines.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Iterator

from deeptutor.services.memory.ids import new_trace_id
from deeptutor.services.memory.paths import SURFACES, Surface, trace_dir, trace_file

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(surface: Surface) -> asyncio.Lock:
    lock = _locks.get(surface)
    if lock is None:
        lock = asyncio.Lock()
        _locks[surface] = lock
    return lock


@dataclass
class TraceEvent:
    id: str
    ts: str
    surface: Surface
    kind: str
    payload: dict[str, Any]
    session_id: str | None = None
    turn_id: str | None = None

    @classmethod
    def new(
        cls,
        surface: Surface,
        kind: str,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> "TraceEvent":
        return cls(
            id=new_trace_id(surface),
            ts=datetime.now(tz=timezone.utc).isoformat(),
            surface=surface,
            kind=kind,
            payload=payload,
            session_id=session_id,
            turn_id=turn_id,
        )


async def append(event: TraceEvent) -> None:
    """Append one event to today's surface trace file. Never raises."""
    try:
        path = trace_file(event.surface, datetime.now(tz=timezone.utc).date())
        line = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        async with _lock_for(event.surface):
            await asyncio.to_thread(_append_line, path, line)
    except Exception:
        logger.warning(
            "memory trace append failed surface=%s kind=%s",
            event.surface,
            event.kind,
            exc_info=True,
        )


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("\n")


def iter_since(surface: Surface, since: datetime | None = None) -> Iterator[TraceEvent]:
    """Yield events for ``surface`` in chronological order, optionally
    filtering to events with ``ts >= since`` (UTC)."""
    files = sorted(trace_dir(surface).glob("*.jsonl"))
    cutoff_iso = since.isoformat() if since else ""
    cutoff_date_iso = since.date().isoformat() if since else ""
    for path in files:
        if cutoff_date_iso and path.stem < cutoff_date_iso:
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if cutoff_iso and obj.get("ts", "") < cutoff_iso:
                        continue
                    yield TraceEvent(**obj)
        except OSError:
            continue


def iter_by_ids(ids: list[str]) -> Iterator[TraceEvent]:
    """Resolve trace ids back to their events. Cross-surface walk."""
    wanted_by_surface: dict[str, set[str]] = {}
    for tid in ids:
        if ":" not in tid:
            continue
        surface, _ = tid.split(":", 1)
        if surface in SURFACES:
            wanted_by_surface.setdefault(surface, set()).add(tid)

    for surface, wanted in wanted_by_surface.items():
        for event in iter_since(surface):  # type: ignore[arg-type]
            if event.id in wanted:
                yield event


def count_since(surface: Surface, since: datetime | None = None) -> int:
    return sum(1 for _ in iter_since(surface, since))


def latest_ts(surface: Surface) -> str | None:
    """Most recent event timestamp for ``surface``, or None."""
    files = sorted(trace_dir(surface).glob("*.jsonl"), reverse=True)
    for path in files:
        try:
            last = ""
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if raw:
                        last = raw
            if last:
                obj = json.loads(last)
                ts = obj.get("ts")
                if isinstance(ts, str):
                    return ts
        except (OSError, json.JSONDecodeError):
            continue
    return None
