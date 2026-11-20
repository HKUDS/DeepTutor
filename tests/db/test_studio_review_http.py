"""Licence refusal and the review endpoints over the API surface."""

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
from deeptutor.services.studio.script import quality_checklist


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


def _asset(db, owner="u1"):
    queue = JobQueue(db, worker_id="t")
    submitted = _run(
        api.submit_job(
            api.SubmitPayload(kind="mind_map", script="مشتق چیست؟"), user_id=owner
        )
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
                    size_bytes=200,
                    actual_tokens=9,
                ),
            )
        },
        limit=1,
    )
    return S.list_assets(db, user_id=owner)[0]


# ---------------------------------------------------------------------------
# Licence over HTTP
# ---------------------------------------------------------------------------


def test_a_source_without_a_licence_is_a_422(live):
    """422, not 500: the request is malformed for this endpoint's contract."""
    with pytest.raises(HTTPException) as exc:
        _run(
            api.submit_job(
                api.SubmitPayload(kind="mind_map", script="متن", source_id="src_1"),
                user_id="u1",
            )
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["rule"] == "licence_required"


def test_a_source_with_a_licence_is_accepted(live):
    result = _run(
        api.submit_job(
            api.SubmitPayload(
                kind="mind_map", script="متن", source_id="src_1", licence_code="cc-by"
            ),
            user_id="u1",
        )
    )
    assert result["job_id"]


# ---------------------------------------------------------------------------
# Reviews over HTTP
# ---------------------------------------------------------------------------


def test_the_owner_records_a_verdict(live):
    asset = _asset(live)
    item = quality_checklist("mind_map")[0]
    review = _run(
        api.create_review(
            asset["id"],
            api.ReviewPayload(item_id=item["id"], verdict="pass"),
            user_id="u1",
        )
    )
    assert review["verdict"] == "pass"


def test_an_invalid_verdict_is_422(live):
    asset = _asset(live)
    item = quality_checklist("mind_map")[0]
    with pytest.raises(HTTPException) as exc:
        _run(
            api.create_review(
                asset["id"],
                api.ReviewPayload(item_id=item["id"], verdict="excellent"),
                user_id="u1",
            )
        )
    assert exc.value.status_code == 422


def test_a_stranger_cannot_review(live):
    asset = _asset(live)
    item = quality_checklist("mind_map")[0]
    with pytest.raises(HTTPException) as exc:
        _run(
            api.create_review(
                asset["id"],
                api.ReviewPayload(item_id=item["id"], verdict="pass"),
                user_id="u2",
            )
        )
    assert exc.value.status_code == 404


def test_review_status_reports_independence(live):
    asset = _asset(live)
    items = quality_checklist("mind_map")
    for item in items:
        _run(
            api.create_review(
                asset["id"], api.ReviewPayload(item_id=item["id"], verdict="pass"), user_id="u1"
            )
        )

    status = _run(api.get_reviews(asset["id"], user_id="u1"))
    assert status["complete"] is True
    assert status["independently_reviewed"] is False

    _run(
        api.create_review(
            asset["id"],
            api.ReviewPayload(
                item_id=items[0]["id"], verdict="fail", reviewer_id="teacher"
            ),
            user_id="u1",
        )
    )
    status = _run(api.get_reviews(asset["id"], user_id="u1"))
    assert status["independently_reviewed"] is True
    assert status["failures"] == [items[0]["id"]]


def test_review_status_is_owner_only(live):
    asset = _asset(live)
    with pytest.raises(HTTPException) as exc:
        _run(api.get_reviews(asset["id"], user_id="u2"))
    assert exc.value.status_code == 404
