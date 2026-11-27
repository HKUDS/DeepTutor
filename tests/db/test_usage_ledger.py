"""One ledger view across chat and studio, and it must reconcile.

Two writers have shared `token_usage_logs` since V0002 and nothing read it as a
whole: a user asking "what have I spent" had to know which table to ask. The
risk in adding a view is that it double-counts (estimate plus actual) or that it
silently disagrees with the wallet. These tests pin both.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services import usage
from deeptutor.services.studio import jobs as S


def _user(db, user_id="u1", tokens=100_000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=tokens)


def _chat_spend(db, tokens=120, user_id="u1"):
    WalletRepository(db).spend(
        user_id, tokens=tokens, action="chat_completion",
        prompt_tokens=int(tokens * 0.8), completion_tokens=int(tokens * 0.2),
    )


def _media_job(db, *, actual=42, user_id="u1", run=True):
    queue = JobQueue(db, worker_id="t")
    submitted = S.submit(
        db, queue=queue,
        request=S.JobRequest(user_id=user_id, kind="mind_map", script="متن"),
    )
    if not run:
        return submitted["job_id"]

    def renderer(kind, payload):
        return S.RenderResult(
            storage_path="m/x.png", mime_type="image/png", size_bytes=10,
            actual_tokens=185, provider="openrouter", actual_cost_microusd=actual,
            content="متن",
        )

    while queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=renderer)}
    ):
        pass
    return submitted["job_id"]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_a_user_with_no_spend_gets_zero_not_an_error(db):
    _user(db)
    result = usage.summary(db, "u1")
    assert result["tokens_spent"] == 0
    assert result["events"] == 0


def test_chat_spend_appears_under_chat(db):
    _user(db)
    _chat_spend(db)
    result = usage.summary(db, "u1")
    assert result["by_surface"]["chat"]["tokens"] == 120
    assert result["tokens_spent"] == 120


def test_media_spend_appears_under_studio(db):
    _user(db)
    _media_job(db)
    result = usage.summary(db, "u1")
    assert "studio" in result["by_surface"]


def test_the_two_surfaces_are_summed_together(db):
    """One view means one total; the split is detail, not a separate answer."""
    _user(db)
    _chat_spend(db, 120)
    _media_job(db)
    result = usage.summary(db, "u1")
    assert result["by_surface"]["chat"]["tokens"] == 120
    assert result["tokens_spent"] >= 120


def test_media_cost_is_reported_in_usd_beside_tokens(db):
    """Tokens and dollars are different units; adding them needs a rate."""
    _user(db)
    _media_job(db, actual=42)
    result = usage.summary(db, "u1")
    assert result["media_cost_microusd"] == 42
    assert result["media_cost_usd"] == 0.000042


def test_an_in_flight_job_is_pending_not_spent(db):
    """An estimate that has not settled is not a measurement."""
    _user(db)
    _media_job(db, run=False)
    result = usage.summary(db, "u1")
    assert result["pending_jobs"] == 1
    assert result["media_cost_microusd"] == 0


def test_a_priced_estimate_is_not_counted_as_spend(db):
    """The estimate phase can carry an expected price; only actual money moved.

    Written directly because the studio's own estimate row leaves the price
    null -- but an estimator that fills it in is the obvious next step, and the
    moment it does, "sum every cost row" starts reporting money that was never
    spent. This pins the distinction before that happens.
    """
    _user(db)
    job_id = _media_job(db, actual=42)
    # The settle path already wrote an estimate row; the unique index on
    # (job_id, phase) is what makes idempotency possible, so this prices that
    # row rather than adding a second one.
    with db.transaction() as conn:
        updated = conn.execute(
            "UPDATE media_job_costs SET cost_microusd = 900, tokens = 999 "
            "WHERE job_id = ? AND phase = 'estimate'",
            (job_id,),
        )
    assert updated == 1, "the settle path wrote no estimate row to price"
    result = usage.summary(db, "u1")
    assert result["media_cost_microusd"] == 42, "the estimate was counted as spend"
    assert result["pending_jobs"] == 0


# ---------------------------------------------------------------------------
# Recent events
# ---------------------------------------------------------------------------


def test_recent_lists_newest_first(db):
    _user(db)
    _chat_spend(db, 10)
    _chat_spend(db, 20)
    rows = usage.recent(db, "u1")
    assert len(rows) == 2
    assert rows[0].at >= rows[1].at


def test_a_media_job_appears_once(db):
    """The log row and the cost row describe one job; listing both doubles it."""
    _user(db)
    _chat_spend(db, 10)  # so the total row count is not 1 by accident
    _media_job(db)
    all_rows = usage.recent(db, "u1")
    studio_rows = [r for r in all_rows if r.surface == "studio"]
    assert len(studio_rows) == 1, f"media job listed {len(studio_rows)} times"
    assert studio_rows[0].cost_microusd == 42
    assert len(all_rows) == 2


def test_a_studio_row_carries_its_job_id(db):
    _user(db)
    job_id = _media_job(db)
    row = next(r for r in usage.recent(db, "u1") if r.surface == "studio")
    assert row.job_id == job_id


def test_recent_respects_the_limit(db):
    _user(db)
    for _ in range(5):
        _chat_spend(db, 10)
    assert len(usage.recent(db, "u1", limit=3)) == 3


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_a_clean_ledger_reconciles(db):
    _user(db)
    _chat_spend(db, 120)
    result = usage.assert_consistent(db, "u1")
    assert result["ok"] is True
    assert result["difference"] == 0


def test_a_wallet_write_outside_the_log_is_reported(db):
    """The failure this exists to catch: a balance change with no record."""
    _user(db)
    _chat_spend(db, 120)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_wallets SET tokens_used = tokens_used + 50, "
            "tokens_remaining = tokens_remaining - 50 WHERE user_id = ?",
            ("u1",),
        )
    result = usage.assert_consistent(db, "u1")
    assert result["ok"] is False
    assert result["difference"] == 50


def test_reconciliation_reports_rather_than_repairs(db):
    """An automatic fix would erase the evidence of the bug that caused it."""
    _user(db)
    # The wallet's own CHECK pins tokens_remaining = tokens_total - tokens_used,
    # so a corrupt state has to be corrupt *consistently*: bump both used and
    # remaining-inverse together, which is exactly what a bug outside the log
    # would do. The first version of this test wrote an impossible row and was
    # rejected by the schema -- the constraint doing its job.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_wallets SET tokens_total = 1000, tokens_used = 77, "
            "tokens_remaining = 923 WHERE user_id = ?",
            ("u1",),
        )
    usage.assert_consistent(db, "u1")
    with db.read() as conn:
        wallet = conn.query_one("SELECT tokens_used FROM user_wallets WHERE user_id = ?", ("u1",))
    assert wallet["tokens_used"] == 77, "the reconciler changed the wallet"


def test_a_missing_wallet_is_reported_not_crashed(db):
    result = usage.assert_consistent(db, "nobody")
    assert result["ok"] is False
    assert result["reason"] == "no_wallet"


# ---------------------------------------------------------------------------
# Operator view
# ---------------------------------------------------------------------------


def test_operator_totals_span_all_users(db):
    _user(db, "u1")
    _user(db, "u2")
    _chat_spend(db, 100, "u1")
    _chat_spend(db, 200, "u2")
    totals = usage.operator_totals(db)
    assert totals["tokens_spent"] == 300
    assert totals["active_users"] == 2


def test_operator_totals_include_media_cost(db):
    _user(db)
    _media_job(db, actual=42)
    totals = usage.operator_totals(db)
    assert totals["media_cost_microusd"] == 42
    assert totals["media_jobs"] == 1


def test_operator_totals_span_media_across_accounts(db):
    """The operator view is defined by *not* being scoped to one account."""
    _user(db, "u1")
    _user(db, "u2")
    _media_job(db, actual=42, user_id="u1")
    _media_job(db, actual=8, user_id="u2")
    totals = usage.operator_totals(db)
    assert totals["media_jobs"] == 2, "the operator view was scoped to one user"
    assert totals["media_cost_microusd"] == 50


def test_the_operator_view_is_a_different_function(db):
    """Keeping it separate is what lets the router mount it on the admin app."""
    assert usage.operator_totals is not usage.summary
    import inspect

    assert "user_id" not in inspect.signature(usage.operator_totals).parameters
