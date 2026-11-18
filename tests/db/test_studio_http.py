"""The studio API: authorization, status codes and the download guard.

The single most important assertion in this file is that an asset's bytes are
readable only by its owner. Everything else is about telling a client the right
thing (402 vs 403 vs 404) so it can send the user to the right screen.
"""

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
    for user in ("u1", "u2"):
        IdentityRepository(db).save(user, {"id": user, "hash": "x", "role": "user"})
        WalletRepository(db).grant(user, tokens=5000)
    return db


def _submit(user="u1", **kwargs):
    payload = dict(
        kind="mind_map", script="مشتق چیست؟", title="نقشه", source_id=None,
        chapter_title="", licence_code="", render={},
    )
    payload.update(kwargs)
    return _run(api.submit_job(api.SubmitPayload(**payload), user_id=user))


def _asset_for(db, user="u1"):
    """Submit and run a job, returning its asset."""
    submitted = _submit(user)
    queue = JobQueue(db, worker_id="test")
    renderer = lambda kind, payload: S.RenderResult(  # noqa: E731
        storage_path=f"media/{payload['content_hash'][:8]}.json",
        mime_type="application/json",
        size_bytes=2,
        actual_tokens=100,
    )
    queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=renderer)},
        limit=1,
    )
    return S.list_assets(db, user_id=user)[0]


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def test_submitting_returns_accepted_with_a_hold(live):
    result = _submit()
    assert result["cached"] is False
    assert result["job_id"]
    assert result["reserved_tokens"] > 0


def test_a_poor_user_gets_402(live):
    IdentityRepository(live).save("poor", {"id": "poor", "hash": "x", "role": "user"})
    WalletRepository(live).grant("poor", tokens=1)
    with pytest.raises(HTTPException) as exc:
        _submit(user="poor")
    assert exc.value.status_code == 402
    assert exc.value.detail["rule"] == "insufficient_quota"


def test_an_unknown_kind_is_422(live):
    with pytest.raises(HTTPException) as exc:
        _submit(kind="hologram")
    assert exc.value.status_code == 422
    assert exc.value.detail["rule"] == "unknown_kind"


def test_an_empty_script_is_422(live):
    with pytest.raises(HTTPException) as exc:
        _submit(script="  ")
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Asset ownership -- the decisive rule
# ---------------------------------------------------------------------------


def test_an_asset_can_be_read_by_its_owner(live):
    asset = _asset_for(live, "u1")
    got = _run(api.get_asset(asset["id"], user_id="u1"))
    assert got["id"] == asset["id"]


def test_an_asset_is_not_found_for_anyone_else(live):
    """404, not 403: an opaque id must not confirm that it exists."""
    asset = _asset_for(live, "u1")
    with pytest.raises(HTTPException) as exc:
        _run(api.get_asset(asset["id"], user_id="u2"))
    assert exc.value.status_code == 404
    assert exc.value.detail["rule"] == "asset_not_found"


def test_asset_bytes_are_owner_only(live):
    asset = _asset_for(live, "u1")
    with pytest.raises(HTTPException) as exc:
        _run(api.asset_content(asset["id"], user_id="u2"))
    assert exc.value.status_code == 404


def test_asset_bytes_are_served_to_the_owner(live, tmp_path, monkeypatch):
    """The positive half: the owner's request reaches the store."""
    asset = _asset_for(live, "u1")
    blob = tmp_path / "asset.json"
    blob.write_text('{"ok": true}')

    class Store:
        def open_path(self, key):
            return blob

    monkeypatch.setattr("deeptutor.db.storage.get_object_store", lambda: Store())
    response = _run(api.asset_content(asset["id"], user_id="u1"))
    assert str(response.path) == str(blob)


def test_deleting_someone_elses_asset_is_not_found(live):
    asset = _asset_for(live, "u1")
    with pytest.raises(HTTPException) as exc:
        _run(api.delete_asset(asset["id"], user_id="u2"))
    assert exc.value.status_code == 404
    assert len(S.list_assets(live, user_id="u1")) == 1


def test_a_deleted_asset_disappears_from_the_library(live):
    asset = _asset_for(live, "u1")
    _run(api.delete_asset(asset["id"], user_id="u1"))
    assert S.list_assets(live, user_id="u1") == []
    with pytest.raises(HTTPException) as exc:
        _run(api.get_asset(asset["id"], user_id="u1"))
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def test_another_users_job_is_not_found(live):
    submitted = _submit("u1")
    with pytest.raises(HTTPException) as exc:
        _run(api.get_job(submitted["job_id"], user_id="u2"))
    assert exc.value.status_code == 404


def test_cancelling_refunds_and_is_visible_in_the_job(live):
    submitted = _submit()
    result = _run(api.cancel_job(submitted["job_id"], user_id="u1"))
    assert result["cancelled"] is True and result["refunded"] is True

    job = _run(api.get_job(submitted["job_id"], user_id="u1"))
    assert job["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


def test_quota_reports_held_tokens_separately_from_the_balance(live):
    _submit()
    quota = _run(api.quota(user_id="u1"))

    assert quota["tokens_remaining"] == 5000, "a hold is not a charge"
    assert quota["tokens_held"] > 0
    assert quota["tokens_available"] == 5000 - quota["tokens_held"]


# ---------------------------------------------------------------------------
# Operator surface
# ---------------------------------------------------------------------------


def test_the_admin_queue_view_counts_media_jobs(live):
    _submit()
    view = _run(api.queue_health())
    assert view["open_holds_tokens"] > 0
    assert any(row["kind"] == "media.mind_map" for row in view["by_kind"])


def test_the_admin_asset_view_is_metadata_only(live):
    """An operator sees sizes and owners, not the lessons themselves."""
    asset = _asset_for(live, "u1")
    view = _run(api.admin_assets())
    row = next(r for r in view["assets"] if r["id"] == asset["id"])
    assert "storage_path" not in row
    assert "script" not in row
    assert row["user_id"] == "u1"
