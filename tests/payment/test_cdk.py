"""Tests for the offline CDK (card-key) engine.

Covers generation invariants, single-use atomic redemption, concurrency safety,
anti-brute-force budgeting, expiry handling, and export (JSON/CSV).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from threading import Barrier, Thread

import pytest

from deeptutor.payment.cdk import (
    CODE_STATUS_REDEEMED,
    CODE_STATUS_UNUSED,
    REDEEM_ATTEMPTS_PER_HOUR,
    CDKNotFoundError,
    CDKValidationError,
    RedeemFailure,
    export_batch_codes,
    generate_batch,
    list_batches,
    list_codes_for_batch,
    lookup_batch,
    redeem_cdk,
)

PLAN = {
    "id": "plan_monthly",
    "name": "月度会员",
    "price": "9.9",
    "valid_days": 30,
    "models": {"llm": [{"profile_id": "fast"}]},
    "knowledge_bases": [{"resource_id": "admin:kb:math"}],
    "books": ["bk_math"],
}


@pytest.fixture
def batch(pay_isolated_root):
    return generate_batch(plan=PLAN, count=10, expires_in_days=30, creator="admin")


def test_generate_batch_returns_unique_codes(batch):
    codes = batch["codes"]
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert batch["batch"]["plan"]["id"] == "plan_monthly"
    assert batch["batch"]["count"] == 10
    for code in codes:
        assert len(code) >= 8


def test_generate_batch_validates_input(pay_isolated_root):
    with pytest.raises(CDKValidationError):
        generate_batch(plan=PLAN, count=0)
    with pytest.raises(CDKValidationError):
        generate_batch(plan={}, count=1)  # missing plan id
    with pytest.raises(CDKValidationError):
        generate_batch(plan=PLAN, count=1, expires_in_days=0)


def test_codes_are_single_use(batch, make_user, seed_user):
    alice = seed_user("alice", role="user")
    code = batch["codes"][0]
    token = set_current(make_user("u_alice", username="alice"))
    try:
        result = redeem_cdk(code=code, user_id=alice["id"], username="alice")
        assert result["code_digest"]
        assert result["plan"]["id"] == "plan_monthly"

        # Re-submission by the same account is idempotent, not an error.
        again = redeem_cdk(code=code, user_id=alice["id"], username="alice")
        assert again.get("idempotent") is True
        assert again["grant"]["models"]["llm"][0]["profile_id"] == "fast"
    finally:
        reset_current(token)


def test_redeem_unknown_code(batch, make_user, seed_user):
    alice = seed_user("alice", role="user")
    token = set_current(make_user("u_alice", username="alice"))
    try:
        with pytest.raises(RedeemFailure) as exc:
            redeem_cdk(code="NONEXISTENT123", user_id=alice["id"], username="alice")
        assert exc.value.reason == "invalid_code"
    finally:
        reset_current(token)


def test_redeem_already_used_code_fails_for_other_user(batch, make_user, seed_user):
    alice = seed_user("alice", role="user")
    bob = seed_user("bob", role="user")
    code = batch["codes"][0]
    token = set_current(make_user("u_alice", username="alice"))
    try:
        redeem_cdk(code=code, user_id=alice["id"], username="alice")
    finally:
        reset_current(token)

    token = set_current(make_user("u_bob", username="bob"))
    try:
        with pytest.raises(RedeemFailure) as exc:
            redeem_cdk(code=code, user_id=bob["id"], username="bob")
        assert exc.value.reason == "already_redeemed"
    finally:
        reset_current(token)


def test_redeem_expired_code(pay_isolated_root, make_user, seed_user):
    import datetime as _dt

    from deeptutor.payment import cdk as cdk_module

    # Generate with a very short expiry and force-expire by backdating.
    result = generate_batch(plan=PLAN, count=1, expires_in_days=30)
    code = result["codes"][0]
    store_path = cdk_module.cdk_store_path()
    store = json.loads(store_path.read_text(encoding="utf-8"))
    digest = list(store["codes"].keys())[0]
    past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).isoformat()
    store["codes"][digest]["expires_at"] = past
    store_path.write_text(json.dumps(store), encoding="utf-8")

    alice = seed_user("alice", role="user")
    token = set_current(make_user("u_alice", username="alice"))
    try:
        with pytest.raises(RedeemFailure) as exc:
            redeem_cdk(code=code, user_id=alice["id"], username="alice")
        assert exc.value.reason == "expired_code"
    finally:
        reset_current(token)


def test_concurrent_redeem_consumes_once(batch, make_user, seed_user):
    """Two threads racing on the same code — exactly one wins."""
    alice = seed_user("alice", role="user")
    bob = seed_user("bob", role="user")
    code = batch["codes"][0]
    outcomes: list[str] = []
    barrier = Barrier(2)

    def worker(user_id: str, username: str):
        token = set_current(make_user(f"u_{username}", username=username))
        try:
            barrier.wait(timeout=5)
            try:
                redeem_cdk(code=code, user_id=user_id, username=username)
                outcomes.append(username)
            except RedeemFailure as exc:
                outcomes.append(f"fail:{exc.reason}")
        finally:
            reset_current(token)

    t1 = Thread(target=worker, args=(alice["id"], "alice"))
    t2 = Thread(target=worker, args=(bob["id"], "bob"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    winners = [o for o in outcomes if not o.startswith("fail:")]
    losers = [o for o in outcomes if o.startswith("fail:")]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0] == "fail:already_redeemed"


def test_redeem_rate_limit(pay_isolated_root, make_user, seed_user):
    # Attempt budget is per-window; invalid guesses count against it.
    alice = seed_user("alice", role="user")
    token = set_current(make_user("u_alice", username="alice"))
    try:
        for _ in range(REDEEM_ATTEMPTS_PER_HOUR):
            try:
                redeem_cdk(code="WRONGCODE1", user_id=alice["id"], username="alice")
            except RedeemFailure:
                pass
        with pytest.raises(RedeemFailure) as exc:
            redeem_cdk(code="WRONGCODE2", user_id=alice["id"], username="alice")
        assert exc.value.reason == "rate_limited"
    finally:
        reset_current(token)


def test_export_json_and_csv(batch):
    batch_id = batch["batch"]["id"]
    json_out = export_batch_codes(batch_id, fmt="json")
    payload = json.loads(json_out)
    assert payload["count"] == 10
    assert set(payload["codes"]) == set(batch["codes"])

    csv_out = export_batch_codes(batch_id, fmt="csv")
    reader = csv_reader(csv_out)
    rows = list(reader)
    assert rows[0] == ["code", "status", "expires_at"]
    assert len(rows) == 11  # header + 10 codes
    assert rows[1][1] == CODE_STATUS_UNUSED


def test_export_unknown_batch(pay_isolated_root):
    with pytest.raises(CDKNotFoundError):
        export_batch_codes("cb_missing", fmt="json")


def test_list_and_lookup_batch(batch):
    batch_id = batch["batch"]["id"]
    all_batches = list_batches()
    assert any(b["id"] == batch_id for b in all_batches)
    detail = lookup_batch(batch_id)
    assert detail["total_codes"] == 10
    assert detail["redeemed_count"] == 0

    codes = list_codes_for_batch(batch_id)
    assert len(codes) == 10
    assert all("digest" in c for c in codes)
    # Raw codes are not exposed through the public listing.
    assert all(c["status"] == CODE_STATUS_UNUSED for c in codes)


def test_redeem_binds_grant_and_books(batch, make_user, seed_user):
    alice = seed_user("alice", role="user")
    code = batch["codes"][0]
    token = set_current(make_user("u_alice", username="alice"))
    try:
        result = redeem_cdk(code=code, user_id=alice["id"], username="alice")
        grant = result["grant"]
        assert grant["models"]["llm"][0]["profile_id"] == "fast"
        assert grant["knowledge_bases"][0]["resource_id"] == "admin:kb:math"
    finally:
        reset_current(token)

    from deeptutor.multi_user.identity import get_user

    record = get_user("alice") or {}
    books = record.get("book_permission", {}).get("books", {})
    assert books.get("bk_math") == "read"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def set_current(user):
    from deeptutor.multi_user.context import set_current_user

    return set_current_user(user)


def reset_current(token):
    from deeptutor.multi_user.context import reset_current_user

    reset_current_user(token)


def csv_reader(text: str):
    import csv as _csv

    return _csv.reader(io.StringIO(text))
