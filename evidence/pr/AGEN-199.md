# PR: fix(migration): scope unreadable-journal rejection to migration paths

## Summary

- A corrupted (partially written / zero-byte) `operation.json` migration journal was invisible to pending-recovery checks: `operations()` silently skipped unreadable journals, so `assert_no_pending_recovery()` never saw them and new migrations could start while a recovery was still pending.
- This PR makes unreadable journals visible and actionable, while rejecting them only on migration-class paths — not on the per-request precheck that guards every non-settings endpoint.
- `operations()` now lists unreadable journals with `status="unreadable"` (including the full journal path in `error`), and `recover_operation()` quarantines them (rename to `operation.json.corrupt`) instead of raising, so Settings → Data migration can show and clear the blockage without a manual fix.

## Root cause

`_journal_rows()` in `deeptutor/services/workspace/data_migration.py` iterated journal directories and skipped any directory whose `operation.json` failed to parse. Consequently:

1. `operations()` (Settings → Data migration) hid corrupted journals, so the error message's advice to check that page was a dead end.
2. `assert_no_pending_recovery()` — which consumes the same rows — treated the workspace as clean, letting `migrate_data` / `export_data` / KB and session moves proceed despite a possibly in-flight migration with an unreadable journal.
3. Recovering the corrupted entry hit `json.loads` on the same broken file and raised (`JSONDecodeError`), leaving no in-app way out.

A naive fix (rejecting unreadable journals in `assert_no_pending_recovery()` itself) was rejected during review because that function runs via `activity.py` on every non-settings request: a single corrupt file would 404-lock the entire app. The final fix adds a `reject_unreadable` parameter (default `False`) and opts in only migration-class callers.

## Changes

- `deeptutor/services/workspace/data_migration.py` (+87/−13 core):
  - `_journal_rows()` yields `(path, None)` for unreadable journals instead of skipping them; no logging here (runs on every request).
  - `assert_no_pending_recovery(reject_unreadable=False)`: unreadable journals only raise when `reject_unreadable=True`; the error names the full journal path.
  - `migrate_data`, `export_data`, and the recovery gate pass `reject_unreadable=True`.
  - `operations()` lists unreadable journals as `status="unreadable"` (id = directory name, `created_at` = mtime, `error` contains the full path) and logs one bounded warning per settings-page load.
  - `recover_operation()` quarantines an unreadable journal by renaming it to `operation.json.corrupt` (snapshot kept for inspection) and returns `status="recovered"` + `recovery_path`; a warning is logged at quarantine time.
- `deeptutor/services/workspace/kb_move.py`, `session_move.py`, `deeptutor/api/routers/workspace.py` (1–2 lines each): pass `reject_unreadable=True` on the migration/exclusive branches only.
- `tests/services/workspace/test_data_migration.py` (+42): `test_unreadable_journal_blocks_only_migration_paths` asserts the four behaviors — listed as unreadable in `operations()`; per-request precheck and `acquire_activity()` keep working (no app-wide lockout); `assert_no_pending_recovery(reject_unreadable=True)` and `migrate_data` reject with the full journal path (matched via `re.escape` so the test is portable to Windows path separators); `recover_operation` quarantines the file and clears the block.

## Tests

All commands run on the single squashed commit rebased on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/services/workspace/test_data_migration.py -k "test_unreadable_journal_blocks_only_migration_paths" -q` → **1 passed, 16 deselected**
- `python -m pytest tests/services/workspace/ tests/api/test_workspace_router.py tests/app/test_startup_data_migrations.py -q` → **88 passed** (matches the pre-existing baseline)
- Red-green: on unmodified `dev` (`ef2d9e5c3`) the new test fails (`KeyError` — the corrupt journal is invisible in `operations()`), verified during review of the v2 branch; the base commit is unchanged by the rebase, so the red baseline still holds.
- `ruff check <5 changed files>` → All checks passed
- `ruff format --check <5 changed files>` → 5 files already formatted

## Related issue

None — found during an internal review of the pending-recovery guard (`AGEN-117` audit trail). No upstream issue or PR covers this path (checked before preparing this PR).
