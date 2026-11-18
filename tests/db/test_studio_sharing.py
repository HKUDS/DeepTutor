"""Sharing: the "or someone authorized" half of the access rule.

Phase 8 shipped owner-only access. These tests cover the second route, and the
rules exist mostly to stop a share from quietly becoming a redistribution.
"""

from __future__ import annotations

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import jobs as S


def _user(db, user_id):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=5000)
    return user_id


def _asset(db, owner="u1"):
    _user(db, owner)
    queue = JobQueue(db, worker_id="t")
    out = S.submit(
        db, queue=queue, request=S.JobRequest(user_id=owner, kind="mind_map", script="مشتق چیست؟")
    )

    def render(kind, payload):
        return S.RenderResult(
            storage_path=f"media/{owner}/{payload['content_hash'][:8]}.png",
            mime_type="image/png",
            size_bytes=120,
            actual_tokens=50,
        )

    queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=render)},
        limit=1,
    )
    return S.list_assets(db, user_id=owner)[0]


def _can_read(db, asset_id, user):
    try:
        S.get_asset(db, asset_id, user_id=user)
    except S.StudioError:
        return False
    return True


# ---------------------------------------------------------------------------
# The basic second route
# ---------------------------------------------------------------------------


def test_a_stranger_cannot_read_before_a_grant(db):
    asset = _asset(db)
    _user(db, "u2")
    assert _can_read(db, asset["id"], "u2") is False


def test_a_grantee_can_read(db):
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")
    assert _can_read(db, asset["id"], "u2") is True


def test_a_grant_does_not_transfer_ownership(db):
    """The library is still the owner's; the grantee sees it under shares."""
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")

    assert S.list_assets(db, user_id="u2") == []
    assert [a["id"] for a in S.list_shared_with_me(db, user_id="u2")] == [asset["id"]]


def test_a_grantee_cannot_delete_the_asset(db):
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")

    with pytest.raises(S.StudioError):
        S.delete_asset(db, asset["id"], user_id="u2")


# ---------------------------------------------------------------------------
# Rules that stop a share becoming a redistribution
# ---------------------------------------------------------------------------


def test_a_recipient_cannot_re_share(db):
    """A share is not a copy of the owner's authority."""
    asset = _asset(db)
    _user(db, "u2")
    _user(db, "u3")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")

    with pytest.raises(S.StudioError) as exc:
        S.grant_access(db, asset_id=asset["id"], owner_id="u2", grantee_id="u3")
    assert exc.value.rule == "asset_not_found"
    assert _can_read(db, asset["id"], "u3") is False


def test_the_owner_cannot_grant_to_itself(db):
    asset = _asset(db)
    with pytest.raises(S.StudioError) as exc:
        S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u1")
    assert exc.value.rule == "self_grant"


def test_only_the_owner_can_revoke(db):
    asset = _asset(db)
    _user(db, "u2")
    _user(db, "u3")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u3")

    with pytest.raises(S.StudioError):
        S.revoke_access(db, asset_id=asset["id"], owner_id="u2", grantee_id="u3")
    assert _can_read(db, asset["id"], "u3") is True


# ---------------------------------------------------------------------------
# Expiry and revocation
# ---------------------------------------------------------------------------


def test_an_expired_grant_closes_without_a_cleanup_job(db):
    """Expiry is checked at read time, so nothing has to sweep the table."""
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(
        db, asset_id=asset["id"], owner_id="u1", grantee_id="u2",
        expires_at="2000-01-01T00:00:00+00:00",
    )
    assert _can_read(db, asset["id"], "u2") is False


def test_a_future_grant_is_live(db):
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(
        db, asset_id=asset["id"], owner_id="u1", grantee_id="u2",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    assert _can_read(db, asset["id"], "u2") is True


def test_revocation_takes_access_away(db):
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")

    assert S.revoke_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2") is True
    assert _can_read(db, asset["id"], "u2") is False
    assert S.list_shared_with_me(db, user_id="u2") == []


def test_revocation_keeps_the_history(db):
    """A deleted grant cannot answer "did this person ever have access"."""
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")
    S.revoke_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")

    rows = S.list_grants(db, asset_id=asset["id"], owner_id="u1")
    assert len(rows) == 1
    assert rows[0]["revoked_at"] is not None


def test_re_granting_revives_one_row_rather_than_adding_another(db):
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")
    S.revoke_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")

    rows = S.list_grants(db, asset_id=asset["id"], owner_id="u1")
    assert len(rows) == 1, "re-granting must not fork the row"
    assert rows[0]["revoked_at"] is None
    assert _can_read(db, asset["id"], "u2") is True


def test_a_grant_cannot_be_moved_to_another_asset(db):
    first = _asset(db)
    queue = JobQueue(db, worker_id="t")
    S.submit(
        db, queue=queue,
        request=S.JobRequest(user_id="u1", kind="mind_map", script="حد چیست؟"),
    )

    def render(kind, payload):
        return S.RenderResult(
            storage_path=f"media/x/{payload['content_hash'][:8]}.png",
            mime_type="image/png",
            size_bytes=90,
            actual_tokens=40,
        )

    queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=render)},
        limit=1,
    )
    second = [a for a in S.list_assets(db, user_id="u1") if a["id"] != first["id"]][0]
    _user(db, "u2")
    S.grant_access(db, asset_id=first["id"], owner_id="u1", grantee_id="u2")

    assert _can_read(db, second["id"], "u2") is False, "a grant is per asset"
