"""Media jobs: admission, lifecycle, cancellation, cache and recovery.

Every test here uses a mock renderer. Gate 8 asks for a controlled real smoke
test as well, and that is a separate, manually-run check -- putting a live
provider call in CI would make the suite depend on someone's API key and
quietly flaky.
"""

from __future__ import annotations

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import accounting as A
from deeptutor.services.studio import jobs as S


def _user(db, user_id="u1", tokens=5000):
    IdentityRepository(db).save(user_id, {"id": user_id, "hash": "x", "role": "user"})
    WalletRepository(db).grant(user_id, tokens=tokens)
    return user_id


def _queue(db):
    return JobQueue(db, worker_id="test")


def _request(**kwargs):
    payload = dict(user_id="u1", kind="mind_map", script="مشتق چیست؟", title="نقشه")
    payload.update(kwargs)
    return S.JobRequest(**payload)


def _renderer(actual=400, text="{}"):
    def render(kind, payload):
        return S.RenderResult(
            storage_path=f"media/{payload.get('content_hash')[:8]}/{kind}.json",
            mime_type="application/json",
            content=text,
            size_bytes=len(text),
            actual_tokens=actual,
            provider="mock",
        )

    return render


def _run_one(db, queue, kind, renderer):
    return queue.run_once(
        {S.job_kind(kind): lambda job: S.run_job(db, queue=queue, job=job, renderer=renderer)},
        limit=1,
    )


# ---------------------------------------------------------------------------
# Admission: no job without entitlement and quota
# ---------------------------------------------------------------------------


