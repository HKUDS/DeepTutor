# PR: fix(memory): log corrupt snapshot files instead of skipping silently

## Summary

- `deeptutor/services/memory/snapshot/adapters.py` silently skipped unreadable or corrupt JSON files when building memory snapshots. This PR adds a `logger.warning` (file path + exception summary, never file contents) at each of the three skip sites, so missing snapshot entities become diagnosable instead of silently disappearing.
- Skipping behavior itself is unchanged: corrupt files are still skipped and all readable entries are still produced, so snapshot semantics are 100% preserved.
- Adds 3 regression tests (one corrupt file per source: notebook file, co-writer manifest, book manifest) asserting both the warning and that remaining entities are still generated.

## Root cause

`read_notebook_entities`, `read_cowriter_entities`, and `read_book_entities` each wrapped their JSON read in a bare `except (OSError, json.JSONDecodeError): continue`. A truncated manifest or an unreadable notebook file therefore vanished from the memory snapshot with no trace, making "why is my notebook/book missing from memory?" impossible to debug from logs.

## Changes

- `deeptutor/services/memory/snapshot/adapters.py` (+6/−3): capture the exception and log one warning per skipped file, e.g. `notebook snapshot skipped corrupt file: <path> (<exc>)`. Message style matches the existing `chat`/`quiz` warning patterns in the same file; file contents are never logged.
- `tests/services/memory/test_snapshot_adapters.py` (+109): 3 new tests — `test_corrupt_notebook_file_skipped_with_warning`, `test_corrupt_cowriter_manifest_skipped_with_warning`, `test_corrupt_book_manifest_skipped_with_warning`. Each uses a mocked `PathService` with one corrupt and one valid file, and asserts via `caplog` that a warning naming the corrupt path is emitted while the valid entity is still returned.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/services/memory/test_snapshot_adapters.py -v` → **10 passed** (7 pre-existing + 3 new)
- `python -m pytest tests/services/memory -q` → **151 passed, 0 failed** (full memory subsystem, no cross-test pollution)
- Red-green check: with the product-code change reverted (pre-fix `dev` state), the 3 new tests fail (**3 failed, 7 passed**), confirming they pin the fix.
- `ruff check deeptutor/services/memory/snapshot/adapters.py tests/services/memory/test_snapshot_adapters.py` → All checks passed
- `ruff format --check <same files>` → 2 files already formatted

## Related issue

None — found during an internal error-handling audit of silent `except: continue` sites in the memory snapshot pipeline.
