-- V0004 — reconcile the pre-existing Supabase schema with the product schema.
--
-- Context: the live project already carried six migrations (2026-11-14 →
-- 2026-11-15) that created 16 tables. They describe the *same product* but
-- disagree with the Phase 2 implementation on the identity model:
--
--   old schema                       Phase 2 / this schema
--   ------------------------------   -----------------------------------
--   users.phone_number NOT NULL      username is the identity; phone nullable
--   users.is_active                  users.disabled (+ must_change_password)
--   users.role default 'student'     default 'user'
--   no password_hash column          password_hash NOT NULL
--   user_sessions.revoked_at ✓       ✓ (already compatible)
--   otp_codes (code_hash, attempts)  otp_codes (salt, digest, ...)
--
-- The owner's ruling (2026-11-17): the **Phase 2 model is authoritative** and
-- Supabase is brought to it. Every user-facing table in the live project was
-- empty (0 rows in users, otp_codes, user_sessions, user_files,
-- payment_transactions, token_usage_logs), so no data can be lost — but this
-- migration still does the safe thing and ALTERs rather than drops, so it would
-- remain correct if a row appeared between the audit and the deploy.
--
-- Reference data that must survive untouched: grades (12), majors (3),
-- plans (3), billing_settings (1). This migration never touches those four
-- tables. Evidence of the pre-migration state is in
-- docs/darsyar/evidence/phase3-pre-migration-snapshot.json.
--
-- Why ALTER and not DROP: a DROP would also have to drop 11 foreign keys
-- pointing at users, including ones from tables this migration does not own.
-- ALTER touches only what actually conflicts.

-- @@ DIALECT: postgres @@

-- @@ UP @@

-- ---------------------------------------------------------------------------
-- users: add every column the Phase 2 record needs and the old table lacks.
-- Additive only; nothing existing is removed, so a rollback can drop exactly
-- this list.
-- ---------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS preset TEXT NOT NULL DEFAULT 'standard';
ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS book_permission TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS learner_profile TEXT;

-- The old table required a phone on every row; a local admin account has none.
-- Relaxing the constraint is what makes the bootstrap admin expressible at all.
ALTER TABLE users ALTER COLUMN phone_number DROP NOT NULL;

-- Old tables defaulted role to 'student', which is NOT a role this codebase
-- accepts (VALID_ROLES = admin/teacher/student/user — 'student' is valid, so
-- keep it; only the *default* changes for new rows created by this schema).
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user';

-- Username is the identity key the repositories look up by. Unique when
-- present, null for rows that have not been migrated to a username yet.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_role ON users (role);

-- ---------------------------------------------------------------------------
-- otp_codes: the old table stores a single code_hash; the schema needs the
-- salt/digest pair plus the rate-limit window. Additive; the old columns
-- (code_hash, consumed_at, id) are left in place and simply unused. They must
-- be nullable-tolerant, so new columns get defaults where a value is required.
-- ---------------------------------------------------------------------------
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS salt TEXT;
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS digest TEXT;
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS last_sent_at DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS window_started_at DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS sends_in_window INTEGER NOT NULL DEFAULT 0;
ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS phone_number TEXT;

-- The old table allowed many rows per phone (id primary key). The new model
-- keeps exactly one live code per phone, which is what makes consumption
-- atomic. Delete any surplus rows first so the unique index can be built; there
-- were zero rows at the time of writing, so this is a no-op in practice.
DELETE FROM otp_codes a
    USING otp_codes b
    WHERE a.phone_number = b.phone_number
      AND a.ctid < b.ctid;
CREATE UNIQUE INDEX IF NOT EXISTS uq_otp_codes_phone ON otp_codes (phone_number);

-- ---------------------------------------------------------------------------
-- user_sessions: already compatible with the product schema (it has
-- revoked_at). Only the unique nonce index and a supporting index are added.
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_sessions_token_nonce ON user_sessions (token_nonce);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions (expires_at);

-- ---------------------------------------------------------------------------
-- user_wallets: a new table, not present in the old schema, because the old
-- schema denormalised balances onto users.tokens_remaining. The denormalised
-- columns stay (they are still referenced) and this table becomes the
-- transactional source of truth; the backfill in the report copies existing
-- users across.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_wallets (
    user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    plan_code TEXT,
    plan_started_at TIMESTAMPTZ,
    plan_expires_at TIMESTAMPTZ,
    tokens_total INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    tokens_remaining INTEGER NOT NULL DEFAULT 0,
    storage_used_bytes BIGINT NOT NULL DEFAULT 0,
    storage_quota_bytes BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_wallet_non_negative CHECK (
        tokens_total >= 0 AND tokens_used >= 0
        AND tokens_remaining >= 0 AND storage_used_bytes >= 0
    ),
    CONSTRAINT ck_wallet_balance CHECK (tokens_remaining = tokens_total - tokens_used)
);
CREATE INDEX IF NOT EXISTS ix_user_wallets_plan ON user_wallets (plan_code);

