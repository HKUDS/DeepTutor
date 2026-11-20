"""A price is a fact about a moment, not a column you overwrite.

An `UPDATE plans SET price_toman = ...` would make last month's invoice
unexplainable and a cost recorded under the old price silently wrong. These
tests pin that history survives.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.services import entitlements as E
from deeptutor.services.studio.jobs import StudioError

JAN = datetime(2026, 1, 1, tzinfo=timezone.utc)
APR = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _price(db, price=100_000, quota=500_000, days=30, at=JAN, code="pro"):
    return E.set_price(
        db, plan_code=code, price_toman=price, token_quota=quota,
        duration_days=days, effective_from=at,
    )


def _plan(db, code="pro"):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO plans (code, name, price_toman, token_quota, duration_days, "
            "is_active, sort_order, storage_quota_bytes, updated_at, capabilities) "
            "VALUES (?, ?, 0, 100000, 30, 1, 1, 104857600, ?, 'studio')",
            (code, code, JAN.isoformat()),
        )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_a_price_is_recorded(db):
    price = _price(db)
    assert price.price_toman == 100_000
    assert price.effective_from.startswith("2026-01-01")


def test_a_later_price_does_not_erase_the_earlier_one(db):
    _price(db, price=100_000, at=JAN)
    _price(db, price=150_000, at=APR)
    history = E.price_history(db, "pro")
    assert [p.price_toman for p in history] == [100_000, 150_000]


def test_a_past_moment_is_answered_from_the_row_in_force_then(db):
    """The whole reason this is versioned: last quarter's invoice."""
    _price(db, price=100_000, at=JAN)
    _price(db, price=150_000, at=APR)
    assert E.price_at(db, "pro", at=JAN + timedelta(days=45)).price_toman == 100_000
    assert E.price_at(db, "pro", at=APR + timedelta(days=1)).price_toman == 150_000


def test_the_current_price_is_the_newest_effective_row(db):
    _price(db, price=100_000, at=JAN)
    _price(db, price=150_000, at=APR)
    assert E.price_at(db, "pro").price_toman == 150_000


def test_a_future_price_does_not_apply_yet(db):
    """Scheduling an increase must not change what anyone is charged today."""
    _price(db, price=100_000, at=JAN)
    _price(db, price=999_000, at=datetime.now(timezone.utc) + timedelta(days=90))
    assert E.price_at(db, "pro").price_toman == 100_000


def test_a_moment_before_any_price_has_no_answer(db):
    _price(db, at=APR)
    assert E.price_at(db, "pro", at=JAN) is None


def test_an_unknown_plan_has_no_price(db):
    assert E.price_at(db, "never-sold") is None
    assert E.price_history(db, "never-sold") == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"price_toman": -1},
        {"token_quota": -1},
        {"duration_days": 0},
        {"duration_days": -30},
    ],
)
def test_an_impossible_price_is_refused(db, kwargs):
    args = {"price_toman": 100_000, "token_quota": 500_000, "duration_days": 30}
    args.update(kwargs)
    with pytest.raises(StudioError) as exc:
        E.set_price(db, plan_code="pro", effective_from=JAN, **args)
    assert exc.value.rule == "invalid_price"


def test_a_refused_price_leaves_no_row(db):
    with pytest.raises(StudioError):
        _price(db, price=-5)
    assert E.price_history(db, "pro") == []


def test_a_free_plan_is_a_valid_price(db):
    assert _price(db, price=0).price_toman == 0


# ---------------------------------------------------------------------------
# What the price is attached to
# ---------------------------------------------------------------------------


def test_prices_and_plans_are_linked_by_code_not_by_id(db):
    """A price row outlives a plan row being edited; the code is the key."""
    _plan(db)
    _price(db)
    with db.transaction() as conn:
        conn.execute("UPDATE plans SET price_toman = 777 WHERE code = 'pro'")
    assert E.price_at(db, "pro", at=JAN + timedelta(days=1)).price_toman == 100_000
    with db.read() as conn:
        row = conn.query_one("SELECT price_toman FROM plans WHERE code = 'pro'")
    assert row["price_toman"] == 777, "the plans row is not the price of record"
