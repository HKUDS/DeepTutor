# PR: test(book): cover engine stage transitions

## Summary

- Adds `tests/book/test_engine_stage_transitions.py` (+495 lines): regression coverage for the three guarantees a long book-generation run depends on in `deeptutor/book/engine.py` — stage order with per-stage artefact persistence, single-stage failure retry without duplicating output, and pause/resume recovery that never re-pays finished pages.
- Pure test addition: no product code is touched, no API or behavior change.
- All agents (ideation/exploration/synthesizer/compiler) are replaced by lightweight async fakes — no LLM calls, no network, ~0.5s per run.

## Root cause

`deeptutor/book/engine.py` drives the longest-running generation flow in the project but had only 43% line coverage in the `tests/book` scope (535 of 945 statements uncovered, DT-21 Top-15 gap #6). The stage-transition invariants — every stage persists its artefacts before advancing, retries do not re-pay or duplicate work, and a user pause mid-compile is fully recoverable — were not pinned by any test, so a regression in the state machine would surface only in real multi-hour runs.

## Changes

- `tests/book/test_engine_stage_transitions.py` (+495): 4 tests with a shared FakeStorage + FakeCompiler harness:
  - `test_stages_advance_in_order_and_persist_each_artefact` — create_book → DRAFT → confirm_proposal → SPINE_READY → confirm_spine → COMPILING → READY, asserting per-stage artefact persistence and the `proposal_ready → exploration_ready → spine_ready → overview_ready` StreamBus event order.
  - `test_exploration_failure_degrades_and_retry_does_not_duplicate` — exploration failure degrades gracefully (spine still generated from the proposal), and retry clears the failure marker without duplicating exploration or spine artefacts.
  - `test_compile_failure_marks_the_page_and_retry_pays_only_for_it` — a failing page lands in ERROR while the book stays COMPILING and sibling pages are unaffected; retry invokes the compiler only for the failed page.
  - `test_pause_mid_compile_then_resume_finishes_without_repaying_ready_work` — pausing mid-compile flips the book to PAUSED, in-flight pages return to PENDING, compiles are rejected with `BookPausedError`, and resume re-queues only unfinished pages without re-compiling READY/Overview pages.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/book/test_engine_stage_transitions.py -v` → **4 passed** in ~0.7s
- `python -m pytest tests/book -q --cov=deeptutor.book.engine` → **184 passed** (baseline 180); `engine.py` line coverage **43% → 62%** (945 stmts, miss 535 → 359)
- `python -m pytest tests/book tests/reading -q` → **586 passed**
- `python -m pytest tests/architecture tests/core tests/logging tests/runtime -q` → 492 passed, 4 skipped, plus 1 pre-existing order-dependent failure (`test_api_import_memory_boundary.py::test_api_import_keeps_optional_heavy_dependencies_cold`) that reproduces identically on clean `dev` without this change and passes when run standalone
- `ruff check tests/book/test_engine_stage_transitions.py` → All checks passed
- `ruff format --check tests/book/test_engine_stage_transitions.py` → 1 file already formatted

## Related issue

None — `deeptutor/book/engine.py` was ranked #6 in an internal coverage-gap audit (DT-21 Top 15). No open upstream issue tracks these stage-transition invariants.
