"""Durable job queue.

ROADMAP Phase 3 requires a "worker/queue interface for long jobs" whose
acceptance test is: *restarting a worker or retrying a job must not duplicate
its effect.*

The implementation is a Postgres/SQLite table plus conditional updates. That
choice is worth defending because a broker (Redis/Celery) is the obvious
alternative:

* The only durable store this product already owns is the database. Adding a
  broker adds a second stateful service to back up, monitor and secure, for a
  workload of a few hundred jobs a day.
* "No duplicate effect" is a *transactional* property, and the transaction
  boundary already exists in Postgres. Enqueueing in the same transaction as
  the domain write means a job can never be orphaned or double-created.
* It works in tests without any external service, so the acceptance test runs
  in CI instead of being skipped — which is the whole lesson of Gate 1.5.

The interface is deliberately broker-shaped, so moving to Celery later means
reimplementing :class:`JobQueue`, not editing call-sites.
"""

from __future__ import annotations

from deeptutor.db.jobs.queue import (
    ClaimedJob,
    Job,
    JobQueue,
    JobQueueUnavailable,
    JobState,
    acquire_queue,
)

__all__ = [
    "ClaimedJob",
    "Job",
    "JobQueue",
    "JobQueueUnavailable",
    "JobState",
    "acquire_queue",
]
