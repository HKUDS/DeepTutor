"""Entitlement over the real HTTP surface.

The unit tests prove the resolver decides correctly. These prove the decision is
actually reached from a request: before Phase 9 `submit` accepted a
`require_entitlement` callable and no caller supplied one, so every one of these
would have returned 202 for any account, including one with no plan at all.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import studio as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services import entitlements as E


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u1", tokens=500_000)
    return db


def _submit(kind="mind_map", script="متن درس"):
    return _run(api.submit_job(api.SubmitPayload(kind=kind, script=script), user_id="u1"))


def _plan(db, code="pro", capabilities="studio,media.video,media.audio", days=30):
    now = datetime.now(timezone.utc)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO plans (code, name, price_toman, token_quota, duration_days, "
            "is_active, sort_order, storage_quota_bytes, updated_at, capabilities) "
            "VALUES (?, ?, 0, 100000, ?, 1, 1, 104857600, ?, ?)",
            (code, code, days, now.isoformat(), capabilities),
        )


def _expire(db, user_id="u1"):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_wallets SET plan_expires_at = ? WHERE user_id = ?", (past, user_id)
        )


# ---------------------------------------------------------------------------
# The hole that is now closed
# ---------------------------------------------------------------------------


def test_video_without_a_plan_is_refused(live):
    """Before this pass it returned 202 and reserved tokens."""
    with pytest.raises(HTTPException) as exc:
        _submit("video_lesson")
    assert exc.value.status_code == 403
    assert exc.value.detail["rule"] == "not_entitled"


def test_audio_without_a_plan_is_refused(live):
    with pytest.raises(HTTPException) as exc:
        _submit("audio_overview")
    assert exc.value.status_code == 403


def test_an_image_kind_needs_only_the_base_surface(live):
    """Refusing everything would be closed, but not useful."""
    assert _submit("mind_map")["job_id"]
    assert _submit("infographic", "متن دیگر")["job_id"]


# ---------------------------------------------------------------------------
# A plan grants what it says
# ---------------------------------------------------------------------------


def test_a_plan_with_video_permits_video(live):
    _plan(live)
    E.grant_plan(live, user_id="u1", plan_code="pro")
    assert _submit("video_lesson")["job_id"]


def test_a_plan_without_video_still_refuses_video(live):
    """Paying is not the same as being entitled to a specific surface."""
    _plan(live, code="audio-only", capabilities="studio,media.audio")
    E.grant_plan(live, user_id="u1", plan_code="audio-only")
    assert _submit("audio_overview")["job_id"]
    with pytest.raises(HTTPException) as exc:
        _submit("video_lesson", "متن ویدیو")
    assert exc.value.status_code == 403


def test_a_refusal_reserves_nothing(live):
    """A 403 after the reserve would leave a hold nothing releases."""
    from deeptutor.services.studio import accounting

    before = accounting.open_holds(live, "u1")
    with pytest.raises(HTTPException):
        _submit("video_lesson")
    assert accounting.open_holds(live, "u1") == before == 0


# ---------------------------------------------------------------------------
# Expiry over HTTP
# ---------------------------------------------------------------------------


def test_an_expired_plan_loses_the_paid_surface(live):
    """The concrete claim: a lapsed subscription is not a licence to keep going."""
    _plan(live)
    E.grant_plan(live, user_id="u1", plan_code="pro")
    assert _submit("video_lesson")["job_id"]

    _expire(live)
    with pytest.raises(HTTPException) as exc:
        _submit("video_lesson", "متن پس از انقضا")
    assert exc.value.status_code == 403


def test_an_expired_plan_keeps_the_base_surface(live):
    _plan(live)
    E.grant_plan(live, user_id="u1", plan_code="pro")
    _expire(live)
    assert _submit("mind_map", "متن پس از انقضا")["job_id"]


def test_renewing_restores_the_paid_surface(live):
    _plan(live)
    E.grant_plan(live, user_id="u1", plan_code="pro")
    _expire(live)
    with pytest.raises(HTTPException):
        _submit("video_lesson", "x")
    E.grant_plan(live, user_id="u1", plan_code="pro")
    assert _submit("video_lesson", "y")["job_id"]


# ---------------------------------------------------------------------------
# The decision is on the record
# ---------------------------------------------------------------------------


def test_an_allowed_request_leaves_a_decision(live):
    _plan(live)
    E.grant_plan(live, user_id="u1", plan_code="pro")
    _submit("video_lesson")
    with live.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM entitlement_decisions WHERE user_id = 'u1' "
                "AND capability = ? ORDER BY decided_at",
                (E.CAP_MEDIA_VIDEO,),
            )
        )
    assert rows
    assert int(rows[-1]["allowed"]) == 1
    assert rows[-1]["reason"] == "active"


def test_a_refused_request_leaves_a_decision(live):
    with pytest.raises(HTTPException):
        _submit("video_lesson")
    with live.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM entitlement_decisions WHERE user_id = 'u1' ORDER BY decided_at"
            )
        )
    assert rows
    assert int(rows[-1]["allowed"]) == 0
    assert rows[-1]["reason"] == "missing_plan"
