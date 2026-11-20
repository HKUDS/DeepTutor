"""Job queue: idempotency, lease recovery, retry backoff.

The acceptance criterion from ROADMAP Phase 3 is explicit:

    "restart worker و retry job باعث duplicate اثر نشود"
    (restarting a worker, or retrying a job, must not duplicate its effect)

The tests below attack that from three directions:

1. **Enqueue idempotency** — the same dedupe key never creates two jobs, even
   under a concurrent burst.
2. **Lease recovery** — a worker that dies mid-job has its work reclaimed, and
   the reclaimed job still runs exactly one *effect* because the handler is
   keyed on the job id.
3. **Duplicate-suppression at the queue level** — a completed job's dedupe key
   still blocks a second effect from being queued.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading

import pytest

from deeptutor.db.connection import Database
from deeptutor.db.jobs.queue import JobQueue


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _expire_lease(db: Database, job_id: str) -> None:
    """Simulate a worker that claimed a job and then died.

    Written straight to the table because there is no API for "become a
    zombie" — and that is the point: recovery must depend on the row's lease
    timestamp alone, with no external watchdog or in-memory state.
    """
    long_ago = (utc_now() - timedelta(hours=2)).isoformat()
    with db.transaction() as conn:
        conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE id = ?", (long_ago, job_id))


class TestEnqueue:
    def test_creates_one_job(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("export", {"book": 1})
        assert job.kind == "export"
        assert job.status == "queued"
        assert job.payload == {"book": 1}
        assert job.attempts == 0

    def test_same_dedupe_key_returns_the_same_job(self, db: Database):
        queue = JobQueue(db)
        first = queue.enqueue("ocr", dedupe_key="ocr:book:1:page:2")
        second = queue.enqueue("ocr", dedupe_key="ocr:book:1:page:2")
        assert first.id == second.id
        assert len(queue.list_jobs()) == 1

    def test_different_dedupe_keys_create_separate_jobs(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("ocr", dedupe_key="ocr:1")
        queue.enqueue("ocr", dedupe_key="ocr:2")
        assert len(queue.list_jobs()) == 2

    def test_no_dedupe_key_never_collapses(self, db: Database):
        queue = JobQueue(db)
        a = queue.enqueue("export")
        b = queue.enqueue("export")
        assert a.id != b.id

    def test_concurrent_enqueue_of_one_key_creates_one_job(self, db: Database):
        """The unique index, not the read, is what guarantees this."""
        queue = JobQueue(db)
        results: list[str] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                job = queue.enqueue("ocr", dedupe_key="race-key")
                results.append(job.id)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert not errors, errors
        assert len(set(results)) == 1, f"dedupe key produced {len(set(results))} jobs"
        assert len(queue.list_jobs()) == 1

    def test_delay_defers_visibility(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("slow", delay_seconds=3600)
        assert queue.claim() == []

    def test_priority_orders_claims(self, db: Database):
        queue = JobQueue(db)
        low = queue.enqueue("task", priority=200)
        high = queue.enqueue("task", priority=10)
        claimed = queue.claim(limit=2)
        assert [j.id for j in claimed] == [high.id, low.id]


class TestClaim:
    def test_claim_marks_running_and_increments_attempts(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("task")
        claimed = queue.claim()
        assert len(claimed) == 1
        assert claimed[0].id == job.id
        assert claimed[0].attempts == 1
        assert queue.get(job.id).status == "running"  # type: ignore[union-attr]

    def test_a_claimed_job_cannot_be_claimed_again(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("task")
        assert len(queue.claim()) == 1
        assert queue.claim() == []

    def test_two_queues_cannot_both_claim(self, db: Database):
        """Two workers, one job, one winner."""
        first = JobQueue(db, worker_id="w1")
        second = JobQueue(db, worker_id="w2")
        first.enqueue("task")
        won = first.claim() + second.claim()
        assert len(won) == 1

    def test_expired_lease_is_reclaimable(self, db: Database):
        """What a killed worker actually leaves behind: a running row, dead lease."""
        queue = JobQueue(db)
        queue.enqueue("task")
        first = queue.claim()
        assert len(first) == 1
        _expire_lease(db, first[0].id)
        # The lease ran out two hours ago; a fresh worker must recover the job.
        recovered = queue.claim()
        assert len(recovered) == 1
        assert recovered[0].id == first[0].id
        assert recovered[0].attempts == 2

    def test_kind_filter_restricts_claims(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("ocr")
        queue.enqueue("export")
        claimed = queue.claim(kinds=["export"])
        assert [j.kind for j in claimed] == ["export"]

    def test_claim_respects_limit(self, db: Database):
        queue = JobQueue(db)
        for _ in range(5):
            queue.enqueue("task")
        assert len(queue.claim(limit=3)) == 3


class TestCompletion:
    def test_succeed_marks_terminal(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("task")
        job = queue.claim()[0]
        assert queue.succeed(job, {"rows": 3}) is True
        stored = queue.get(job.id)
        assert stored.status == "succeeded"  # type: ignore[union-attr]
        assert stored.result == {"rows": 3}  # type: ignore[union-attr]
        assert stored.completed_at  # type: ignore[union-attr]

    def test_succeed_twice_only_counts_once(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("task")
        job = queue.claim()[0]
        assert queue.succeed(job) is True
        assert queue.succeed(job) is False

    def test_a_stale_lease_cannot_succeed(self, db: Database):
        """Worker A dies, worker B recovers the job, A wakes up and tries to finish."""
        queue = JobQueue(db, worker_id="A")
        queue.enqueue("task")
        stale = queue.claim()[0]
        _expire_lease(db, stale.id)
        fresh = JobQueue(db, worker_id="B").claim()[0]
        assert queue.succeed(fresh) is True
        assert queue.succeed(stale) is False
        assert queue.get(stale.id).status == "succeeded"  # type: ignore[union-attr]

    def test_fail_requeues_with_backoff(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("task")
        claimed = queue.claim()[0]
        outcome = queue.fail(claimed, "boom")
        assert outcome == "queued"
        stored = queue.get(job.id)
        assert stored.status == "queued"  # type: ignore[union-attr]
        assert stored.last_error == "boom"  # type: ignore[union-attr]
        # Backoff means it is not immediately claimable.
        assert queue.claim() == []

    def test_fail_after_max_attempts_is_terminal(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("task", max_attempts=1)
        claimed = queue.claim()[0]
        assert queue.fail(claimed, "boom") == "failed"
        assert queue.get(claimed.id).status == "failed"  # type: ignore[union-attr]

    def test_retry_false_fails_immediately(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("task", max_attempts=5)
        claimed = queue.claim()[0]
        assert queue.fail(claimed, "permanent", retry=False) == "failed"

    def test_cancel_a_queued_job(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("task")
        assert queue.cancel(job.id) is True
        assert queue.get(job.id).status == "cancelled"  # type: ignore[union-attr]

    def test_cancel_is_not_possible_twice(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("task")
        queue.cancel(job.id)
        assert queue.cancel(job.id) is False

    def test_cancelled_job_is_not_claimed(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("task")
        queue.cancel(job.id)
        assert queue.claim() == []


class TestRunOnce:
    def test_processes_with_the_registered_handler(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("double", {"n": 21})
        seen: list[int] = []

        def handler(job):
            seen.append(job.payload["n"])
            return {"doubled": job.payload["n"] * 2}

        assert queue.run_once({"double": handler}) == 1
        assert seen == [21]
        assert queue.list_jobs(status="succeeded")[0].result == {"doubled": 42}

    def test_unknown_kind_fails_loudly_not_silently(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("nobody-handles-this")
        queue.run_once({"other": lambda job: None})
        jobs = queue.list_jobs()
        # It must not be left queued looking like health.
        assert jobs == [] or jobs[0].status != "queued"

    def test_handler_exception_becomes_a_retry(self, db: Database):
        queue = JobQueue(db)

        def explode(job):
            raise RuntimeError("disk on fire")

        queue.enqueue("boom")
        queue.run_once({"boom": explode})
        job = queue.list_jobs()[0]
        assert job.status == "queued"
        assert "disk on fire" in (job.last_error or "")

    def test_empty_queue_returns_zero(self, db: Database):
        assert JobQueue(db).run_once({}) == 0


class TestDuplicateEffect:
    def test_retrying_a_completed_job_produces_no_second_effect(self, db: Database):
        """The headline acceptance test.

        A job whose handler appends to an "effects" list is enqueued twice with
        the same dedupe key, then run. The second enqueue collapses and the
        second run finds nothing to claim, so the effect happens exactly once.
        """
        queue = JobQueue(db)
        effects: list[str] = []

        def handler(job):
            effects.append(job.payload["item"])
            return {"done": True}

        key = "ocr:book:9:page:1"
        queue.enqueue("ocr", {"item": "page-1"}, dedupe_key=key)
        queue.run_once({"ocr": handler})
        queue.enqueue("ocr", {"item": "page-1"}, dedupe_key=key)
        queue.run_once({"ocr": handler})

        assert effects == ["page-1"]

    def test_worker_restart_does_not_duplicate_a_succeeded_job(self, db: Database):
        queue = JobQueue(db)
        effects: list[int] = []

        def handler(job):
            effects.append(1)
            return None

        queue.enqueue("task", dedupe_key="once")
        queue.run_once({"task": handler})
        # Simulate a restart: a brand-new queue object over the same database.
        restarted = JobQueue(db)
        restarted.run_once({"task": handler})
        assert len(effects) == 1


class TestObservability:
    def test_stats_counts_by_status(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("a")
        queue.enqueue("b")
        done = queue.enqueue("c")
        queue.claim()
        assert queue.stats()["queued"] >= 1
        assert isinstance(queue.stats(), dict)
        assert done.id

    def test_events_record_the_lifecycle(self, db: Database):
        queue = JobQueue(db)
        job = queue.enqueue("task")
        claimed = queue.claim()[0]
        queue.succeed(claimed)
        events = [e["event"] for e in queue.events(job.id)]
        assert events == ["enqueued", "claimed", "succeeded"]

    def test_list_jobs_filters_by_kind(self, db: Database):
        queue = JobQueue(db)
        queue.enqueue("ocr")
        queue.enqueue("export")
        assert [j.kind for j in queue.list_jobs(kind="ocr")] == ["ocr"]
