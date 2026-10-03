# PR: fix(lightrag): warn when workspace meta.json exists but is unusable

`workspace_for()` in `deeptutor/services/rag/pipelines/lightrag/engine.py` swallowed every `OSError`/`ValueError` while reading a published workspace's `meta.json` and silently fell back to a path-hash workspace name. When a knowledge base is moved, that fallback name differs from the published one, so LightRAG opens an empty store — retrieval returns nothing and no log line explains why. This PR keeps the fallback behavior but logs a warning whenever an existing `meta.json` cannot be read or parsed.

## Summary

- `workspace_for()` (`engine.py:188`) now splits the previously blanket `except (OSError, ValueError): pass`:
  - `FileNotFoundError` stays silent — a missing `meta.json` is the normal state for unpublished workspaces.
  - Any other `OSError` (e.g. `PermissionError`) or `ValueError` (e.g. `JSONDecodeError`) logs a module-level `logger.warning` that includes the `meta.json` path, the exception type, and the exception message, then falls back exactly as before.
- Adds module-level `logger = logging.getLogger(__name__)` and the `logging` import.
- Adds `tests/services/rag/test_lightrag_workspace_meta.py` with 4 regression tests.

## Root cause

A published LightRAG workspace keeps its native workspace name (recorded in `meta.json`) so it survives a knowledge-base move; the name itself is a hash of the original absolute version path, so recomputing it after the move yields a different workspace. The original code treated "meta.json unreadable/corrupt" the same as "meta.json absent": both fell through to the recomputed hash, which silently opens an empty store with zero log trail. The failure is invisible to users (empty retrieval results) and to operators (nothing in the logs to correlate with the move).

## Changes

- `deeptutor/services/rag/pipelines/lightrag/engine.py` (+8/-2): split the exception handling in `workspace_for()`; add `logging` import and module logger. No control-flow, return-value, or caller-visible behavior changes.
- `tests/services/rag/test_lightrag_workspace_meta.py` (new, 4 cases):
  1. corrupt JSON → warning containing `meta.json` and `JSONDecodeError`, returns hash name;
  2. unreadable file (`chmod 0o000`) → warning containing `PermissionError`, returns hash name;
  3. missing file → hash name, no warning;
  4. valid meta → published name, no warning.

## Tests

Fail-first check: on the pre-fix baseline (`origin/main` @ `ef2d9e5c3`) this suite reports **2 failed, 2 passed** — exactly the two warning assertions fail, then all 4 pass with the fix.

All commands below pass on this branch (based on the current `dev` tip `ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/services/rag/test_lightrag_workspace_meta.py -v` → **4 passed**
- `python -m pytest tests/services/rag -q -k lightrag` → **176 passed, 28 skipped**
- `python -m pytest tests/multi_user/test_kb_move.py -v` → **14 passed** (KB-move scenario that depends on `workspace_for()` name stability)
- `python -m pytest tests/services/rag -q` → **638 passed, 31 skipped**
- `ruff check deeptutor/services/rag/pipelines/lightrag/engine.py tests/services/rag/test_lightrag_workspace_meta.py` → All checks passed
- `ruff format --check <same files>` → already formatted
- `pre-commit run --files <same files>` → all hooks Passed

Note: the permission-error test uses `chmod(0o000)`, which is POSIX-oriented; upstream CI (`python-tests`) runs on `ubuntu-latest`, where the behavior is POSIX.

## Related issue

No upstream issue tracks this silent-empty-store symptom yet; this PR is a standalone observability fix found in an internal error-swallowing audit. Related to the LightRAG workspace-name preservation behavior introduced for KB moves.