-- ---------------------------------------------------------------------------
-- jobs: the durable queue. Not present in the old schema at all.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    dedupe_key TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 100,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_jobs_status CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT ck_jobs_attempts CHECK (attempts >= 0 AND max_attempts > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_dedupe
    ON jobs (dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_jobs_claimable ON jobs (status, run_after, priority);
CREATE INDEX IF NOT EXISTS ix_jobs_kind ON jobs (kind, status);
CREATE INDEX IF NOT EXISTS ix_jobs_lease ON jobs (lease_expires_at);

CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    worker TEXT,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_job_events_job ON job_events (job_id, created_at);

-- ---------------------------------------------------------------------------
-- audit_events: not present in the old schema.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_id TEXT,
    actor_label TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    outcome TEXT NOT NULL DEFAULT 'ok',
    detail JSONB,
    ip_address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_events_created_at ON audit_events (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_events_actor ON audit_events (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_events_action ON audit_events (action);

-- ---------------------------------------------------------------------------
-- user_files: old table has no content_hash, so the dedupe index cannot be
-- meaningful without it. Added nullable; the partial unique index treats NULL
-- as "not deduplicated", which is the correct behaviour for legacy rows.
-- ---------------------------------------------------------------------------
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS content_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_files_content
    ON user_files (user_id, content_hash)
    WHERE content_hash IS NOT NULL AND status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_files_storage_path ON user_files (storage_path);

-- @@ DOWN @@

DROP INDEX IF EXISTS uq_user_files_storage_path;
DROP INDEX IF EXISTS uq_user_files_content;
ALTER TABLE user_files DROP COLUMN IF EXISTS content_hash;

DROP INDEX IF EXISTS ix_audit_events_action;
DROP INDEX IF EXISTS ix_audit_events_actor;
DROP INDEX IF EXISTS ix_audit_events_created_at;
DROP TABLE IF EXISTS audit_events;

DROP INDEX IF EXISTS ix_job_events_job;
DROP TABLE IF EXISTS job_events;
DROP INDEX IF EXISTS ix_jobs_lease;
DROP INDEX IF EXISTS ix_jobs_kind;
DROP INDEX IF EXISTS ix_jobs_claimable;
DROP INDEX IF EXISTS uq_jobs_dedupe;
DROP TABLE IF EXISTS jobs;

DROP INDEX IF EXISTS ix_user_wallets_plan;
DROP TABLE IF EXISTS user_wallets;

DROP INDEX IF EXISTS ix_user_sessions_expires_at;
DROP INDEX IF EXISTS ix_user_sessions_user_id;
DROP INDEX IF EXISTS uq_user_sessions_token_nonce;

DROP INDEX IF EXISTS uq_otp_codes_phone;
ALTER TABLE otp_codes DROP COLUMN IF EXISTS phone_number;
ALTER TABLE otp_codes DROP COLUMN IF EXISTS sends_in_window;
ALTER TABLE otp_codes DROP COLUMN IF EXISTS window_started_at;
ALTER TABLE otp_codes DROP COLUMN IF EXISTS last_sent_at;
ALTER TABLE otp_codes DROP COLUMN IF EXISTS digest;
ALTER TABLE otp_codes DROP COLUMN IF EXISTS salt;

DROP INDEX IF EXISTS ix_users_role;
DROP INDEX IF EXISTS uq_users_username;
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'student';
ALTER TABLE users DROP COLUMN IF EXISTS learner_profile;
ALTER TABLE users DROP COLUMN IF EXISTS book_permission;
ALTER TABLE users DROP COLUMN IF EXISTS token_version;
ALTER TABLE users DROP COLUMN IF EXISTS preset;
ALTER TABLE users DROP COLUMN IF EXISTS avatar;
ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;
ALTER TABLE users DROP COLUMN IF EXISTS disabled;
ALTER TABLE users DROP COLUMN IF EXISTS username;
ALTER TABLE users DROP COLUMN IF EXISTS password_hash;
