# Phase 3 data-layer tests

## Running

```bash
# SQLite only (always available, runs in CI)
pytest tests/db -q

# SQLite + real PostgreSQL
DEEPTUTOR_TEST_DATABASE_URL="postgresql://user:pass@host:5432/dbname" pytest tests/db -q
```

Every behavioural test is parametrised over both engines. Without
`DEEPTUTOR_TEST_DATABASE_URL` the `[postgres]` variants **skip** rather than
fail, so a contributor with no database still gets a green run.

## What the Postgres run adds

The SQLite run is the regression net. The Postgres run is the evidence that the
same SQL is portable — and it has already caught three bugs the SQLite run could
not:

1. A unique index declared inside `CREATE TABLE IF NOT EXISTS` is silently
   skipped when the table already exists. On SQLite the table is always created
   fresh in a temp file, so the index always came with it.
2. `timestamptz` columns reject ISO text parameters, while SQLite stores any
   string happily.
3. psycopg interpolates on `%`, so a literal percent in SQL breaks the
   statement.

Treat a Postgres run as mandatory before deploying a migration.

## Isolation

The Postgres fixture creates a **throwaway schema per test** and drops it
afterwards, so a run cannot collide with the application's tables or with
another concurrent run. Nothing it does is visible outside that schema.

## Layout

| File | Covers |
| --- | --- |
| `conftest.py` | the two-engine `db` fixture, `sqlite_db`, `temp_home` |
| `test_migrations.py` | discovery, statement splitting, drift, rollback |
| `test_identity_repository.py` | field fidelity against the Phase 2 JSON record |
| `test_identity_store_binding.py` | Phase 2 `identity.py` running on the database |
| `test_job_queue.py` | idempotency, lease recovery, no duplicate effect |
| `test_object_store.py` | content addressing, traversal safety, atomicity |
| `test_wallets_and_audit.py` | money invariants, concurrent overdraw, redaction |
| `test_otp_repository.py` | single use, no plaintext at rest |
| `test_isolation.py` | user A cannot see or change user B's data |
| `test_health.py` | liveness vs readiness, backup evidence |
| `test_connection_portability.py` | DSN redaction, parameter coercion, placeholders |
