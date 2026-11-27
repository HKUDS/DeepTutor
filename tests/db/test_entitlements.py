"""Entitlement is closed by default, and expiry is evaluated rather than stored.

The gap these tests close: before Phase 9, `plans` existed and nothing read it,
`plan_expires_at` was written and never checked, and `require_entitlement` was a
parameter no caller supplied. An account whose plan expired ninety days ago had
exactly the access of one that paid this morning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services import entitlements as E

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def _user(db, user_id="u1", tokens=1000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=tokens)


def _plan(db, code="pro", *, capabilities="studio,media.video,media.audio",
          days=30, active=1, tokens=500_000):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO plans (code, name, price_toman, token_quota, duration_days, "
            "is_active, sort_order, storage_quota_bytes, updated_at, capabilities) "
            "VALUES (?, ?, 100000, ?, ?, ?, 1, 104857600, ?, ?)",
            (code, code, tokens, days, active, NOW.isoformat(), capabilities),
        )


# ---------------------------------------------------------------------------
# Closed by default -- the rule that was missing
# ---------------------------------------------------------------------------


def test_an_account_with_no_wallet_gets_the_base_tier(db):
    result = E.resolve(db, "nobody", now=NOW)
    assert result.reason == "no_wallet"
    assert result.capabilities == E.BASE_CAPABILITIES


def test_an_account_with_a_wallet_and_no_plan_gets_the_base_tier(db):
    _user(db)
    result = E.resolve(db, "u1", now=NOW)
    assert result.reason == "missing_plan"
    assert E.CAP_MEDIA_VIDEO not in result.capabilities


def test_no_plan_means_no_video(db):
    """The concrete hole: video was available to everyone."""
    _user(db)
    assert E.allows(db, "u1", E.CAP_MEDIA_VIDEO, now=NOW) is False


def test_a_plan_code_that_does_not_exist_grants_only_the_base_tier(db):
    """A free string on the wallet must not be believed."""
    _user(db)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_wallets SET plan_code = 'made-up', "
            "plan_expires_at = ? WHERE user_id = ?",
            ((NOW + timedelta(days=30)).isoformat(), "u1"),
        )
    result = E.resolve(db, "u1", now=NOW)
    assert result.reason == "unknown_plan"
    assert E.CAP_MEDIA_VIDEO not in result.capabilities


# ---------------------------------------------------------------------------
# An active plan grants what it says, and nothing else
# ---------------------------------------------------------------------------


def test_an_active_plan_grants_its_capabilities(db):
    _user(db)
    _plan(db)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    result = E.resolve(db, "u1", now=NOW)
    assert result.reason == "active"
    assert result.is_paid
    assert E.CAP_MEDIA_VIDEO in result.capabilities


def test_a_plan_grants_only_what_it_lists(db):
    """A plan without video must not grant video just because it is paid."""
    _user(db)
    _plan(db, code="basic", capabilities="studio,media.audio")
    E.grant_plan(db, user_id="u1", plan_code="basic", now=NOW)
    result = E.resolve(db, "u1", now=NOW)
    assert E.CAP_MEDIA_AUDIO in result.capabilities
    assert E.CAP_MEDIA_VIDEO not in result.capabilities


def test_the_base_surface_survives_buying_a_plan(db):
    """A plan that omits `studio` must not take it away."""
    _user(db)
    _plan(db, code="odd", capabilities="media.video")
    E.grant_plan(db, user_id="u1", plan_code="odd", now=NOW)
    assert E.CAP_STUDIO in E.resolve(db, "u1", now=NOW).capabilities


def test_an_unknown_capability_name_grants_nothing(db):
    """A typo must fail closed, not open."""
    _user(db)
    _plan(db, code="typo", capabilities="studio,media.videoo,everything")
    E.grant_plan(db, user_id="u1", plan_code="typo", now=NOW)
    result = E.resolve(db, "u1", now=NOW)
    assert "everything" not in result.capabilities
    assert "media.videoo" not in result.capabilities
    assert result.capabilities == E.BASE_CAPABILITIES


# ---------------------------------------------------------------------------
# Expiry is evaluated at read time
# ---------------------------------------------------------------------------


def test_a_plan_expires_when_its_date_passes(db):
    _user(db)
    _plan(db, days=30)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    assert E.resolve(db, "u1", now=NOW + timedelta(days=29)).reason == "active"
    assert E.resolve(db, "u1", now=NOW + timedelta(days=31)).reason == "expired"


def test_expiry_is_evaluated_not_stored(db):
    """The row still says the plan's name; only the clock decides."""
    _user(db)
    _plan(db, days=30)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    later = E.resolve(db, "u1", now=NOW + timedelta(days=400))
    assert later.reason == "expired"
    assert later.plan_code == "pro", "the plan is recorded, it is just not in force"


def test_an_expired_plan_stops_granting_its_capabilities(db):
    """The whole point: an expired plan must lose video."""
    _user(db)
    _plan(db, days=30)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    assert E.allows(db, "u1", E.CAP_MEDIA_VIDEO, now=NOW) is True
    assert E.allows(db, "u1", E.CAP_MEDIA_VIDEO, now=NOW + timedelta(days=31)) is False


def test_expired_means_base_tier_not_zero_access(db):
    """We withdrew the paid surface, not the account's access to the product."""
    _user(db)
    _plan(db, days=1)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    expired = E.resolve(db, "u1", now=NOW + timedelta(days=2))
    assert expired.capabilities == E.BASE_CAPABILITIES
    assert E.CAP_STUDIO in expired.capabilities


