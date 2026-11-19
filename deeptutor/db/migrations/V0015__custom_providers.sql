-- V0015: a user-supplied AI endpoint.
--
-- The key is NOT in this table. It is handed to the encrypted secret store and
-- this row keeps a reference, so a database dump cannot contain a credential
-- and a query cannot return one by accident.
--
-- base_url is stored already validated (net_guard resolves and checks the
-- address). It is re-validated at use time as well, because DNS between save
-- and use is an attack window that a store-time check cannot close.

-- @@ UP @@
CREATE TABLE IF NOT EXISTS custom_providers (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    secret_ref TEXT NOT NULL,
    -- 'actual' when the provider reported usage, 'estimated' otherwise. A cost
    -- report that does not distinguish the two cannot be audited.
    cost_basis TEXT NOT NULL DEFAULT 'estimated'
        CHECK (cost_basis IN ('actual', 'estimated')),
    verified_at TEXT,
    created_at TEXT NOT NULL,
    CHECK (length(trim(name)) > 0),
    CHECK (length(trim(base_url)) > 0),
    CHECK (length(trim(model)) > 0),
    -- The scheme is the one thing a stored row can assert cheaply. A row that
    -- says file:// is a row that was written without going through create().
    CHECK (base_url LIKE 'http://%' OR base_url LIKE 'https://%')
);
CREATE INDEX IF NOT EXISTS ix_custom_providers_user ON custom_providers (user_id, created_at);
-- One name per account, so "my provider" is unambiguous in a picker.
CREATE UNIQUE INDEX IF NOT EXISTS ux_custom_providers_user_name
    ON custom_providers (user_id, name);

-- @@ DOWN @@
DROP INDEX IF EXISTS ux_custom_providers_user_name;
DROP INDEX IF EXISTS ix_custom_providers_user;
DROP TABLE IF EXISTS custom_providers;
