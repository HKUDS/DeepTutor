-- V0002 — billing, quotas and storage metadata.
--
-- Wallet correctness is the point of this migration. ROADMAP Phase 3 requires
-- "transaction and unique constraints for wallet/reservations/account
-- identity", so the invariants live in the schema rather than in Python:
--
-- * token balances can never go negative (CHECK)
-- * a payment can only be settled once (status transition guarded by the
--   repository, plus a UNIQUE authority per provider so a retried callback
--   cannot grant tokens twice)
-- * storage usage is derived from user_files, which has a UNIQUE (user_id,
--   content_hash) so the same bytes are not stored twice for one user
--
-- Money is stored as integers in Toman. Never floats: 0.1 + 0.2 problems in a
-- wallet are indistinguishable from theft.

-- @@ UP @@

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_toman INTEGER NOT NULL DEFAULT 0,
    token_quota INTEGER NOT NULL DEFAULT 0,
    duration_days INTEGER NOT NULL DEFAULT 30,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 1,
    storage_quota_bytes INTEGER NOT NULL DEFAULT 104857600,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_plans_code ON plans (code);
CREATE INDEX IF NOT EXISTS ix_plans_active ON plans (is_active, sort_order);

-- Single-row configuration. The CHECK pins the row id so a second row cannot
-- exist; billing settings read through one place or not at all.
CREATE TABLE IF NOT EXISTS billing_settings (
    id INTEGER PRIMARY KEY,
    token_price_per_1k_toman INTEGER NOT NULL DEFAULT 1000,
    starter_tokens INTEGER NOT NULL DEFAULT 15000,
    starter_duration_days INTEGER NOT NULL DEFAULT 7,
    starter_storage_bytes INTEGER NOT NULL DEFAULT 26214400,
    admin_preferences TEXT NOT NULL DEFAULT '{}',
    system_config TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    CHECK (id = 1)
);

-- Wallet state per user. Separate from users so a wallet write does not touch
-- the identity row (row-level lock contention on login).
CREATE TABLE IF NOT EXISTS user_wallets (
    user_id TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    plan_code TEXT,
    plan_started_at TEXT,
    plan_expires_at TEXT,
    tokens_total INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    tokens_remaining INTEGER NOT NULL DEFAULT 0,
    storage_used_bytes INTEGER NOT NULL DEFAULT 0,
    storage_quota_bytes INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    CHECK (tokens_total >= 0),
    CHECK (tokens_used >= 0),
    CHECK (tokens_remaining >= 0),
    CHECK (storage_used_bytes >= 0),
    CHECK (tokens_remaining = tokens_total - tokens_used)
);
CREATE INDEX IF NOT EXISTS ix_user_wallets_plan ON user_wallets (plan_code);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    plan_code TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    amount_toman INTEGER NOT NULL,
    tokens_granted INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    provider TEXT NOT NULL,
    authority TEXT,
    ref_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    paid_at TEXT,
    CHECK (amount_toman >= 0),
    CHECK (tokens_granted >= 0),
    CHECK (status IN ('pending', 'paid', 'failed', 'cancelled', 'refunded'))
);
-- A gateway callback retried twice must not create two paid rows, and must not
-- grant the quota twice. One authority per provider is the idempotency key.
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_provider_authority
    ON payment_transactions (provider, authority);
CREATE INDEX IF NOT EXISTS ix_payment_user ON payment_transactions (user_id);
CREATE INDEX IF NOT EXISTS ix_payment_status ON payment_transactions (status);

-- Immutable spend log. One row per billable action; the wallet's
-- tokens_used is the sum, and this table is the evidence.
CREATE TABLE IF NOT EXISTS token_usage_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    book_id INTEGER,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_toman INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    CHECK (prompt_tokens >= 0),
    CHECK (completion_tokens >= 0),
    CHECK (total_tokens >= 0),
    CHECK (cost_toman >= 0)
);
CREATE INDEX IF NOT EXISTS ix_token_usage_user ON token_usage_logs (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_token_usage_created ON token_usage_logs (created_at);

-- Uploaded files. storage_path is the key handed to the object-storage
-- interface (deeptutor.db.storage), not a filesystem path: the local-disk
-- backend prefixes its root, an S3 backend maps it to a bucket key. Keeping the
-- column relative is what makes a backend swap a config change.
CREATE TABLE IF NOT EXISTS user_files (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    category TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT,
    source_context TEXT NOT NULL DEFAULT 'personal_upload',
    chat_session_id TEXT,
    book_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    CHECK (size_bytes >= 0),
    CHECK (status IN ('active', 'deleted'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_files_storage_path ON user_files (storage_path);
CREATE INDEX IF NOT EXISTS ix_user_files_user ON user_files (user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_user_files_category ON user_files (category);
-- Deduplicating within one user's library, and only for live rows: a soft
-- deleted file may be re-uploaded.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_files_content
    ON user_files (user_id, content_hash) WHERE content_hash IS NOT NULL AND status = 'active';

-- @@ DOWN @@

DROP INDEX IF EXISTS uq_user_files_content;
DROP INDEX IF EXISTS ix_user_files_category;
DROP INDEX IF EXISTS ix_user_files_user;
DROP INDEX IF EXISTS uq_user_files_storage_path;
DROP TABLE IF EXISTS user_files;
DROP INDEX IF EXISTS ix_token_usage_created;
DROP INDEX IF EXISTS ix_token_usage_user;
DROP TABLE IF EXISTS token_usage_logs;
DROP INDEX IF EXISTS ix_payment_status;
DROP INDEX IF EXISTS ix_payment_user;
DROP INDEX IF EXISTS uq_payment_provider_authority;
DROP TABLE IF EXISTS payment_transactions;
DROP INDEX IF EXISTS ix_user_wallets_plan;
DROP TABLE IF EXISTS user_wallets;
DROP TABLE IF EXISTS billing_settings;
DROP INDEX IF EXISTS ix_plans_active;
DROP INDEX IF EXISTS uq_plans_code;
DROP TABLE IF EXISTS plans;
