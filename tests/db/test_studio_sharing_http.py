"""Sharing and storage over the API surface."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import studio as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import jobs as S


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    for user in ("u1", "u2", "u3"):
        IdentityRepository(db).save(user, {"id": user, "hash": "x", "role": "user"})
        WalletRepository(db).grant(user, tokens=5000, storage_quota_bytes=10_000_000)
    return db


def _asset(db, owner="u1", script="مشتق چیست؟"):
    queue = JobQueue(db, worker_id="t")
    submitted = _run(
        api.submit_job(api.SubmitPayload(kind="mind_map", script=script), user_id=owner)
    )
    queue.run_once(
        {
            S.job_kind("mind_map"): lambda job: S.run_job(
                db,
                queue=queue,
                job=job,
                renderer=lambda kind, payload: S.RenderResult(
                    storage_path=f"media/{owner}/{payload['content_hash'][:8]}.png",
                    mime_type="image/png",
                    size_bytes=900,
                    actual_tokens=40,
                ),
            )
        },
        limit=1,
    )
    return S.list_assets(db, user_id=owner)[0]


def test_the_owner_shares_and_the_grantee_reads(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))

    assert _run(api.get_asset(asset["id"], user_id="u2"))["id"] == asset["id"]


def test_a_stranger_of_a_shared_asset_still_gets_404(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))

    with pytest.raises(HTTPException) as exc:
        _run(api.get_asset(asset["id"], user_id="u3"))
    assert exc.value.status_code == 404


def test_a_non_owner_cannot_create_a_grant(live):
    asset = _asset(live)
    with pytest.raises(HTTPException) as exc:
        _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u3"))
    assert exc.value.status_code == 404


def test_a_grantee_cannot_delete_through_the_api(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))

    with pytest.raises(HTTPException) as exc:
        _run(api.delete_asset(asset["id"], user_id="u2"))
    assert exc.value.status_code == 404
    assert _run(api.get_asset(asset["id"], user_id="u1"))


def test_revoking_takes_effect_immediately(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))
    _run(api.delete_grant(asset["id"], "u2", user_id="u1"))

    with pytest.raises(HTTPException) as exc:
        _run(api.get_asset(asset["id"], user_id="u2"))
    assert exc.value.status_code == 404


def test_grants_are_listed_for_the_owner_only(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))

    listing = _run(api.list_grants(asset["id"], user_id="u1"))
    assert listing["count"] == 1
    assert listing["grants"][0]["grantee_id"] == "u2"

    with pytest.raises(HTTPException):
        _run(api.list_grants(asset["id"], user_id="u3"))


def test_shared_with_me_is_separate_from_the_library(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))

    shared = _run(api.shared_with_me(user_id="u2"))
    assert shared["count"] == 1

    library = _run(api.list_assets(user_id="u2"))
    assert library["count"] == 0, "a share is not ownership"


def test_the_library_still_reports_owner_only(live):
    asset = _asset(live)
    _run(api.create_grant(asset["id"], api.GrantPayload(grantee_id="u2"), user_id="u1"))

    assert _run(api.list_assets(user_id="u1"))["count"] == 1
    assert _run(api.list_assets(user_id="u2"))["count"] == 0


def test_quota_reports_storage_after_a_render(live):
    _asset(live)
    quota = _run(api.quota(user_id="u1"))
    assert quota["storage_used_bytes"] == 900
    assert quota["storage_quota_bytes"] == 10_000_000


def test_admin_asset_view_totals_real_bytes(live):
    _asset(live)
    view = _run(api.admin_assets())
    assert view["total_bytes"] >= 900
