"""Licence enforcement, real deletion, and the recorded human review.

The three things that turned out to be missing once the mechanism was done.
Each one is a case where a feature *looked* finished and was not:

- a licence field that could be empty and therefore guaranteed nothing;
- a delete that freed the meter but left the file occupying the disk;
- a checklist nobody could fill in, so "quality assessed" was only ever
  "criteria written down".
"""

from __future__ import annotations

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.db.storage import get_object_store
from deeptutor.services.studio import jobs as S
from deeptutor.services.studio.script import quality_checklist


def _user(db, user_id="u1", tokens=5000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=tokens)
    return user_id


def _asset(db, owner="u1", *, source_id=None, licence_code="", script="مشتق چیست؟"):
    _user(db, owner)
    queue = JobQueue(db, worker_id="t")
    submitted = S.submit(
        db,
        queue=queue,
        request=S.JobRequest(
            user_id=owner,
            kind="mind_map",
            script=script,
            source_id=source_id,
            licence_code=licence_code,
        ),
    )
    store = get_object_store()

    def render(kind, payload):
        key = store.put(b"PNGDATA" * 50, namespace="media", key=f"{payload['content_hash'][:8]}.png")
        return S.RenderResult(
            storage_path=key, mime_type="image/png", size_bytes=350, actual_tokens=10
        )

    queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=render)},
        limit=1,
    )
    return S.list_assets(db, user_id=owner)[0]


# ---------------------------------------------------------------------------
# 1. A licence that is not required is not a licence
# ---------------------------------------------------------------------------


def test_content_from_a_source_without_a_licence_is_refused(db):
    """The provenance row would say where it came from and nothing about terms."""
    _user(db)
    queue = JobQueue(db, worker_id="t")
    with pytest.raises(S.StudioError) as exc:
        S.submit(
            db,
            queue=queue,
            request=S.JobRequest(
                user_id="u1", kind="mind_map", script="متن منبع", source_id="src_9", licence_code=""
            ),
        )
    assert exc.value.rule == "licence_required"


def test_a_blank_licence_is_not_a_licence(db):
    """Whitespace is the emptiest possible way to satisfy a required field."""
    _user(db)
    queue = JobQueue(db, worker_id="t")
    with pytest.raises(S.StudioError) as exc:
        S.submit(
            db,
            queue=queue,
            request=S.JobRequest(
                user_id="u1", kind="mind_map", script="x", source_id="src_1", licence_code="   "
            ),
        )
    assert exc.value.rule == "licence_required"


def test_the_refusal_happens_before_any_hold_or_job(db):
    """A rejected submit must leave nothing behind -- no money, no queue entry."""
    _user(db)
    queue = JobQueue(db, worker_id="t")
    with pytest.raises(S.StudioError):
        S.submit(
            db,
            queue=queue,
            request=S.JobRequest(user_id="u1", kind="mind_map", script="x", source_id="s"),
        )
    with db.read() as conn:
        holds = conn.scalar("SELECT COUNT(*) FROM media_reservations")
        jobs = conn.scalar("SELECT COUNT(*) FROM jobs")
    assert int(holds) == 0 and int(jobs) == 0


def test_content_from_a_source_with_a_licence_is_accepted(db):
    _user(db)
    queue = JobQueue(db, worker_id="t")
    result = S.submit(
        db,
        queue=queue,
        request=S.JobRequest(
            user_id="u1", kind="mind_map", script="متن", source_id="src_1", licence_code="cc-by"
        ),
    )
    assert result["job_id"]


def test_a_prompt_with_no_source_needs_no_licence(db):
    """There is nothing to licence when nothing was used."""
    _user(db)
    queue = JobQueue(db, worker_id="t")
    result = S.submit(
        db, queue=queue, request=S.JobRequest(user_id="u1", kind="mind_map", script="متن من")
    )
    assert result["job_id"]


def test_the_licence_travels_to_the_asset(db):
    asset = _asset(db, source_id="src_1", licence_code="cc-by")
    assert asset["source_id"] == "src_1"
    assert asset["licence_code"] == "cc-by"


# ---------------------------------------------------------------------------
# 2. Deleting must free the disk, not just the counter
# ---------------------------------------------------------------------------


def test_deleting_removes_the_bytes_from_storage(db):
    """A delete that frees the meter and leaves the file is a slow disk leak."""
    asset = _asset(db)
    store = get_object_store()
    assert store.exists(asset["storage_path"]) is True

    S.delete_asset(db, asset["id"], user_id="u1")

    assert store.exists(asset["storage_path"]) is False


def test_deleting_still_releases_the_storage_meter(db):
    asset = _asset(db)
    assert WalletRepository(db).get("u1")["storage_used_bytes"] == 350

    S.delete_asset(db, asset["id"], user_id="u1")

    assert WalletRepository(db).get("u1")["storage_used_bytes"] == 0