def test_a_wallet_with_no_expiry_does_not_grant_a_plan(db):
    """Half-written state must fail closed."""
    _user(db)
    _plan(db)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_wallets SET plan_code = 'pro', plan_expires_at = NULL WHERE user_id = ?",
            ("u1",),
        )
    result = E.resolve(db, "u1", now=NOW)
    assert result.reason == "no_expiry"
    assert E.CAP_MEDIA_VIDEO not in result.capabilities


def test_an_retired_plan_stops_granting(db):
    _user(db)
    _plan(db, code="legacy", active=1)
    E.grant_plan(db, user_id="u1", plan_code="legacy", now=NOW)
    with db.transaction() as conn:
        conn.execute("UPDATE plans SET is_active = 0 WHERE code = 'legacy'")
    result = E.resolve(db, "u1", now=NOW)
    assert result.reason == "plan_retired"
    assert E.CAP_MEDIA_VIDEO not in result.capabilities


def test_a_malformed_expiry_fails_closed(db):
    _user(db)
    _plan(db)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_wallets SET plan_code = 'pro', plan_expires_at = 'not-a-date' "
            "WHERE user_id = ?",
            ("u1",),
        )
    assert E.resolve(db, "u1", now=NOW).reason == "no_expiry"


# ---------------------------------------------------------------------------
# Granting
# ---------------------------------------------------------------------------


def test_renewing_early_extends_rather_than_truncates(db):
    """A user who pays before expiry must not lose the days they already paid."""
    _user(db)
    _plan(db, days=30)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    first = E.resolve(db, "u1", now=NOW).expires_at
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW + timedelta(days=10))
    second = E.resolve(db, "u1", now=NOW + timedelta(days=10)).expires_at
    assert second > first
    assert (second - first).days == 30


def test_renewing_after_expiry_starts_fresh_from_now(db):
    """Adding to a past date would leave a paying user expired."""
    _user(db)
    _plan(db, days=30)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    later = NOW + timedelta(days=100)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=later, extend=True)
    result = E.resolve(db, "u1", now=later)
    assert result.reason == "active"
    assert result.expires_at > later


def test_granting_an_unknown_plan_raises(db):
    _user(db)
    from deeptutor.services.studio.jobs import StudioError

    with pytest.raises(StudioError) as exc:
        E.grant_plan(db, user_id="u1", plan_code="nope", now=NOW)
    assert exc.value.rule == "unknown_plan"


def test_granting_a_retired_plan_raises(db):
    _user(db)
    _plan(db, code="gone", active=0)
    from deeptutor.services.studio.jobs import StudioError

    with pytest.raises(StudioError) as exc:
        E.grant_plan(db, user_id="u1", plan_code="gone", now=NOW)
    assert exc.value.rule == "plan_retired"


# ---------------------------------------------------------------------------
# The kind-to-capability mapping
# ---------------------------------------------------------------------------


def test_video_needs_the_video_capability(db):
    assert E.capability_for_kind("video_lesson") == E.CAP_MEDIA_VIDEO


def test_audio_needs_the_audio_capability(db):
    assert E.capability_for_kind("audio_overview") == E.CAP_MEDIA_AUDIO


def test_image_kinds_need_only_the_base_surface(db):
    for kind in ("mind_map", "infographic", "slide_deck"):
        assert E.capability_for_kind(kind) == E.CAP_STUDIO


def test_an_unknown_kind_needs_the_base_surface(db):
    """Unknown kinds must not fall into a paid bucket by accident."""
    assert E.capability_for_kind("something_new") == E.CAP_STUDIO


# ---------------------------------------------------------------------------
# The decision record
# ---------------------------------------------------------------------------


def _decisions(db, user_id="u1"):
    with db.read() as conn:
        return list(
            conn.query(
                "SELECT * FROM entitlement_decisions WHERE user_id = ? "
                "ORDER BY decided_at",
                (user_id,),
            )
        )


def test_the_gate_records_its_decision(db):
    _user(db)
    _plan(db)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    gate = E.studio_gate(db)
    assert gate("u1", "video_lesson") is True
    rows = _decisions(db)
    assert rows and int(rows[-1]["allowed"]) == 1
    assert rows[-1]["capability"] == E.CAP_MEDIA_VIDEO


def test_a_refusal_is_recorded_too(db):
    """'Why was this blocked' needs an answer as much as 'why allowed'."""
    _user(db)
    gate = E.studio_gate(db)
    assert gate("u1", "video_lesson") is False
    rows = _decisions(db)
    assert rows and int(rows[-1]["allowed"]) == 0
    assert rows[-1]["reason"] == "missing_plan"


def test_the_record_survives_the_plan_changing(db):
    _user(db)
    _plan(db)
    E.grant_plan(db, user_id="u1", plan_code="pro", now=NOW)
    E.studio_gate(db)("u1", "video_lesson")
    with db.transaction() as conn:
        conn.execute("UPDATE plans SET capabilities = 'studio' WHERE code = 'pro'")
    rows = _decisions(db)
    assert rows[-1]["plan_code"] == "pro"
    assert int(rows[-1]["allowed"]) == 1, (
        "the decision was taken when video was included; rewriting the plan "
        "must not retroactively change what happened"
    )


def test_allows_without_record_writes_nothing(db):
    _user(db)
    E.allows(db, "u1", E.CAP_MEDIA_VIDEO)
    assert _decisions(db) == []


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_list_plans_returns_only_active_by_default(db):
    _plan(db, code="a", active=1)
    _plan(db, code="b", active=0)
    codes = [plan.code for plan in E.list_plans(db)]
    assert "a" in codes
    assert "b" not in codes


def test_list_plans_can_include_retired_ones(db):
    _plan(db, code="old", active=0)
    assert "old" in [p.code for p in E.list_plans(db, include_inactive=True)]
