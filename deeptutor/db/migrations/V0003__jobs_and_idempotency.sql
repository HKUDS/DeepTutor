-- V0003 — durable job queue with idempotency.
--
-- ROADMAP Phase 3: "worker/queue interface for long jobs" and "restarting a
-- worker or retrying a job must not produce a duplicate effect".
--
-- Design: the queue is a table, not a broker. A row is the unit of work; a
-- claim is a conditional UPDATE, which is atomic on both engines and needs no
-- external service. That is deliberately boring — it means the acceptance test
-- for "no duplicate effect" can run anywhere, including CI without Redis.
--
-- Idempotency is enforced by ``uq_jobs_dedupe``: a caller supplies a dedupe key
-- ("ocr:book:41:page:7") and the second enqueue of the same key collapses onto
-- the existing row instead of creating a second job. This is what makes a
-- retried request safe.
--
-- Attempt bookkeeping is on the row (attempts/max_attempts/last_error) so a
-- crashed worker's job is recoverable by lease expiry alone: no other state to
-- reconcile.

-- @@ UP @@

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    dedupe_key TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    -- Set when a worker claims the job; a claim whose lease has expired is
    -- reclaimable, which is how a killed worker's work is recovered.
    lease_owner TEXT,
    lease_expires_at TEXT,
    run_after TEXT NOT NULL,
    last_error TEXT,
    result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CHECK (attempts >= 0),
    CHECK (max_attempts > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_dedupe ON jobs (dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_jobs_claimable ON jobs (status, run_after, priority);
CREATE INDEX IF NOT EXISTS ix_jobs_kind ON jobs (kind, status);
CREATE INDEX IF NOT EXISTS ix_jobs_lease ON jobs (lease_expires_at);

-- Append-only job history. The jobs row holds current state; this holds what
-- happened, which is what a duplicate-effect investigation actually needs.
CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    worker TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_job_events_job ON job_events (job_id, created_at);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_job_events_job;
DROP TABLE IF EXISTS job_events;
DROP INDEX IF EXISTS ix_jobs_lease;
DROP INDEX IF EXISTS ix_jobs_kind;
DROP INDEX IF EXISTS ix_jobs_claimable;
DROP INDEX IF EXISTS uq_jobs_dedupe;
DROP TABLE IF EXISTS jobs;