def test_a_deleted_asset_is_gone_from_the_library_and_the_api(db):
    asset = _asset(db)
    S.delete_asset(db, asset["id"], user_id="u1")

    assert S.list_assets(db, user_id="u1") == []
    with pytest.raises(S.StudioError):
        S.get_asset(db, asset["id"], user_id="u1")


def test_deletion_revokes_a_grantee_implicitly(db):
    """A grantee loses access the moment the owner deletes, with no extra step."""
    asset = _asset(db)
    _user(db, "u2")
    S.grant_access(db, asset_id=asset["id"], owner_id="u1", grantee_id="u2")
    assert S.get_asset(db, asset["id"], user_id="u2")

    S.delete_asset(db, asset["id"], user_id="u1")

    with pytest.raises(S.StudioError):
        S.get_asset(db, asset["id"], user_id="u2")
    assert S.list_shared_with_me(db, user_id="u2") == []


def test_a_non_owner_still_cannot_delete(db):
    asset = _asset(db)
    _user(db, "u2")
    with pytest.raises(S.StudioError):
        S.delete_asset(db, asset["id"], user_id="u2")
    assert get_object_store().exists(asset["storage_path"]) is True


def test_deleting_an_asset_whose_object_is_already_gone_still_fixes_the_meter(db):
    """A previous partial delete must not leave the meter permanently wrong."""
    asset = _asset(db)
    get_object_store().delete(asset["storage_path"])

    S.delete_asset(db, asset["id"], user_id="u1")

    assert WalletRepository(db).get("u1")["storage_used_bytes"] == 0


# ---------------------------------------------------------------------------
# 3. The human review has somewhere to live
# ---------------------------------------------------------------------------


def test_a_reviewer_can_record_a_verdict(db):
    asset = _asset(db)
    item = quality_checklist("mind_map")[0]

    review = S.record_review(
        db, asset_id=asset["id"], user_id="u1", item_id=item["id"], verdict="pass"
    )
    assert review["verdict"] == "pass"
    assert review["reviewer_id"] == "u1"


def test_an_invalid_verdict_is_refused(db):
    """Three values, because "I could not decide" is a real outcome."""
    asset = _asset(db)
    item = quality_checklist("mind_map")[0]
    with pytest.raises(S.StudioError) as exc:
        S.record_review(
            db, asset_id=asset["id"], user_id="u1", item_id=item["id"], verdict="maybe"
        )
    assert exc.value.rule == "invalid_verdict"


def test_an_item_from_another_kind_is_refused(db):
    """A mind-map review must not accept an audio-overview question."""
    asset = _asset(db)
    audio_item = quality_checklist("audio_overview")[-1]
    with pytest.raises(S.StudioError) as exc:
        S.record_review(
            db, asset_id=asset["id"], user_id="u1", item_id=audio_item["id"], verdict="pass"
        )
    assert exc.value.rule == "unknown_checklist_item"


def test_reviewing_someone_elses_asset_is_refused(db):
    asset = _asset(db)
    _user(db, "u2")
    item = quality_checklist("mind_map")[0]
    with pytest.raises(S.StudioError):
        S.record_review(db, asset_id=asset["id"], user_id="u2", item_id=item["id"], verdict="pass")


def test_a_complete_self_review_is_complete_but_not_independent(db):
    """The distinction a report must not lose."""
    asset = _asset(db)
    for item in quality_checklist("mind_map"):
        S.record_review(
            db, asset_id=asset["id"], user_id="u1", item_id=item["id"], verdict="pass"
        )

    status = S.review_status(db, asset["id"], user_id="u1")

    assert status["complete"] is True
    assert status["independently_reviewed"] is False
    assert status["independent_reviews"] == 0


def test_a_second_reviewer_makes_the_evidence_independent(db):
    asset = _asset(db)
    _user(db, "teacher")
    items = quality_checklist("mind_map")
    S.record_review(db, asset_id=asset["id"], user_id="u1", item_id=items[0]["id"], verdict="pass")
    S.record_review(
        db,
        asset_id=asset["id"],
        user_id="u1",
        item_id=items[0]["id"],
        verdict="fail",
        comment="ماشینی است",
        reviewer_id="teacher",
    )

    status = S.review_status(db, asset["id"], user_id="u1")

    assert status["independently_reviewed"] is True
    assert status["independent_reviews"] == 1
    assert status["failures"] == [items[0]["id"]]
    verdicts = status["items"][0]["verdicts"]
    assert {v["verdict"] for v in verdicts} == {"pass", "fail"}
    assert [v["independent"] for v in verdicts].count(True) == 1