def test_a_job_reserves_before_it_is_enqueued(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    result = S.submit(db, queue=queue, request=_request())

    assert result["reserved_tokens"] == S.DEFAULT_ESTIMATES["mind_map"].tokens
    assert A.open_holds(db, "u1") == result["reserved_tokens"]
    assert queue.get(result["job_id"]) is not None


def test_a_job_without_entitlement_is_refused_before_any_hold(db):
    """403 is not 402: 'you may not' and 'you cannot afford' are different."""
    _user(db, "u1", tokens=10000)
    queue = _queue(db)

    with pytest.raises(S.StudioError) as exc:
        S.submit(
            db,
            queue=queue,
            request=_request(kind="video_lesson"),
            require_entitlement=lambda user, kind: False,
        )

    assert exc.value.rule == "not_entitled"
    assert A.open_holds(db, "u1") == 0
    assert queue.stats().get("queued", 0) == 0


def test_a_job_beyond_the_quota_is_refused_and_leaves_no_trace(db):
    _user(db, "u1", tokens=10)
    queue = _queue(db)

    with pytest.raises(A.QuotaExceeded):
        S.submit(db, queue=queue, request=_request())

    assert A.open_holds(db, "u1") == 0
    assert all(row["kind"] != "media.mind_map" for row in _all_jobs(db))


def test_an_unknown_kind_is_refused(db):
    _user(db, "u1")
    with pytest.raises(S.StudioError) as exc:
        S.submit(db, queue=_queue(db), request=_request(kind="hologram"))
    assert exc.value.rule == "unknown_kind"


def test_an_empty_script_is_refused(db):
    _user(db, "u1")
    with pytest.raises(S.StudioError) as exc:
        S.submit(db, queue=_queue(db), request=_request(script="   "))
    assert exc.value.rule == "empty_script"


def _all_jobs(db):
    with db.read() as conn:
        return [dict(row) for row in conn.query("SELECT * FROM jobs")]


# ---------------------------------------------------------------------------
# Lifecycle and settle
# ---------------------------------------------------------------------------


def test_a_successful_job_settles_at_the_actual_cost(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    _run_one(db, queue, "mind_map", _renderer(actual=250))

    assert WalletRepository(db).get("u1")["tokens_remaining"] == 750
    assert A.open_holds(db, "u1") == 0
    assert queue.get(submitted["job_id"]).status == "succeeded"


def test_the_actual_cost_is_recorded_beside_the_estimate(db):
    """Gate 8 checks the estimate against reality; overwriting loses the finding."""
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())
    _run_one(db, queue, "mind_map", _renderer(actual=250))

    costs = {row["phase"]: row for row in S.job_costs(db, submitted["job_id"])}
    assert costs["estimate"]["tokens"] == S.DEFAULT_ESTIMATES["mind_map"].tokens
    assert costs["actual"]["tokens"] == 250


def test_a_job_that_cannot_report_a_cost_settles_at_the_estimate(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    def render(kind, payload):
        return S.RenderResult(
            storage_path="media/x/mind_map.json",
            mime_type="application/json",
            actual_tokens=None,  # provider did not say
        )

    _run_one(db, queue, "mind_map", render)
    assert WalletRepository(db).get("u1")["tokens_remaining"] == 1000 - submitted["reserved_tokens"]


def test_a_successful_job_creates_one_asset_with_provenance(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    S.submit(
        db,
        queue=queue,
        request=_request(source_id="src_1", chapter_title="فصل ۳", licence_code="cc-by"),
    )
    _run_one(db, queue, "mind_map", _renderer())

    assets = S.list_assets(db, user_id="u1")
    assert len(assets) == 1
    assert assets[0]["source_id"] == "src_1"
    assert assets[0]["chapter_title"] == "فصل ۳"
    assert assets[0]["licence_code"] == "cc-by"


# ---------------------------------------------------------------------------
# Failure and refund
# ---------------------------------------------------------------------------


def test_a_single_failure_keeps_the_hold_for_the_retry(db):
    """A retry that had already been refunded would settle against nothing.

    The hold belongs to the *purchase*, not the attempt, so it survives a
    failure as long as another attempt is coming.
    """
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    def boom(kind, payload):
        raise RuntimeError("provider down")

    _run_one(db, queue, "mind_map", boom)

    assert WalletRepository(db).get("u1")["tokens_remaining"] == 1000
    assert A.open_holds(db, "u1") == submitted["reserved_tokens"], "held, not refunded"


def test_a_terminally_failed_job_refunds_the_hold(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    def boom(kind, payload):
        raise RuntimeError("provider down")

    for _ in range(S.MEDIA_MAX_ATTEMPTS):
        with db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET run_after = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                (submitted["job_id"],),
            )
        _run_one(db, queue, "mind_map", boom)

    assert queue.get(submitted["job_id"]).status == "failed"
    assert WalletRepository(db).get("u1")["tokens_remaining"] == 1000
    assert A.open_holds(db, "u1") == 0, "a dead job must not hold money"


def test_a_failed_job_is_requeued_within_its_retry_limit(db):
    """Media retries are capped lower than the queue default: each attempt can
    cost a real provider call."""
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    def boom(kind, payload):
        raise RuntimeError("provider down")

    _run_one(db, queue, "mind_map", boom)
    assert queue.get(submitted["job_id"]).status == "queued"

    # Exhaust the attempts.
    for _ in range(S.MEDIA_MAX_ATTEMPTS):
        with db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET run_after = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                (submitted["job_id"],),
            )
        _run_one(db, queue, "mind_map", boom)

    job = queue.get(submitted["job_id"])
    assert job.status == "failed"
    assert job.attempts >= S.MEDIA_MAX_ATTEMPTS
    assert WalletRepository(db).get("u1")["tokens_remaining"] == 1000, "every attempt refunded"


def test_a_retry_reuses_the_same_hold(db):
    """A second attempt is more work towards one purchase, not a second one."""
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())
    first_hold = A.open_holds(db, "u1")

    def boom(kind, payload):
        raise RuntimeError("provider down")

    _run_one(db, queue, "mind_map", boom)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE jobs SET run_after = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (submitted["job_id"],),
        )
    _run_one(db, queue, "mind_map", _renderer(actual=250))

    assert first_hold == submitted["reserved_tokens"]
    assert WalletRepository(db).get("u1")["tokens_remaining"] == 750


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancelling_a_queued_job_refunds_it(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    result = S.cancel(db, queue=queue, job_id=submitted["job_id"], user_id="u1")

    assert result["cancelled"] is True
    assert result["refunded"] is True
    assert A.open_holds(db, "u1") == 0
    assert WalletRepository(db).get("u1")["tokens_remaining"] == 1000


def test_cancelling_someone_elses_job_is_not_found(db):
    _user(db, "u1")
    _user(db, "u2")
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    with pytest.raises(S.StudioError) as exc:
        S.cancel(db, queue=queue, job_id=submitted["job_id"], user_id="u2")
    assert exc.value.rule == "job_not_found"
    assert A.open_holds(db, "u1") == submitted["reserved_tokens"], "untouched"


def test_a_job_cancelled_midflight_is_not_charged(db):
    """The queue cannot preempt a handler, so the handler must honour it."""
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())

    def cancel_then_render(kind, payload):
        queue.cancel(submitted["job_id"])
        return S.RenderResult(
            storage_path="media/x.json", mime_type="application/json", actual_tokens=400
        )

    _run_one(db, queue, "mind_map", cancel_then_render)

    assert WalletRepository(db).get("u1")["tokens_remaining"] == 1000
    assert A.open_holds(db, "u1") == 0
    assert S.list_assets(db, user_id="u1") == [], "a cancelled job produces nothing"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_an_identical_request_reuses_the_asset_and_costs_nothing(db):
    _user(db, "u1", tokens=1000)
    queue = _queue(db)
    submitted = S.submit(db, queue=queue, request=_request())
    _run_one(db, queue, "mind_map", _renderer(actual=250))
    balance = WalletRepository(db).get("u1")["tokens_remaining"]

    again = S.submit(db, queue=queue, request=_request())

    assert again["cached"] is True
    assert again["reserved_tokens"] == 0
    assert again["asset"]["id"] == S.list_assets(db, user_id="u1")[0]["id"]
    assert WalletRepository(db).get("u1")["tokens_remaining"] == balance
    assert A.open_holds(db, "u1") == 0


