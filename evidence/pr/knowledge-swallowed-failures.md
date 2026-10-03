# fix(knowledge): surface swallowed KB status and progress failures

## Summary

Three failure points in the knowledge-base surface swallowed their errors with
`except Exception: pass`, so a broken write or teardown path left no trace and
the KB status/progress shown to users silently diverged from reality:

- `KnowledgeBaseManager.update_kb_status` swallowed every failure of the
  ready-transition metadata refresh (embedding signature / `index_versions`),
  so a KB could be marked "ready" while its persisted entry was already stale.
- The `websocket_progress` endpoint swallowed five failure points: two
  timestamp parses, error-frame delivery, socket close, and the multi-user
  context reset — a corrupt progress snapshot or a leaked user context
  vanished without a trace.
- `run_reindex_task` swallowed a failed error-progress write, so a failed
  rebuild could leave the KB progress view looking live/stale with nothing in
  the logs explaining it.

This PR keeps all best-effort semantics (indexing itself never fails on
progress bookkeeping) but makes every degraded path visible: warnings for real
faults, debug traces for expected disconnect noise, and — where the failure
must reach callers — the original exception still propagates.

## Changes per site

- `deeptutor/knowledge/manager.py` — `update_kb_status`:
  - Ready-transition metadata refresh: `except Exception: pass` → `except
    Exception as exc` with a `warning` naming the KB. The refresh stays
    best-effort.
  - `self._save_config()` failure: now logged at `error` level (KB name +
    status) and re-raised — callers keep receiving the exception, exactly as
    before this PR; the log replaces silence, not the raise.
- `deeptutor/api/routers/knowledge.py` — `websocket_progress`:
  - New `_progress_age_seconds(timestamp)` helper shared by both freshness
    checks; the catch is narrowed to `(TypeError, ValueError)` and an
    unparseable timestamp logs a `warning` (a corrupt snapshot can no longer
    silently disable liveness detection). The already-parsed snapshot age is
    reused by the replay decision, so one corrupt timestamp produces one
    warning per connection, not one per check.
  - Failed error-frame delivery and failed socket close now log at `debug`
    (usually an already-disconnected client, not a fault).
  - A failed `reset_current_user` logs at `warning`: leaking the user context
    is a real fault, not a disconnect.
- `deeptutor/api/routers/knowledge.py` — `run_reindex_task`:
  - The error-path `ProgressTracker(ERROR)` write wrapped in `except
    Exception: pass` now logs a `warning` (task id, KB name, the underlying
    error). The task-level error status stays authoritative; the warning makes
    a stale KB progress view explainable.

## Tests

All commands run against a branch based on the current `dev` tip
(`ef2d9e5c3`, v1.6.12); mocked/stubbed services only, no real backends:

- `python -m pytest tests/api/test_knowledge_progress_ws.py -q` → **6 passed**
  (3 new: malformed timestamp logged + degraded, task_id connection warns
  exactly once, cleanup/error-delivery failures logged and never propagate;
  plus a regression test that normal disconnects stay quiet at WARNING+)
- `python -m pytest tests/api/test_knowledge_router.py -q` → **125 passed**
  (1 new: a failed error-progress write is warned, task metadata still
  reflects the original indexing failure)
- `python -m pytest tests/knowledge/test_manager_update_kb_status_failures.py -q`
  → **3 passed** (successful update persists; `_save_config` failure is logged
  at ERROR **and** re-raised to the caller; metadata-refresh failure warns
  while the status write still lands)
- `python -m pytest tests/knowledge --ignore=tests/knowledge/test_linked_folder_sync.py -q`
  → **161 passed** (no regression; the ignored file fails for unrelated
  environment reasons on `dev`)

## Related issue

Related to #1612 (truthful/resumable indexing progress — this PR removes
silent failure paths from the status/progress surface; it does not implement
resumability itself).