def test_changing_a_verdict_updates_rather_than_doubling(db):
    """Two rows for one reviewer would make the count meaningless."""
    asset = _asset(db)
    item = quality_checklist("mind_map")[0]
    S.record_review(db, asset_id=asset["id"], user_id="u1", item_id=item["id"], verdict="pass")
    S.record_review(db, asset_id=asset["id"], user_id="u1", item_id=item["id"], verdict="fail")

    status = S.review_status(db, asset["id"], user_id="u1")
    assert len(status["items"][0]["verdicts"]) == 1
    assert status["items"][0]["verdicts"][0]["verdict"] == "fail"


def test_an_unanswered_item_is_visible_as_unanswered(db):
    asset = _asset(db)
    items = quality_checklist("mind_map")
    S.record_review(db, asset_id=asset["id"], user_id="u1", item_id=items[0]["id"], verdict="pass")

    status = S.review_status(db, asset["id"], user_id="u1")
    assert status["answered_items"] == 1
    assert status["complete"] is False
    assert status["total_items"] == len(items)


def test_unclear_is_recorded_separately_from_fail(db):
    asset = _asset(db)
    item = quality_checklist("mind_map")[0]
    S.record_review(
        db, asset_id=asset["id"], user_id="u1", item_id=item["id"], verdict="unclear"
    )
    status = S.review_status(db, asset["id"], user_id="u1")
    assert status["unclear"] == [item["id"]]
    assert status["failures"] == []


# ---------------------------------------------------------------------------
# The guarantee is in the table, not only in the service
# ---------------------------------------------------------------------------


def _raw_insert(db, *, source_id, licence_code, asset_id="raw1", path="raw/1.png"):
    """Insert straight into the table, bypassing every service check."""
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO media_assets "
            "(id, user_id, kind, title, storage_path, mime_type, size_bytes, "
            " content_hash, source_id, chapter_title, licence_code, script, status, "
            " created_at, updated_at) "
            "VALUES (?, 'u1', 'mind_map', '', ?, 'image/png', 1, ?, ?, '', ?, '', "
            " 'ready', 't', 't')",
            (asset_id, path, f"h-{asset_id}", source_id, licence_code),
        )


def test_the_database_refuses_a_source_without_a_licence(db):
    """A service check can be bypassed by the next writer; this cannot."""
    from deeptutor.services.studio import integrity

    integrity.ensure_guards(db)
    with pytest.raises(Exception) as exc:
        _raw_insert(db, source_id="src_9", licence_code="")
    assert "licence" in str(exc.value).lower()


def test_the_database_refuses_moving_an_asset_onto_an_unlicensed_source(db):
    """An insert-only guard would miss a later update that adds the source."""
    from deeptutor.services.studio import integrity

    asset = _asset(db)
    integrity.ensure_guards(db)
    with db.transaction() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(
                "UPDATE media_assets SET source_id = 'src_7', licence_code = '' WHERE id = ?",
                (asset["id"],),
            )
    assert "licence" in str(exc.value).lower()


def test_the_database_accepts_a_licensed_source(db):
    from deeptutor.services.studio import integrity

    integrity.ensure_guards(db)
    _raw_insert(db, source_id="src_1", licence_code="cc-by")
    with db.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM media_assets WHERE id = 'raw1'") == 1


def test_the_database_accepts_content_with_no_source(db):
    from deeptutor.services.studio import integrity

    integrity.ensure_guards(db)
    _raw_insert(db, source_id=None, licence_code="")
    with db.read() as conn:
        assert conn.scalar("SELECT COUNT(*) FROM media_assets WHERE id = 'raw1'") == 1


def test_blank_whitespace_is_treated_as_missing_by_the_database(db):
    """The service strips; the trigger must strip too or it is a loophole."""
    from deeptutor.services.studio import integrity

    integrity.ensure_guards(db)
    with pytest.raises(Exception):
        _raw_insert(db, source_id="src_1", licence_code="   ")


def test_installing_the_guards_is_idempotent(db):
    from deeptutor.services.studio import integrity

    integrity.reset_memo()
    assert integrity.ensure_guards(db) is True
    assert integrity.ensure_guards(db) is True
    assert integrity.guards_present(db) == {"insert": True, "update": True}


def test_guards_are_not_installed_before_migration(db):
    """A process can start before migrations; it must say so, not pretend."""
    import pathlib
    import tempfile

    from deeptutor.db.config import DatabaseSettings
    from deeptutor.db.connection import open_database
    from deeptutor.services.studio import integrity

    empty = open_database(
        DatabaseSettings(app_url=f"sqlite:///{pathlib.Path(tempfile.mkdtemp())}/e.db", backend="sqlite")
    )
    integrity.reset_memo()
    assert integrity.ensure_guards(empty) is False
    assert integrity.guards_present(empty) == {"insert": False, "update": False}
