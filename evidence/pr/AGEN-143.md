# PR: test(research): lock deep_research four-phase orchestration contract

`deeptutor/agents/research/pipeline.py` — the deep_research capability's four-phase orchestrator — had no end-to-end stage-contract tests (61.9% statement coverage, 408 statements missing per the coverage report's gap list). This PR adds `tests/agents/research/test_pipeline_stage_contract.py` with 6 tests that lock the rephrase → decompose → research → report contract at the pipeline boundary. No product code is changed.

## Summary

- Add `tests/agents/research/test_pipeline_stage_contract.py` (+366 lines): 6 tests covering the `ResearchPipeline` orchestration contracts:
  1. **Planning run** (`confirmed_outline=None`): stage order `rephrasing → decomposing`; outline-preview payload contract (`response=""`, `output_dir=""`, `outline_preview=True`, refined `topic`, `sub_topics=[{title, overview}]`); decompose receives the rephrased topic; the planning stage itself must not emit the capability result.
  2. **`rephrase_enabled=False`**: the `rephrasing` stage context is still emitted, the LLM loop is skipped, and the raw topic is passed through stripped.
  3. **Confirmed run** (non-empty `confirmed_outline`): stage order `researching → reporting`; rephrase/decompose skipped (no second clarification round); result `metadata` contract (`mode="agentic_research"`, `topic`, `block_count`, `citation_count`, `partial`, `failed_block_count`, `failed_block_titles`); `emit_capability_result` exactly once with `source="deep_research"`; report assembled in outline section order (`# title → ## 1. Introduction → ## sections → ## Conclusion`).
  4. **Empty retrieval short-circuit**: `confirmed_outline=[]` → zero blocks queued, still `researching → reporting`, full result envelope with `block_count=0, citation_count=0, partial=False`, no exception.
  5. **Empty knowledge blocks**: a COMPLETED block with empty knowledge still yields a report with `partial=False` (partial reflects status only).

## Root cause

No product defect. A coverage audit identified `deeptutor/agents/research/pipeline.py` as coverage gap #7 (61.9% statement coverage, 408 statements missing): the four-phase orchestration — stage transition order, the outline-preview and final result envelope shapes, the confirmed-outline planning skip, and the empty-retrieval short-circuit — had no regression protection, so a refactor that changed any of these contracts would pass the existing suite unnoticed. This PR closes that gap with isolated contract tests only (a green regression lock; mutation-checked: flipping `outline_preview` makes the tests fail).

## Changes

- New file `tests/agents/research/test_pipeline_stage_contract.py` (+366 lines).
- Zero product-code changes (`deeptutor/` untouched).
- Full isolation: the LLM seam is mocked at the `deeptutor.runtime.agentic` primitives (`run_agentic_loop` / `run_labeled_step`), so the real pipeline orchestration, `StreamBus` stage events, dynamic task queue, and result envelope run end to end with no network access and no LLM calls. Constructor patches follow the existing `test_pipeline_partial_failure.py` conventions (`get_llm_config` / `get_tool_registry`, plus no-op `_prepare_pageindex_tools` and a sentinel `_build_client`).

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12), with `ruff format` applied:

- `python -m pytest tests/agents/research/test_pipeline_stage_contract.py -v` → **6 passed**
- `python -m pytest tests/agents/research/ -q` → **83 passed** (no regression)
- `python -m pytest tests/agents/research/ tests/capabilities/test_rag_consistency.py tests/core/test_capabilities_runtime.py -q` → **94 passed**
- `ruff check tests/agents/research/test_pipeline_stage_contract.py` → All checks passed
- `ruff format --check tests/agents/research/test_pipeline_stage_contract.py` → clean
- `python scripts/check_architecture.py` → OK
- `python scripts/check_workspace_hygiene.py` → passed
- `pipeline.py` statement coverage: **61.9% → 73.8%** (+132 statements, measured with stdlib `trace` + AST statement counting; the remainder is the live LLM loop body and retrieval internals out of scope for stubbed contract tests)

## Related issue

Related to the deep_research pipeline coverage gap identified in an internal coverage audit. No upstream issue exists yet; this PR is standalone test hardening with no behavior change.
