"""One ledger view across every surface that spends.

Why this exists
---------------
`token_usage_logs` has been the shared write target since V0002 -- chat writes
there, the studio writes there on settle -- but nothing read it as a whole. A
user asking "what have I spent" had to know which table to ask, and an operator
asking "what are we spending" had no single query. Two writers and no reader is
a ledger that records without reporting.

What "central" means here
-------------------------
Not a second table. A second table would need its own idempotency, its own
migration and its own reconciliation, and the first time the two disagreed there
would be no way to say which was right. This module reads the log that already
exists and joins it to what the cost tables know, so there is one source and one
view.

Estimated versus actual
-----------------------
The studio records an `estimate` row at submit and an `actual` row at settle.
Summing both double-counts. Every total here comes from the `actual` phase, and
where only an estimate exists the row is reported as pending rather than counted
— a number that anticipates its own outcome is not a measurement.

Idempotency
-----------
The ledger's own guarantee is `UNIQUE (job_id, phase)` on `media_job_costs`, and
an `INSERT ... ON CONFLICT DO NOTHING` on the log. This module does not add a
second write path, so it cannot introduce a second way to double-count. What it
does add is the check: :func:`assert_consistent` compares the two and fails
loudly, because a ledger nobody reconciles is a ledger nobody can use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from deeptutor.db.connection import Database


@dataclass(frozen=True)
class SpendRow:
    """One line of spend, normalised across surfaces."""

    surface: str
    action: str
    tokens: int
    cost_microusd: int | None
    at: str
    job_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "action": self.action,
            "tokens": self.tokens,
            "cost_microusd": self.cost_microusd,
            "at": self.at,
            "job_id": self.job_id,
        }


def _surface_for(action: str) -> str:
    """Which part of the product spent the tokens.

    A media action is named ``media_job`` by the studio; everything else is the
    chat/ingest path. Adding a surface means adding a case here rather than
    guessing from an arbitrary string later.
    """
    return "studio" if str(action).startswith("media") else "chat"


def summary(db: Database, user_id: str, *, days: int | None = None) -> dict[str, Any]:
    """What this account has spent, by surface, from the one log.

    ``days`` limits to a recent window. Only *actual* costs are summed; a job
    still in flight is reported under ``pending`` so a user can see that work is
    running without being told it has already been charged.
    """
    clause = ""
    params: list[Any] = [user_id]
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        clause = " AND created_at >= ?"
        params.append(cutoff)

    with db.read() as conn:
        logs = list(
            conn.query(
                "SELECT action, total_tokens, cost_toman, created_at "
                "FROM token_usage_logs WHERE user_id = ?" + clause + " ORDER BY created_at",
                tuple(params),
            )
        )
        priced = list(
            conn.query(
                "SELECT job_id, tokens, cost_microusd, created_at "
                "FROM media_job_costs WHERE user_id = ? AND phase = 'actual'"
                + clause,
                tuple(params),
            )
        )
        pending = conn.query_one(
            "SELECT COUNT(*) AS n FROM media_job_costs WHERE user_id = ? "
            "AND phase = 'estimate' AND job_id NOT IN "
            "(SELECT job_id FROM media_job_costs WHERE user_id = ? AND phase = 'actual')",
            (user_id, user_id),
        )

    by_surface: dict[str, dict[str, int]] = {}
    for row in logs:
        surface = _surface_for(str(row["action"]))
        bucket = by_surface.setdefault(surface, {"tokens": 0, "events": 0})
        bucket["tokens"] += int(row["total_tokens"] or 0)
        bucket["events"] += 1

    # The studio's money lives in micro-USD, not Toman, and only on the actual
    # phase. Folding it into the Toman total would need an exchange rate nobody
    # has set, so it is reported beside the total rather than added to it.
    microusd = sum(int(row["cost_microusd"] or 0) for row in priced)

    return {
        "user_id": user_id,
        "window_days": days,
        "tokens_spent": sum(b["tokens"] for b in by_surface.values()),
        "events": sum(b["events"] for b in by_surface.values()),
        "by_surface": by_surface,
        "media_cost_microusd": microusd,
        "media_cost_usd": microusd / 1_000_000,
        "pending_jobs": int((pending or {}).get("n") or 0),
        "note": (
            "media_cost_* covers the studio's actual phase only; token counts "
            "come from token_usage_logs. Combining them is a currency question, "
            "not a join, so they are reported separately"
        ),
    }


def recent(db: Database, user_id: str, *, limit: int = 50) -> list[SpendRow]:
    """The most recent spend events across surfaces, newest first.

    The studio's money lives on `media_job_costs` (the log row carries tokens
    only), so studio entries are built from that table and chat entries from the
    log. Both are then sorted together -- which is the only way a single view
    can answer "what did I spend yesterday" without the reader knowing which
    table each surface happens to write to.
    """
    with db.read() as conn:
        logs = list(
            conn.query(
                "SELECT action, total_tokens, created_at FROM token_usage_logs "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        )
        priced = list(
            conn.query(
                "SELECT job_id, tokens, cost_microusd, created_at FROM media_job_costs "
                "WHERE user_id = ? AND phase = 'actual' ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        )

    rows: list[SpendRow] = []
    for row in logs:
        action = str(row["action"])
        if action.startswith("media"):
            # Already represented by the priced row; listing it twice would
            # double every media job in the user's history.
            continue
        rows.append(
            SpendRow(
                surface="chat",
                action=action,
                tokens=int(row["total_tokens"] or 0),
                cost_microusd=None,
                at=str(row["created_at"]),
            )
        )
    for row in priced:
        rows.append(
            SpendRow(
                surface="studio",
                action="media_job",
                tokens=int(row["tokens"] or 0),
                cost_microusd=(
                    int(row["cost_microusd"]) if row["cost_microusd"] is not None else None
                ),
                at=str(row["created_at"]),
                job_id=str(row["job_id"]),
            )
        )
    rows.sort(key=lambda r: r.at, reverse=True)
    return rows[:limit]


def assert_consistent(db: Database, user_id: str) -> dict[str, Any]:
    """Reconcile the wallet against the log. Returns the differences.

    The wallet is the authority for the balance; the log is the authority for
    how it got there. When they disagree, one of them is wrong and neither is
    trustworthy until we know which, so this reports rather than repairs: an
    automatic fix would erase the evidence of the bug that caused it.
    """
    with db.read() as conn:
        wallet = conn.query_one(
            "SELECT tokens_used, tokens_remaining, tokens_total FROM user_wallets "
            "WHERE user_id = ?",
            (user_id,),
        )
        spent = conn.query_one(
            "SELECT COALESCE(SUM(total_tokens), 0) AS total FROM token_usage_logs "
            "WHERE user_id = ?",
            (user_id,),
        )
    if not wallet:
        return {"user_id": user_id, "ok": False, "reason": "no_wallet"}

    logged = int((spent or {}).get("total") or 0)
    recorded = int(wallet["tokens_used"] or 0)
    return {
        "user_id": user_id,
        "ok": logged == recorded,
        "logged_tokens": logged,
        "wallet_tokens_used": recorded,
        "difference": recorded - logged,
        "note": (
            "the wallet is authoritative for the balance; a difference means a "
            "write happened outside the log, and the evidence is left intact "
            "rather than repaired automatically"
        ),
    }


def operator_totals(db: Database, *, days: int = 30) -> dict[str, Any]:
    """Spend across all accounts, for the admin surface.

    Deliberately does not take a user id: this is the view that must never be
    reachable by a student, and keeping it a different function from
    :func:`summary` is what lets the router mount it on the admin app.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.read() as conn:
        usage = conn.query_one(
            "SELECT COALESCE(SUM(total_tokens), 0) AS tokens, COUNT(*) AS events, "
            "COUNT(DISTINCT user_id) AS users FROM token_usage_logs WHERE created_at >= ?",
            (cutoff,),
        )
        media = conn.query_one(
            "SELECT COALESCE(SUM(tokens), 0) AS tokens, "
            "COALESCE(SUM(COALESCE(cost_microusd, 0)), 0) AS microusd, "
            "COUNT(*) AS jobs FROM media_job_costs WHERE phase = 'actual' "
            "AND created_at >= ?",
            (cutoff,),
        )
    return {
        "window_days": days,
        "tokens_spent": int((usage or {}).get("tokens") or 0),
        "events": int((usage or {}).get("events") or 0),
        "active_users": int((usage or {}).get("users") or 0),
        "media_tokens": int((media or {}).get("tokens") or 0),
        "media_cost_microusd": int((media or {}).get("microusd") or 0),
        "media_cost_usd": int((media or {}).get("microusd") or 0) / 1_000_000,
        "media_jobs": int((media or {}).get("jobs") or 0),
    }


__all__ = [
    "SpendRow",
    "assert_consistent",
    "operator_totals",
    "recent",
    "summary",
]
