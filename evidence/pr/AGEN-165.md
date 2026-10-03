# PR: test(api): add memory workbench router contract tests (24 cases)

`deeptutor/api/routers/memory.py` had no route-level tests (31.9% line coverage, 246 uncovered lines). This PR adds `tests/api/test_memory_router_contract.py` with 24 TestClient contract tests covering the memory workbench endpoints. No product code is changed.

## Summary

- Add `tests/api/test_memory_router_contract.py` (+571 lines): 24 TestClient contract tests for `deeptutor/api/routers/memory.py`, the router behind the memory workbench UI (document view/edit, settings, trace, snapshot, consolidator runs, backups).
- Three test groups:
  1. **GET response shapes** (7 cases): overview (11-doc row structure + backups), doc raw text, lines view, settings default schema, trace pagination, snapshot (entities + pending changes), backup list.
  2. **Edit/delete round-trip consistency** (7 cases): PUT /doc read-back, entry delete keeps siblings, apply ops persist, PUT settings merge read-back, trace per-day clear and full clear, snapshot refresh/changes/clear, run lifecycle (stubbed runner — no LLM calls).
  3. **Invalid params / missing entries → 4xx** (10 cases): invalid layer 400, unknown surface/slot 404, missing body 422, run start invalid combinations (400/404/405/422), unknown run (404/409), trace invalid date 400 / missing file 404, snapshot unknown surface, legacy streaming endpoint param pre-validation.

## Root cause

No product defect. A coverage audit showed `deeptutor/api/routers/memory.py` at 31.9% line coverage with 246 missing lines — the memory workbench read/edit/delete contracts had no route-level protection, so a regression in these endpoints (which directly affect user memory data) could pass the existing suite unnoticed. This PR closes that gap with isolated contract tests only.

## Changes

- New file `tests/api/test_memory_router_contract.py` (+571 lines).
- Zero product-code changes (`deeptutor/` untouched).
- Full isolation: `paths.memory_root` redirected to `tmp_path`, in-memory `ConfigManager` stand-in (no writes to the real `main.yaml`), snapshot adapters stubbed, run manager reset symmetrically per case, runner coroutine stubbed — no real LLM calls, no network, no persistent side effects.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/api/test_memory_router_contract.py -q` → **24 passed**
- `python -m pytest tests/api -q` → **770 passed** (746 pre-existing + 24 new; combined run shows no cross-test pollution)
- `python -m pytest tests/api/test_memory_resolver.py tests/services/memory -q` → **152 passed**
- `ruff check tests/api/test_memory_router_contract.py` → All checks passed
- `ruff format --check tests/api/test_memory_router_contract.py` → clean
- `python scripts/check_architecture.py` → OK
- `python scripts/check_workspace_hygiene.py` → passed
- `memory.py` line coverage: **31.9% → 74%** (missing lines 246 → 95; the remaining 95 are the LLM run execution body and SSE streaming internals that require a live consolidator, out of scope for stubbed contract tests)

## Related issue

Related to the memory workbench router coverage gap identified in an internal coverage audit. No upstream issue exists yet; this PR is standalone test hardening with no behavior change.
