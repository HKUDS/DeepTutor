-- V0005 — create the uniqueness indexes that exist in the baseline but were
-- never created on the live database.
--
-- Found by probing the real Supabase project on 2026-11-17, not by any test:
-- inserting two `payment_transactions` rows with the same (provider, authority)
-- was **accepted**. `uq_payment_provider_authority` is declared inside
-- `CREATE TABLE IF NOT EXISTS payment_transactions` in V0002, and Postgres
-- skips the whole statement — indexes included — when the table already
-- exists. The live project already had the table from the 2026-11-15 Alembic
-- migration, so the index silently never existed.
--
-- The consequence was a real money bug: a gateway callback replayed twice could
-- have created two payable rows and credited the quota twice. The SQLite suite
-- could not catch it because there the table is created fresh and the index
-- comes with it.
--
-- Lesson recorded in ADR-003: **never put an index inside an
-- `IF NOT EXISTS` table body** if the table may pre-exist. Every
-- correctness-bearing index gets its own statement, and
-- `deeptutor.db.schema_check.REQUIRED_INDEXES` now asserts the important ones
-- exist by name after every migration run.
--
-- All statements are idempotent, so this migration is safe to re-run and safe on
-- a database where V0002 did create the indexes.

-- @@ DIALECT: postgres @@

-- @@ UP @@

-- The one that actually failed. Two payments may share an authority only if the
-- provider differs; within one provider an authority is a single transaction.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_provider_authority
    ON payment_transactions (provider, authority);

-- Belt and braces for the rest of the baseline's unique indexes, in case a
-- future table pre-exists for any of these too.
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users (username);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_sessions_token_nonce
    ON user_sessions (token_nonce);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_files_storage_path
    ON user_files (storage_path);
CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_dedupe
    ON jobs (dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_plans_code ON plans (code);

-- Support indexes the baseline declares inside table bodies.
CREATE INDEX IF NOT EXISTS ix_user_files_user ON user_files (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_token_usage_user
    ON token_usage_logs (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_payment_user ON payment_transactions (user_id);
CREATE INDEX IF NOT EXISTS ix_payment_status ON payment_transactions (status);

-- @@ DOWN @@

DROP INDEX IF EXISTS ix_payment_status;
DROP INDEX IF EXISTS ix_payment_user;
DROP INDEX IF EXISTS ix_token_usage_user;
DROP INDEX IF EXISTS ix_user_files_user;
-- The unique indexes are left in place on rollback: dropping a uniqueness
-- constraint is a data-integrity downgrade, and a rollback should not make the
-- database able to hold invalid rows.
