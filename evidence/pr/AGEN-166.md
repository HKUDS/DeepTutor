# PR: test(book): cover SpineSynthesizer materialise, revise loop and fallback paths (14.0% → 94%)

`deeptutor/book/agents/spine_synthesizer.py` — the agent that turns a book's LLM proposal into the chapter spine and concept graph driving the reading flow — had only 14.0% line coverage (339 of 394 statements missing). The existing `tests/book/test_spine_synthesizer_llm_call.py` exercises only the LLM call itself, so every downstream seam was unverified: parsing of real payloads, tolerance of unusable LLM output, the draft→critique→revise loop, and the ordering/invariant logic. This PR adds 20 tests covering those seams without touching any product code.

## Summary

- Adds `tests/book/test_spine_synthesizer.py` (20 cases, +620 lines).
- No product code is modified; every case mocks `BaseAgent.stream_llm` to replay offline strings, so the suite makes no network calls and runs in ~0.4s. Each case injects a tmp `agents.yaml` derived from `DEFAULT_AGENTS_SETTINGS`, so nothing depends on local runtime config.
- Module line coverage goes from 339 missing / 14.0% to **24 missing / 94%** (394 statements), measured over the two spine test files together.
- Complements rather than duplicates the existing LLM-call test: that file covers the call; this file covers everything downstream of the reply.

## Root cause

An internal coverage audit of the lowest-covered backend modules ranked the book spine synthesizer among the top gaps (14.0%). Because the module tolerates unusable LLM output by construction (fallback chapters, silently skipped graph noise, best-effort ordering), none of those degradation branches nor the structural invariants (chapter count/order stability, cycle breaking, field clamping) were executed by any test, leaving book spine generation unguarded against regressions.

## Changes

- `tests/book/test_spine_synthesizer.py` (new): 20 tests in three arms —
  - **Materialisation**: payload → chapter and concept-graph objects, concept dependencies lifted to chapter edges, `exploration_summary` passthrough, the `process` adapter, proposal/chunks rendered into the prompts.
  - **Fallbacks**: empty output / invalid JSON / missing `chapters` key → single "Overview" fallback chapter; unparseable critique → treated as no findings (no revision); missing revise prompt → draft kept.
  - **Invariants**: concept dependencies reorder chapters and renumber `order`; chapter count unchanged under cyclic dependencies (weakest-rationale edge broken); title dedup and field clamping (objectives ≤ 6, prerequisites ≤ 4, anchors ≤ 6, OVERVIEW entries kept with a type downgrade); unknown-concept edges dropped; disconnected chapters get a virtual root; Jaccard-based backfill assigns uncovered concepts to the most relevant chapter; `clip`/`slug` helpers tolerate garbage.
- CI-parity formatting: the file passes `ruff format --check` under ruff 0.16.0, the version `tests.yml` pins for its format gate.

## Tests

Verified on this branch (based on the current `dev` tip `ef2d9e5c3`, v1.6.12; fresh worktree seeded only with the gitignored runtime `data/user/settings/agents.yaml` that the pre-existing llm-call test reads):

- `python -m pytest tests/book/test_spine_synthesizer.py -q` → **20 passed in 0.30s**
- `python -m pytest tests/book/test_spine_synthesizer.py tests/book/test_spine_synthesizer_llm_call.py -q` → **25 passed in 0.24s**
- `python -m pytest tests/book -q` → **200 passed, 1 warning in 0.90s** (no cross-test pollution)
- `coverage run --source=deeptutor.book.agents.spine_synthesizer -m pytest tests/book/test_spine_synthesizer.py tests/book/test_spine_synthesizer_llm_call.py -q && coverage report -m` → **394 stmts, 24 miss, 94%**
- `ruff check tests/book/test_spine_synthesizer.py` and `ruff format --check tests/book/test_spine_synthesizer.py` (ruff 0.16.0) → pass
- `pre-commit run --files tests/book/test_spine_synthesizer.py` → all hooks passed

## Related issue

No upstream issue tracks this gap; this PR comes from an internal coverage audit of the lowest-covered modules. "Related to" only — it adds tests exclusively and fixes nothing by itself.
