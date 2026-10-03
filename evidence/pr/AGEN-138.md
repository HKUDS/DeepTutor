# PR: fix(launcher): log handoff failure when mark_failed fails too

## Summary

- When a pending self-update is handed off to a fresh worker process, a handoff failure is recorded by marking the update job failed. In `_handoff_pending_update` that fallback `store.mark_failed(...)` call sat inside a bare `except Exception: pass`: if marking the failure also failed (corrupt state, IO error), the launcher shut down with no persistent trace of either error.
- This PR keeps the minimal fix: the recording failure is caught into a named exception and a fallback log line is emitted naming the update job, the original handoff error, and the recording error, before the existing `return False`. No behavior or return-value semantics change.

## Root cause

In `_handoff_pending_update()` (`deeptutor/runtime/launcher.py`), the outer `except Exception` handler calls `store.mark_failed(job.id, f"Launcher handoff failed: {exc}")` to move the pending job to `failed`. That call had its own `except Exception: pass`, so when the update store was unwritable or its state corrupt:

1. `mark_failed()` raised inside the handler and the exception was discarded — the job never transitioned to `failed` and no log line was produced.
2. A double failure (handoff + recording) was indistinguishable from a clean shutdown: no job ID, no handoff error, no recording error anywhere, making the stuck update undebuggable from logs alone.

## Changes

- `deeptutor/runtime/launcher.py` (+5 / −2): the bare swallow becomes `except Exception as mark_exc` and emits one `_log(...)` line — `Launcher handoff failed for update {job.id}: {exc} (could not record failure: {mark_exc})` — matching the log style of the preceding systemd-rejection path in the same function; still `return False`.
- `tests/runtime/test_launcher.py` (+37 / −1): new test `test_launcher_handoff_failure_still_logged_when_marking_fails` — injects a worker launcher that raises `RuntimeError` and a `mark_failed` that raises `OSError`, captures `_log` output, and asserts the handoff result stays `False` while the log trace contains the job marker, the handoff error and the recording error.

## Tests

All commands run on the branch rebased on the current `dev` tip (`ef2d9e5c3`, v1.6.12; the rebase was a no-op — the fix commit sits directly on that tip):

- `pytest tests/runtime/test_launcher.py -k test_launcher_handoff_failure_still_logged_when_marking_fails -v` → **1 passed, 35 deselected**
- `pytest tests/runtime tests/services/test_app_update.py` → **214 passed, 4 skipped**
- Red-green: running the new test on the unmodified baseline code fails with `AssertionError: double handoff failure vanished without any log`; it passes on the fix branch.
- `ruff check deeptutor/runtime/launcher.py tests/runtime/test_launcher.py` → All checks passed
- `ruff format --check deeptutor/runtime/launcher.py tests/runtime/test_launcher.py` → 2 files already formatted

## Related issue

None — found during an internal review of the launcher update-handoff path. No upstream issue or PR covers this path (searched `_handoff_pending_update`, "handoff mark_failed", "launcher handoff" across open and closed upstream PRs before preparing this PR; no matches).
