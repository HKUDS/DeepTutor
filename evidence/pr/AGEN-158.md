# PR: fix(workspace): surface skipped corrupt sources in migration dependency closure

`deeptutor/services/workspace/dependencies.py` computed the workspace migration dependency closure with four `except ...: continue` blocks (book manifests, notebook/co-writer/timed_media/courses feature documents, message `metadata_json`, and PocketBase message metadata). When any of these sources was corrupt or unreadable, it was silently skipped, so a migrated workspace could quietly miss sessions and references with no log line and no signal to the caller. This PR keeps the skip semantics (a corrupt source must never abort a migration) but makes every skip visible: each one logs a warning containing only the file path or session id plus the parse error, and the migration `preview()` response gains a `warnings` field so callers can show what will be left behind before moving.

## Summary

- New `_warn()` helper (`dependencies.py`): logs at `WARNING` level and appends to an optional caller-supplied `warnings` list, deduplicated so multi-round closure scans emit each skip exactly once.
- The four silent `except ...: continue` sites now report the skipped source:
  - book manifest: `Skipping unreadable book manifest <path>: <error>`
  - feature document: `Skipping unreadable <feature> document <path>: <error>`
  - message metadata: `Skipping unreadable message metadata for session <sid>: <error>`
  - PocketBase metadata: `Skipping unreadable PocketBase message metadata for session <sid>: <error>`
- `dependency_closure()`, `_forward_closure()`, and `_with_historical_references()` accept an optional `warnings` list (default `None`, fully backward compatible) and thread it through all closure rounds.
- `preview()` in `data_migration.py` passes the list through and includes it as a `warnings` field in its response; `migrate_data()` reuses `preview()`, so the actual migration path is covered too.

## Root cause

The closure intentionally tolerates corrupt sources — one unreadable manifest must not block moving an entire workspace. But tolerance was implemented as silence: the `continue` left no trace in the logs and no field in the preview response, so after a migration the user simply discovered missing sessions/references with no way to correlate them to the skipped files. The information needed to diagnose (which file/session failed and why) was discarded at the exact point of failure.

## Changes

- `deeptutor/services/workspace/dependencies.py` (+63/-12 net with tests below): add `_warn()`; capture exceptions at the four skip sites; thread the optional `warnings` parameter through `dependency_closure`, `_forward_closure`, and `_with_historical_references`. No control-flow changes: corrupt sources are still skipped and healthy dependencies still form the same closure.
- `deeptutor/services/workspace/data_migration.py` (+4/-1): `preview()` threads `warnings` and returns them in its response dict (additive field).
- `tests/services/workspace/test_data_migration.py` (+91): 3 regression tests — corrupt book manifest + corrupt feature json (warnings visible in the returned list and in `caplog`, healthy manifest/document dependencies still collected, no file payload leaked into warnings), corrupt message `metadata_json` (warning names the session id), and `preview()` returning the `warnings` field.

Warnings contain only the path or session id and the exception message — never file contents. The `warnings` parameter is optional everywhere, so existing callers are unaffected.

## Tests

Fail-first check: on the pre-fix baseline (`dev` @ `ef2d9e5c3`, v1.6.12) the new tests fail (`TypeError` on the `warnings` keyword / missing response field), then pass with the fix.

All commands below pass on this branch (rebased onto the current `dev` tip `ef2d9e5c3`):

- `python -m pytest tests/services/workspace -q` → **84 passed** (baseline without the fix: 81 passed)
- `python -m pytest tests/services/workspace/test_data_migration.py -k "corrupt or warnings" -v` → **3 passed**
- `python -m pytest tests/services/workspace tests/app/test_startup_data_migrations.py tests/services/session/test_legacy_migration.py -q` → **89 passed**
- `ruff check deeptutor/services/workspace tests/services/workspace` → All checks passed
- `ruff format --check deeptutor/services/workspace tests/services/workspace` → 26 files already formatted

Note: the PocketBase metadata branch mirrors the SQLite message-metadata handling and is covered by review; it has no dedicated end-to-end test because that path requires a live PocketBase instance.

## Related issue

No upstream issue tracks this symptom; found in an internal error-swallowing audit of `dependencies.py`. Related to the notebook/chat decoupling in #1519 (last change touching this file), which is unrelated in purpose.
