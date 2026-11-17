-- V0001 — product core: identity, OTP, sessions, audit.
--
-- This is the *baseline* of the product schema. It is written to be applied to
-- an empty database and to a database that already carries the pre-Phase-3
-- tables (see ADR-003 §"Reconciliation"): every object is created with
-- IF NOT EXISTS, and the columns Phase 2 needs but the old schema lacked are
-- added with guarded ALTERs at the end so re-running against the existing
-- Supabase project converges instead of failing.
--
-- Portability: types are the SQLite-tolerant subset. SQLite has no
-- TIMESTAMPTZ/JSONB/BOOLEAN, so timestamp columns are TEXT holding ISO-8601
-- UTC strings (which is also what the Phase 2 JSON store returned, so no caller
-- has to change), booleans are INTEGER 0/1, and jsonb is TEXT holding JSON.
-- The Postgres-only niceties (partial indexes, pgcrypto) live in V0003.

-- @@ UP @@

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    -- E.164 digits without '+'. The Phase 2 identity store keys users by
    -- username; for phone accounts username == phone_number, enforced by the
    -- repository, not by the schema (the local admin account has no phone).
    phone_number TEXT,
    username TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    disabled INTEGER NOT NULL DEFAULT 0,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    avatar TEXT NOT NULL DEFAULT '',
    preset TEXT NOT NULL DEFAULT 'standard',
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT,
    -- Per-account overrides kept from the Phase 2 JSON record. Stored as JSON
    -- text rather than jsonb so SQLite (the CI harness) and Postgres agree; the
    -- repository is the only reader, so no query ever needs jsonb operators.
    book_permission TEXT,
    learner_profile TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_phone_number ON users (phone_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users (username);
CREATE INDEX IF NOT EXISTS ix_users_role ON users (role);

-- One row per issued code. The plaintext code is never stored; only
-- sha256(salt || code). Phase 2 kept this in otp.json; the shape is preserved
-- exactly so the backfill is a straight copy.
CREATE TABLE IF NOT EXISTS otp_codes (
    phone_number TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    digest TEXT NOT NULL,
    expires_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    consumed_at TEXT,
    last_sent_at REAL NOT NULL,
    window_started_at REAL NOT NULL,
    sends_in_window INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_otp_codes_expires_at ON otp_codes (expires_at);

-- Session registry. Phase 2 revoked by bumping users.token_version; a row here
-- adds per-device revocation without changing the token format.
CREATE TABLE IF NOT EXISTS user_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_nonce TEXT NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_sessions_token_nonce ON user_sessions (token_nonce);
CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions (expires_at);

-- Append-only audit trail. Phase 2 wrote audit.json; the repository mirrors the
-- same fields so the admin audit view does not change shape.
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_id TEXT,
    actor_label TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    outcome TEXT NOT NULL DEFAULT 'ok',
    detail TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_events_created_at ON audit_events (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_events_actor ON audit_events (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_events_action ON audit_events (action);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_audit_events_action;
DROP INDEX IF EXISTS ix_audit_events_actor;
DROP INDEX IF EXISTS ix_audit_events_created_at;
DROP TABLE IF EXISTS audit_events;
DROP INDEX IF EXISTS ix_user_sessions_expires_at;
DROP INDEX IF EXISTS ix_user_sessions_user_id;
DROP INDEX IF EXISTS uq_user_sessions_token_nonce;
DROP TABLE IF EXISTS user_sessions;
DROP INDEX IF EXISTS ix_otp_codes_expires_at;
DROP TABLE IF EXISTS otp_codes;
DROP INDEX IF EXISTS ix_users_role;
DROP INDEX IF EXISTS uq_users_username;
DROP INDEX IF EXISTS uq_users_phone_number;
DROP TABLE IF EXISTS users;
