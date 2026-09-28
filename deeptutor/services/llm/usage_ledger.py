"""Durable per-account LLM accounting, independent of conversations and UI entry points.

Only identifiers, timestamps and numeric measurements are stored. Prompts,
responses, credentials and endpoint URLs never enter this database.
"""

from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any

_CALL_FIELDS = frozenset(
    {
        "call_id",
        "model",
        "provider",
        "status",
        "estimated",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "reasoning_tokens",
        "duration_seconds",
        "ttft_seconds",
        "generation_seconds",
        "tokens_per_second",
        "cache_hit_rate",
    }
)


def ledger_path() -> Path:
    from deeptutor.multi_user.paths import get_owner_path_service

    return get_owner_path_service().get_user_root() / "usage.sqlite3"


def record_call(
    path: Path,
    call: dict[str, Any],
    *,
    started_at: float,
    session_id: str = "",
    turn_id: str = "",
    source: str = "",
) -> None:
    from deeptutor.utils.secret_files import ensure_private_directory, ensure_private_file

    ensure_private_directory(path.parent)
    with closing(sqlite3.connect(path, timeout=5)) as conn, conn:
        ensure_private_file(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_calls (
            call_id TEXT PRIMARY KEY, started_at REAL NOT NULL,
            session_id TEXT NOT NULL, turn_id TEXT NOT NULL, source TEXT NOT NULL,
            usage_json TEXT NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_time ON llm_calls(started_at)")
        conn.execute(
            """INSERT OR IGNORE INTO llm_calls VALUES (?, ?, ?, ?, ?, ?)""",
            (
                call["call_id"],
                started_at,
                session_id,
                turn_id,
                source,
                json.dumps({k: v for k, v in call.items() if k in _CALL_FIELDS}, allow_nan=False),
            ),
        )


def usage_records(
    start_at: float, end_at: float, *, path: Path | None = None
) -> list[dict[str, Any]]:
    path = path or ledger_path()
    if not path.exists():
        return []
    from .metrics import TurnUsage

    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'llm_calls'").fetchone():
            return []
        rows = conn.execute(
            """SELECT started_at, session_id, turn_id, source, usage_json
                               FROM llm_calls WHERE started_at >= ? AND started_at < ?
                               ORDER BY started_at, call_id""",
            (start_at, end_at),
        )
        records = []
        for stamp, session, turn, source, raw in rows:
            collector = TurnUsage()
            collector.calls.append(json.loads(raw))
            records.append(
                {
                    "created_at": stamp,
                    "session_id": session,
                    "turn_id": turn,
                    "activity_id": turn or collector.calls[0]["call_id"],
                    "source": source,
                    "summaries": [collector.summary()],
                }
            )
        return records


def merge_records(
    history: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    *,
    persisted_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Call IDs prevent ledger/snapshot overlap; keep history-only calls on partial writes."""
    ids = (persisted_ids or set()) | {
        call["call_id"]
        for record in ledger
        for summary in record["summaries"]
        for call in summary["call_details"]
    }
    from .metrics import TurnUsage

    merged = []
    for record in history:
        summaries = []
        for summary in record.get("summaries") or []:
            details = summary.get("call_details") or []
            if details and any(c.get("call_id") in ids for c in details):
                collector = TurnUsage()
                collector.calls = [c for c in details if c.get("call_id") not in ids]
                if rest := collector.summary():
                    summaries.append(rest)
            else:
                summaries.append(summary)
        merged.append({**record, "summaries": summaries})
    return merged + ledger


def combined_usage_records(
    history: list[dict[str, Any]], start_at: float, end_at: float
) -> list[dict[str, Any]]:
    path = ledger_path()
    ledger = usage_records(start_at, end_at, path=path)
    # A request can start before New Year and finish after it. Its ledger date
    # remains authoritative even when that call lies outside this year's query.
    candidates = list(
        {
            str(c["call_id"])
            for record in history
            for summary in record.get("summaries", [])
            for c in summary.get("call_details", [])
            if c.get("call_id")
        }
    )
    persisted: set[str] = set()
    if candidates and path.exists():
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'llm_calls'").fetchone():
                return merge_records(history, ledger)
            for start in range(0, len(candidates), 500):
                batch = candidates[start : start + 500]
                marks = ",".join("?" for _ in batch)
                persisted.update(
                    row[0]
                    for row in conn.execute(
                        f"SELECT call_id FROM llm_calls WHERE call_id IN ({marks})",  # nosec B608 - placeholders only
                        batch,
                    )
                )
    return merge_records(history, ledger, persisted_ids=persisted)