def test_a_different_licence_is_not_a_cache_hit(db):
    """Reusing across a licence change would carry the old terms forward."""
    _user(db, "u1", tokens=5000)
    queue = _queue(db)
    S.submit(db, queue=queue, request=_request(licence_code="cc-by"))
    _run_one(db, queue, "mind_map", _renderer())

    again = S.submit(db, queue=queue, request=_request(licence_code="all-rights"))
    assert again["cached"] is False


def test_a_different_render_setting_is_not_a_cache_hit(db):
    _user(db, "u1", tokens=5000)
    queue = _queue(db)
    S.submit(db, queue=queue, request=_request(render={"voice": "a"}))
    _run_one(db, queue, "mind_map", _renderer())

    again = S.submit(db, queue=queue, request=_request(render={"voice": "b"}))
    assert again["cached"] is False


def test_two_users_do_not_share_a_cached_asset(db):
    """Storage is billed per user; a shared asset breaks somebody's quota."""
    _user(db, "u1", tokens=5000)
    _user(db, "u2", tokens=5000)
    queue = _queue(db)
    S.submit(db, queue=queue, request=_request())
    _run_one(db, queue, "mind_map", _renderer())

    other = S.submit(db, queue=queue, request=_request(user_id="u2"))
    assert other["cached"] is False


# ---------------------------------------------------------------------------
# Recovery after a worker restart
# ---------------------------------------------------------------------------


def test_a_job_whose_worker_died_is_reclaimed_and_completed(db):
    """The lease-expiry path, which is how a killed worker's work is recovered."""
    _user(db, "u1", tokens=1000)
    dead = JobQueue(db, worker_id="dead-worker")
    submitted = S.submit(db, queue=dead, request=_request())

    # The worker claims the job and then vanishes without settling.
    claimed = dead.claim(limit=1, lease_seconds=1)
    assert len(claimed) == 1

    # Its lease expires. A fresh worker must pick it up and finish it.
    import time

    time.sleep(1.2)
    live = JobQueue(db, worker_id="live-worker")
    _run_one(db, live, "mind_map", _renderer(actual=250))

    assert live.get(submitted["job_id"]).status == "succeeded"
    assert WalletRepository(db).get("u1")["tokens_remaining"] == 750
    assert A.open_holds(db, "u1") == 0, "the hold was settled exactly once"


def test_a_second_worker_cannot_run_the_same_job(db):
    _user(db, "u1", tokens=1000)
    a = JobQueue(db, worker_id="a")
    submitted = S.submit(db, queue=a, request=_request())

    first = a.claim(limit=1, lease_seconds=60)
    second = a.claim(limit=1, lease_seconds=60)

    assert len(first) == 1
    assert second == [], "a live lease must not be claimable twice"
    assert submitted["job_id"] == first[0].id
