"""Capacity is a measurement, so the test asserts the shape of the measurement.

A throughput number on its own is not a claim anyone can check: it depends on
the host. What *can* be checked is behaviour under concurrency -- that jobs all
complete, that nothing is lost or double-charged, and that a slow queue does not
corrupt the ledger. The numbers themselves live in the evidence file.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from deeptutor.db.jobs.queue import JobQueue
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import accounting
from deeptutor.services.studio import jobs as S

#: Enough rounds to exhaust `DEFAULT_MAX_ATTEMPTS` for every job in the burst.
QUEUE_ROUNDS = 4


def _owner(db, tokens=500_000):
    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u1", tokens=tokens)


def _render(kind, payload):
    return S.RenderResult(
        storage_path=f"media/u1/{kind}-{payload['content_hash'][:8]}.png",
        mime_type="image/png",
        size_bytes=120,
        actual_tokens=10,
        provider="local",
    )


def _drain(queue, db, kinds=(("mind_map",),)):
    while True:
        did = queue.run_once(
            {
                S.job_kind("mind_map"): lambda job: S.run_job(
                    db, queue=queue, job=job, renderer=_render
                )
            }
        )
        if not did:
            return


def test_concurrent_submissions_are_all_accepted_exactly_once(db):
    """Two threads submitting at once must not both claim the same hold."""
    _owner(db)
    queue = JobQueue(db, worker_id="t")
    ids: list[str] = []
    lock = threading.Lock()
    errors: list[str] = []

    def submit(index: int) -> None:
        try:
            result = S.submit(
                db,
                queue=queue,
                request=S.JobRequest(
                    user_id="u1", kind="mind_map", script=f"متن {index}"
                ),
            )
            with lock:
                ids.append(result["job_id"])
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(submit, range(16)))

    assert not errors, errors[:3]
    assert len(ids) == len(set(ids)) == 16


def test_a_burst_holds_no_more_than_it_spent(db):
    """After draining, the wallet balance must equal grant minus actual cost."""
    _owner(db)
    queue = JobQueue(db, worker_id="t")
    submitted = 12
    for index in range(submitted):
        S.submit(
            db,
            queue=queue,
            request=S.JobRequest(user_id="u1", kind="mind_map", script=f"متن {index}"),
        )

    held_before = accounting.open_holds(db, "u1")
    assert held_before > 0, "a queued job must hold tokens, or the wallet oversells"

    _drain(queue, db)

    assert accounting.open_holds(db, "u1") == 0, "settled jobs must release holds"
    remaining = accounting.available_tokens(db, "u1")
    assert remaining > 0
    assert remaining == 500_000 - submitted * 10, (
        "the wallet must be charged exactly the measured cost per job"
    )


def test_a_failing_job_refunds_and_does_not_stop_the_burst(db):
    """One bad render must not poison the queue or the balance of the rest."""
    _owner(db)
    queue = JobQueue(db, worker_id="t")
    for index in range(6):
        S.submit(
            db,
            queue=queue,
            request=S.JobRequest(user_id="u1", kind="mind_map", script=f"متن {index}"),
        )

    calls = {"n": 0}

    def flaky(kind, payload):
        calls["n"] += 1
        if calls["n"] % 2 == 1:
            raise RuntimeError("renderer exploded")
        return _render(kind, payload)

    def drain():
        while queue.run_once(
            {
                S.job_kind("mind_map"): lambda job: S.run_job(
                    db, queue=queue, job=job, renderer=flaky
                )
            }
        ):
            pass

    drain()
    assert calls["n"] == 6, "every job must be attempted once per round"

    # A retry keeps its hold on purpose: refunding on the first failure would
    # close the reservation and the retry would then have nothing to settle
    # against. The cost of that choice is real -- tokens stay held across
    # backoff -- so this test asserts both halves of it: the hold survives
    # while retries remain, and it is released when they are exhausted.
    assert accounting.open_holds(db, "u1") > 0, (
        "a job waiting on a retry legitimately still holds its tokens"
    )

    # The retries are scheduled with exponential backoff, so `run_once` will not
    # pick them up until `run_after` passes. Move the clock forward instead of
    # sleeping for fourteen seconds.
    from datetime import datetime, timedelta, timezone

    for _ in range(QUEUE_ROUNDS):
        # `run_after` gates the claim: a retry sits in backoff until it passes.
        # Backdating it simulates that wait without sleeping for it.
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with db.transaction() as conn:
            conn.execute(
                "UPDATE jobs SET run_after = ? WHERE status = 'queued'", (past,)
            )
        drain()

    assert accounting.open_holds(db, "u1") == 0, (
        "a job that exhausted its retries must release its hold"
    )


def test_the_queue_reports_depth_while_a_burst_is_open(db):
    _owner(db)
    queue = JobQueue(db, worker_id="t")
    for index in range(5):
        S.submit(
            db,
            queue=queue,
            request=S.JobRequest(user_id="u1", kind="mind_map", script=f"x {index}"),
        )
    from deeptutor.db.jobs import queue as queue_module

    health = queue_module.health(db)
    assert health["ok"] is True
    assert health["depth"]["queued"] == 5, health["depth"]


@pytest.mark.parametrize("concurrency", [4, 8])
def test_throughput_does_not_degrade_with_concurrency(db, concurrency):
    """Every job completes at every level; the queue is not the failure point.

    This is deliberately not an absolute number -- that depends on the host and
    is recorded in the evidence file. What must hold is that raising concurrency
    does not lose work.
    """
    _owner(db)
    queue = JobQueue(db, worker_id=f"t{concurrency}")

    def one(index: int) -> str:
        return S.submit(
            db,
            queue=queue,
            request=S.JobRequest(user_id="u1", kind="mind_map", script=f"متن {index}"),
        )["job_id"]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        ids = list(pool.map(one, range(concurrency * 2)))
    assert len(set(ids)) == concurrency * 2

    _drain(queue, db)
    assert accounting.open_holds(db, "u1") == 0
